"""Terminal tape and session log."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..models import Priority
from .format import SquawkLine

RESET = "\033[0m"
STYLES: dict[Priority, str] = {
    Priority.CRITICAL: "\033[1;97;41m",   # white on red, bold
    Priority.IMPORTANT: "\033[1;93m",     # bold yellow
    Priority.NORMAL: "\033[0;37m",
    Priority.LOW: "\033[2;37m",
}


def supports_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


@dataclass
class Tape:
    """Prints the tape, keeps a ring buffer, optionally logs to JSONL."""

    colour: bool = True
    keep: int = 500
    log_path: Path | None = None
    stream: object = None

    def __post_init__(self) -> None:
        self.stream = self.stream or sys.stdout
        self.lines: deque[SquawkLine] = deque(maxlen=self.keep)
        self.counts: dict[str, int] = {}
        if self.colour is True:
            self.colour = supports_colour(self.stream)
        self._log = self.log_path.open("a", encoding="utf-8") if self.log_path else None

    def emit(self, line: SquawkLine, *, note: str = "") -> None:
        self.lines.append(line)
        self.counts[line.priority.name] = self.counts.get(line.priority.name, 0) + 1

        text = line.render()
        if note:
            text = f"{text}  [{note}]"
        if self.colour:
            text = f"{STYLES.get(line.priority, '')}{text}{RESET}"
        print(text, file=self.stream, flush=True)

        if self._log:
            self._log.write(json.dumps({
                "ts": line.ts, "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime(line.ts)),
                "priority": line.priority.name, "region": line.region,
                "org": line.org, "speaker": line.speaker, "body": line.body,
                "symbols": list(line.symbols), "source": line.source,
                "url": line.url, "note": note,
            }) + "\n")
            self._log.flush()

    def banner(self, text: str) -> None:
        print(f"\033[1;96m{text}{RESET}" if self.colour else text,
              file=self.stream, flush=True)

    def close(self) -> None:
        if self._log:
            self._log.close()
            self._log = None
