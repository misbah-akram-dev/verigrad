"""Best-effort page preparation before capture (decisions D8, D12). Never fails a fetch.

Expands only `<details>` and `aria-expanded="false"` toggles — never generic `role=button`
elements. If a click navigates away, we go back, record it, and retry once without that toggle;
a second navigation stops expansion.

Then reveals, without clicking, hidden panels that a visible toggle points at (accordion/collapse
panels, inactive tabs; D32). Hidden text nothing points at stays hidden, so `text.txt` minus
`visible_text.txt` still means "deliberately invisible".
"""

import logging
from urllib.parse import urldefrag

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request

from verigrad.core.fetch.models import PrepStats, RevealedPanels

log = logging.getLogger(__name__)

SETTLE_TIMEOUT_MS = 10_000
MAX_TOGGLES = 50
AFTER_CLICK_MS = 250
MAX_PANELS = 300
ANIMATION_WAIT_MS = 1_000  # let accordions finish closing (single-open) before revealing
REVEAL_ROUNDS = 3  # a revealed panel can hold toggles for nested panels

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


# One reveal round (D32). A panel is shown only when a rendered toggle points at it by id
# (aria-controls, a `data-*target="#id"` attribute, or href="#id"). Tab toggles (role=tab,
# data-toggle=tab/pill) may sit in a <nav> (tab lists do); other toggles must be outside nav and
# header (menus). Menus and overlays are never panels. Styles are set through CSSOM, which a
# page's CSP can't block. A panel still unrendered afterwards (a hidden non-panel ancestor) is
# restored. Returns counts by panel type.
_REVEAL_PANELS_JS = """
(max) => {
  const isRealLink = (el) => {
    if (el.tagName !== 'A') return false;
    const href = (el.getAttribute('href') || '').trim();
    return href !== '' && !href.startsWith('#') && !href.toLowerCase().startsWith('javascript:');
  };
  const toggleAttr = (el) =>
    (el.getAttribute('data-bs-toggle') || el.getAttribute('data-toggle') || '').toLowerCase();
  const toggleKind = (el) => {
    const t = toggleAttr(el);
    if (el.getAttribute('role') === 'tab' || ['tab', 'pill', 'list'].includes(t)) return 'tab';
    if (el.hasAttribute('aria-expanded') || t === 'collapse') return 'disclosure';
    return null;
  };
  const targetIds = (el) => {
    const ids = (el.getAttribute('aria-controls') || '').split(/\s+/).filter(Boolean);
    for (const attr of el.attributes) {
      if (!attr.name.startsWith('data-') || !attr.name.endsWith('target')) continue;
      const m = attr.value.trim().match(/^#([^\s#.,:>+~\[\]]+)$/);
      if (m) ids.push(m[1]);
    }
    const href = (el.getAttribute('href') || '').trim();
    if (/^#[^\s#]+$/.test(href)) ids.push(href.slice(1));
    return ids;
  };
  const NOT_PANEL_ROLES = ['dialog', 'alertdialog', 'menu', 'menubar', 'listbox', 'tooltip'];
  const NOT_PANEL_CLASSES = ['modal', 'offcanvas', 'dropdown-menu', 'navbar-collapse'];
  const notAPanel = (p) => p.closest('nav, header') || p.tagName === 'DIALOG'
    || NOT_PANEL_ROLES.includes(p.getAttribute('role'))
    || NOT_PANEL_CLASSES.some(c => p.classList.contains(c))
    || getComputedStyle(p).position === 'fixed';
  const isHidden = (p) => {
    if (p.getClientRects().length === 0) return true;
    const style = getComputedStyle(p);
    return style.visibility === 'hidden' || parseFloat(style.opacity) === 0
      || p.getBoundingClientRect().height === 0;
  };
  const panelType = (p, kind, toggle) => {
    if (kind === 'tab' || p.getAttribute('role') === 'tabpanel' || p.classList.contains('tab-pane'))
      return 'tab';
    if (toggleAttr(toggle) === 'collapse'
        || Array.from(p.classList).some(c => c.toLowerCase().includes('collapse')))
      return 'collapse';
    return 'disclosure';
  };
  const SHOW = [['display', 'block'], ['visibility', 'visible'], ['opacity', '1'],
    ['height', 'auto'], ['max-height', 'none'], ['overflow', 'visible'],
    ['content-visibility', 'visible']];
  const counts = {collapse: 0, tab: 0, disclosure: 0};
  let left = max;
  const toggles = document.querySelectorAll(
    '[aria-expanded], [aria-controls], [role="tab"], [data-toggle], [data-bs-toggle]');
  for (const toggle of toggles) {
    const kind = toggleKind(toggle);
    if (kind === null || toggle.closest(kind === 'tab' ? 'header' : 'nav, header')) continue;
    if (isRealLink(toggle) || toggle.getClientRects().length === 0) continue;
    for (const id of targetIds(toggle)) {
      if (left <= 0) return counts;
      const panel = document.getElementById(id);
      if (!panel || panel.hasAttribute('data-verigrad-revealed')) continue;
      if (panel.contains(toggle) || notAPanel(panel) || !isHidden(panel)) continue;
      const saved = SHOW.map(([prop]) =>
        [prop, panel.style.getPropertyValue(prop), panel.style.getPropertyPriority(prop)]);
      SHOW.forEach(([prop, value]) => panel.style.setProperty(prop, value, 'important'));
      if (panel.getClientRects().length === 0) {
        saved.forEach(([prop, value, priority]) => value
          ? panel.style.setProperty(prop, value, priority) : panel.style.removeProperty(prop));
        continue;
      }
      const type = panelType(panel, kind, toggle);
      panel.setAttribute('data-verigrad-revealed', type);
      counts[type] += 1;
      left -= 1;
    }
  }
  return counts;
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
    if stats.toggles_clicked:
        await page.wait_for_timeout(ANIMATION_WAIT_MS)
    stats.panels_revealed = await reveal_panels(page)
    await scroll_through(page)
    return stats


async def reveal_panels(page: Page) -> RevealedPanels:
    """Show hidden panels that visible toggles point at, in rounds (nested panels). No clicks."""
    total = RevealedPanels()
    for _ in range(REVEAL_ROUNDS):
        found: dict[str, int] = await _safe_eval(
            page, _REVEAL_PANELS_JS, {}, MAX_PANELS - total.total
        )
        new = RevealedPanels.model_validate(found)
        if new.total == 0:
            break
        total = RevealedPanels(
            collapse=total.collapse + new.collapse,
            tab=total.tab + new.tab,
            disclosure=total.disclosure + new.disclosure,
        )
        if total.total >= MAX_PANELS:
            break
    return total


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
