"""Polite fetching (spec §3.4, decisions D8): robots.txt, per-domain delay, same-site rule."""

import asyncio
import ipaddress
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pydantic import BaseModel

USER_AGENT_TOKEN = "Verigrad"

# Second-level labels under which universities register (kaust.edu.sa, uni.ac.uk, x.com.au).
_KNOWN_SLDS = {"ac", "co", "com", "edu", "gov", "mil", "net", "org", "sch"}


def site_key(host: str) -> str:
    """Registrable-domain approximation: `cs.kaust.edu.sa` → `kaust.edu.sa`."""
    host = host.lower().rstrip(".")
    if not host or "." not in host or _is_ip(host):
        return host
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and labels[-2] in _KNOWN_SLDS and len(labels[-1]) == 2 else 2
    return ".".join(labels[-keep:])


def url_site_key(url: str) -> str:
    return site_key(urlsplit(url).hostname or "")


def same_site(url_a: str, url_b: str) -> bool:
    return url_site_key(url_a) == url_site_key(url_b)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class RobotsVerdict(BaseModel):
    allowed: bool
    reason: str | None = None  # robots_disallowed | robots_unavailable
    crawl_delay: float | None = None


RobotsFetcher = Callable[[str], Awaitable[tuple[int | None, str]]]
"""Async `robots_url -> (status, body)`; status None means the request itself failed."""


class RobotsChecker:
    """Caches robots.txt per origin. Status handling follows RFC 9309:
    2xx → parse; 4xx → no rules (allowed); 5xx or unreachable → disallow everything."""

    def __init__(self, fetch: RobotsFetcher, user_agent: str = USER_AGENT_TOKEN) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}

    async def check(self, url: str) -> RobotsVerdict:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            self._cache[origin] = await self._load(origin)
        parser = self._cache[origin]
        if parser is None:
            return RobotsVerdict(allowed=False, reason="robots_unavailable")
        if not parser.can_fetch(self._user_agent, url):
            return RobotsVerdict(allowed=False, reason="robots_disallowed")
        delay = parser.crawl_delay(self._user_agent)
        return RobotsVerdict(allowed=True, crawl_delay=float(delay) if delay else None)

    async def _load(self, origin: str) -> RobotFileParser | None:
        status, body = await self._fetch(f"{origin}/robots.txt")
        parser = RobotFileParser()
        if status is None or status >= 500:
            return None
        if 200 <= status < 300:
            parser.parse(body.splitlines())
        else:
            parser.parse([])  # 3xx left unresolved / 4xx: no rules apply
        return parser


class DomainThrottle:
    """Spaces out requests per site (not per host). Long-lived: shared by all fetch jobs."""

    def __init__(
        self,
        delay_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.delay_seconds = delay_seconds
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    async def wait(self, url: str, min_delay: float | None = None) -> float:
        """Sleep until this site may be hit again; returns seconds waited."""
        key = url_site_key(url)
        delay = max(self.delay_seconds, min_delay or 0.0)
        waited = 0.0
        last = self._last.get(key)
        if last is not None:
            remaining = last + delay - self._clock()
            if remaining > 0:
                await self._sleep(remaining)
                waited = remaining
        self._last[key] = self._clock()
        return waited
