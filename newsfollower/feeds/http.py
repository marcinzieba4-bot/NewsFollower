"""Polite conditional-GET client.

Polling twenty public feeds every few seconds is how you get your IP banned.
Every request carries ETag / If-Modified-Since from the last response, so a
feed that has not changed costs a 304 and no body. Errors back off
exponentially and 429/503 are respected.
"""

from __future__ import annotations

import gzip
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

PRODUCT = "NewsFollower/0.2"

# BLS and SEC EDGAR require a contact address in the User-Agent - their stated
# fair-use condition - and both 403 without one. They also 403 on any UA
# containing a URL, so the form has to be exactly `Product/version (contact)`;
# adding a project link breaks both feeds. Set NEWSFOLLOWER_CONTACT to your
# email to enable them. Deliberately not hardcoded: this repo is public.
CONTACT = os.environ.get("NEWSFOLLOWER_CONTACT", "")


def user_agent() -> str:
    return f"{PRODUCT} ({CONTACT})" if CONTACT else PRODUCT


@dataclass
class CacheEntry:
    etag: str = ""
    last_modified: str = ""
    fail_count: int = 0
    next_allowed_ts: float = 0.0


@dataclass
class Response:
    status: int
    body: bytes = b""
    not_modified: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.body)


class ConditionalClient:
    """Keeps per-URL validators and backoff state across calls."""

    def __init__(self, timeout: float = 20.0, max_backoff: float = 900.0):
        self.timeout = timeout
        self.max_backoff = max_backoff
        self._cache: dict[str, CacheEntry] = {}

    def _entry(self, url: str) -> CacheEntry:
        return self._cache.setdefault(url, CacheEntry())

    def ready(self, url: str, now: float | None = None) -> bool:
        """False while a failing URL is still in its backoff window."""
        now = time.time() if now is None else now
        return now >= self._entry(url).next_allowed_ts

    def _backoff(self, entry: CacheEntry, now: float, retry_after: float = 0.0) -> None:
        entry.fail_count += 1
        # 30s, 60s, 120s ... with jitter so many feeds do not retry in lockstep.
        delay = min(self.max_backoff, 30.0 * (2 ** (entry.fail_count - 1)))
        delay = max(delay, retry_after)
        entry.next_allowed_ts = now + delay * (0.8 + 0.4 * random.random())

    def get(self, url: str, now: float | None = None) -> Response:
        now = time.time() if now is None else now
        entry = self._entry(url)
        if now < entry.next_allowed_ts:
            return Response(0, error="backoff")

        headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip"}
        if entry.etag:
            headers["If-None-Match"] = entry.etag
        if entry.last_modified:
            headers["If-Modified-Since"] = entry.last_modified

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                entry.etag = resp.headers.get("ETag", "") or entry.etag
                entry.last_modified = resp.headers.get("Last-Modified", "") or entry.last_modified
                entry.fail_count = 0
                entry.next_allowed_ts = 0.0
                return Response(resp.status, body)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                entry.fail_count = 0
                entry.next_allowed_ts = 0.0
                return Response(304, not_modified=True)
            retry_after = 0.0
            if e.code in (429, 503):
                try:
                    retry_after = float(e.headers.get("Retry-After", "0") or 0)
                except ValueError:
                    retry_after = 60.0
            self._backoff(entry, now, retry_after)
            return Response(e.code, error=f"HTTP {e.code}")
        except Exception as e:  # network, TLS, DNS, malformed - all the same here
            self._backoff(entry, now)
            return Response(0, error=f"{type(e).__name__}: {e}")
