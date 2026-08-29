"""RSS 2.0 / Atom parsing with the stdlib only.

Public feeds are inconsistent: three date formats, namespaced Atom, HTML in
descriptions, GUIDs that are sometimes URLs and sometimes not. This normalises
all of it into `NewsItem`.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import NewsItem

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ATOM = "{http://www.w3.org/2005/Atom}"


def clean(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def parse_date(value: str | None) -> float | None:
    """RFC 822 (RSS) or ISO 8601 (Atom). Returns a UTC epoch."""
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return dt.timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    iso = value.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = time.strptime(iso[:len(time.strftime(fmt))], fmt)
            return calendar.timegm(parsed)
        except (ValueError, TypeError):
            continue
    return None


def _text(node, *names: str) -> str:
    for name in names:
        found = node.find(name)
        if found is not None:
            if found.text:
                return found.text
            # Atom <link href="..."/> carries no text.
            if found.get("href"):
                return found.get("href", "")
    return ""


def _stable_id(source: str, guid: str, title: str, link: str) -> str:
    basis = guid or link or title
    return hashlib.sha1(f"{source}|{basis}".encode("utf-8")).hexdigest()[:16]


def parse_feed(raw: bytes, source: str, *, default_symbols: tuple[str, ...] = (),
               now: float | None = None) -> list[NewsItem]:
    """Parse a feed body into NewsItems, newest last.

    Items with no usable publication date fall back to `now`, which makes them
    look fresh. That is the right trade for a squawk - a real headline with a
    broken date should still be read out - but it means the staleness filter
    cannot protect you from a feed that lies.
    """
    now = time.time() if now is None else now
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    entries = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    items: list[NewsItem] = []
    for entry in entries:
        title = clean(_text(entry, "title", f"{_ATOM}title"))
        if not title:
            continue
        link = clean(_text(entry, "link", f"{_ATOM}link"))
        body = clean(_text(entry, "description", "summary",
                           f"{_ATOM}summary", f"{_ATOM}content"))
        guid = clean(_text(entry, "guid", "{http://www.w3.org/2005/Atom}id"))
        ts = parse_date(_text(entry, "pubDate", "{http://purl.org/dc/elements/1.1/}date",
                              f"{_ATOM}updated", f"{_ATOM}published"))

        items.append(NewsItem(
            id=_stable_id(source, guid, title, link),
            headline=title,
            source=source,
            ts=ts if ts is not None else now,
            body=body[:600],
            symbols=default_symbols,
            url=link,
        ))

    items.sort(key=lambda i: i.ts)
    return items
