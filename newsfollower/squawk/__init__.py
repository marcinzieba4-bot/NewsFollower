"""Squawk layer: free feeds, wire-style formatting, spoken tape."""

from .audio import Speaker, detect_backend
from .calendar import INDICATORS, Release, find_indicator, parse_release
from .format import SquawkLine, compress, detect_region, split_speaker, to_squawk
from .tape import Tape

__all__ = [
    "INDICATORS", "Release", "Speaker", "SquawkLine", "Tape", "compress",
    "detect_backend", "detect_region", "find_indicator", "parse_release",
    "split_speaker", "to_squawk",
]
