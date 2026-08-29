"""Source selection helpers."""

from __future__ import annotations

from ..feeds.sources import LIVE_SOURCES, PRIMARY_SOURCES, Source


def select_sources(*, primary_only: bool = False) -> tuple[Source, ...]:
    return PRIMARY_SOURCES if primary_only else LIVE_SOURCES
