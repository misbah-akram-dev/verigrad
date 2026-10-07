"""Best-effort page preparation before capture (decisions D8, D12). Never fails a fetch.

Expands only `<details>` and `aria-expanded="false"` toggles — never generic `role=button`
elements. If a click navigates away, we go back, record it, and retry once without that toggle;
a second navigation stops expansion.
"""

import logging
from urllib.parse import urldefrag

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request

from verigrad.core.fetch.models import PrepStats

log = logging.getLogger(__name__)

SETTLE_TIMEOUT_MS = 10_000
MAX_TOGGLES = 50
AFTER_CLICK_MS = 250

_COOKIE_JS = """
() => {
  const containers = document.querySelectorAll(
    '#onetrust-banner-sdk, #onetrust-consent-sdk, #CybotCookiebotDialog, #cookie-law-info-bar, '
    + '[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i], '
    + '[aria-label*="cookie" i], [aria-label*="consent" i]');
  const accept = new RegExp('^(accept( all)?( cookies)?|allow( all)?( cookies)?'
    + '|i agree|agree|ok|got it|i understand)$', 'i');
  for (const box of containers) {
    for (const el of box.querySelectorAll('button, [role="button"], input[type="button"], a')) {
      const label = (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ');
      const visible = el.getClientRects().length > 0;
      if (visible && accept.test(label)) { el.click(); return true; }
    }
  }
  return false;
}
"""

OPEN_DETAILS_JS = """
() => {
  const closed = document.querySelectorAll('details:not([open])');
  closed.forEach(d => { d.open = true; });
  return closed.length;
}
"""

# Keys every [aria-expanded] element by its document-order position, which stays the same
# whether a toggle is open or closed (so a reload can't shift keys). Returns the keys of
# clickable closed toggles.
_MARK_TOGGLES_JS = """
(max) => {
  const isRealLink = (el) => {
    if (el.tagName !== 'A') return false;
    const href = (el.getAttribute('href') || '').trim();
    return href !== '' && !href.startsWith('#') && !href.toLowerCase().startsWith('javascript:');
  };
  const keys = [];
  document.querySelectorAll('[aria-expanded]').forEach((el, i) => {
    el.setAttribute('data-verigrad-toggle', String(i));
    if (keys.length >= max) return;
    if (el.getAttribute('aria-expanded') !== 'false') return;
    if (el.closest('nav, header') || isRealLink(el)) return;
    if (el.getClientRects().length === 0) return;
    keys.push(i);
  });
  return keys;
}
"""

_CLICK_TOGGLE_JS = """
(i) => {
  const el = document.querySelector('[data-verigrad-toggle="' + i + '"]');
  if (!el || el.getAttribute('aria-expanded') !== 'false') return false;
  el.click();
  return true;
}
"""


class _NavigationWatch:
    """Detects a click taking us off the page: a main-frame navigation request, or a URL change
    other than the #fragment (SPA pushState). Fragment-only changes are normal for accordions."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.home = urldefrag(page.url).url
        self._requested = False
        page.on("request", self._on_request)

    def _on_request(self, request: Request) -> None:
        if request.is_navigation_request() and request.frame == self.page.main_frame:
            self._requested = True

    @property
    def navigated(self) -> bool:
        return self._requested or urldefrag(self.page.url).url != self.home

    def reset(self) -> None:
        self._requested = False

    def detach(self) -> None:
        self.page.remove_listener("request", self._on_request)


async def settle(page: Page, timeout_ms: int = SETTLE_TIMEOUT_MS) -> bool:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightError:
        return False
    return True


async def scroll_through(page: Page) -> None:
    """One scroll to the bottom and back, so lazy-loaded sections render."""
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
        await page.evaluate("window.scrollTo(0, 0)")
    except PlaywrightError as exc:
        log.debug("scroll failed: %s", exc)


async def prepare_page(page: Page) -> PrepStats:
    stats = PrepStats(settled=await settle(page))
    home_url = page.url
    watch = _NavigationWatch(page)
    try:
        stats.cookie_banner_dismissed = await _safe_eval(page, _COOKIE_JS, default=False)
        await page.wait_for_timeout(AFTER_CLICK_MS)
        if watch.navigated:
            await _return_home(page, home_url, stats, watch)

        skip: set[int] = set()
        for attempt in range(2):
            outcome = await _expand_once(page, stats, watch, skip)
            if outcome is None:
                break
            await _return_home(page, home_url, stats, watch)
            skip.add(outcome)
            if attempt == 1:
                stats.expansion_stopped = True
                await _safe_eval(page, OPEN_DETAILS_JS, default=0)
    finally:
        watch.detach()
    await scroll_through(page)
    return stats


async def _expand_once(
    page: Page, stats: PrepStats, watch: _NavigationWatch, skip: set[int]
) -> int | None:
    """Open details and click toggles. Returns the index of a toggle that navigated, else None."""
    stats.details_opened = max(stats.details_opened, await _safe_eval(page, OPEN_DETAILS_JS, 0))
    keys: list[int] = await _safe_eval(page, _MARK_TOGGLES_JS, [], MAX_TOGGLES)
    clicked = 0
    for key in keys:
        if key in skip:
            continue
        if await _safe_eval(page, _CLICK_TOGGLE_JS, False, key):
            clicked += 1
        await page.wait_for_timeout(AFTER_CLICK_MS)
        if watch.navigated:
            stats.toggles_clicked = max(stats.toggles_clicked, clicked - 1)
            return key
    stats.toggles_clicked = max(stats.toggles_clicked, clicked)
    return None


async def _return_home(
    page: Page, home_url: str, stats: PrepStats, watch: _NavigationWatch
) -> None:
    try:  # a navigation request may not have committed yet: wait until we are really away
        await page.wait_for_url(lambda u: urldefrag(u).url != watch.home, timeout=5_000)
        await page.wait_for_load_state("domcontentloaded", timeout=SETTLE_TIMEOUT_MS)
    except PlaywrightError:
        pass
    stats.navigated_away.append(page.url)
    log.info("a click navigated to %s; returning to %s", page.url, home_url)
    try:
        if page.url != home_url:
            await page.go_back(wait_until="domcontentloaded", timeout=SETTLE_TIMEOUT_MS)
        if urldefrag(page.url).url != watch.home:
            await page.goto(home_url, wait_until="domcontentloaded", timeout=SETTLE_TIMEOUT_MS)
    except PlaywrightError as exc:
        log.warning("could not return to %s: %s", home_url, exc)
    await settle(page, 3_000)
    watch.reset()


async def _safe_eval[T](page: Page, script: str, default: T, arg: object = None) -> T:
    try:
        result = await page.evaluate(script, arg)
    except PlaywrightError as exc:  # e.g. context destroyed by a navigation
        log.debug("prepare script failed: %s", exc)
        return default
    return result if result is not None else default
