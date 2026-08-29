"""Spoken squawk.

Uses whatever text-to-speech the host already has - `say` on macOS,
`espeak-ng`/`espeak`/`spd-say` on Linux, SAPI via PowerShell on Windows. If
none is present the speaker is a no-op and the tape still prints; audio is a
convenience, never a dependency.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass, field

from ..models import Priority


@dataclass(frozen=True)
class Backend:
    name: str
    argv: tuple[str, ...]        # {rate} and {text} are substituted
    rate_scale: int = 1


BACKENDS: tuple[Backend, ...] = (
    Backend("say", ("say", "-r", "{rate}", "{text}")),
    Backend("espeak-ng", ("espeak-ng", "-s", "{rate}", "{text}")),
    Backend("espeak", ("espeak", "-s", "{rate}", "{text}")),
    Backend("spd-say", ("spd-say", "-w", "-r", "0", "{text}")),
    Backend("powershell", ("powershell", "-NoProfile", "-Command",
                           "Add-Type -AssemblyName System.Speech; "
                           "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                           ".Speak('{text}')")),
)


def detect_backend() -> Backend | None:
    for backend in BACKENDS:
        if shutil.which(backend.argv[0]):
            return backend
    return None


@dataclass(order=True)
class _Job:
    # Negated priority first so the queue pops the most urgent line next.
    rank: int
    seq: int
    text: str = field(compare=False)
    priority: Priority = field(compare=False, default=Priority.NORMAL)


class Speaker:
    """Priority queue in front of the TTS binary.

    Two behaviours that matter on a live tape: urgent lines jump the queue,
    and a CRITICAL line cuts off whatever is currently being read. A squawk
    that makes you wait forty seconds for the important one is worse than
    silence.
    """

    def __init__(self, *, enabled: bool = True, rate: int = 190,
                 backend: Backend | None = None,
                 min_priority: Priority = Priority.IMPORTANT):
        self.backend = backend or detect_backend()
        self.enabled = enabled and self.backend is not None
        self.rate = rate
        self.min_priority = min_priority
        self.spoken_count = 0
        self.skipped_count = 0
        self._queue: queue.PriorityQueue[_Job | None] = queue.PriorityQueue()
        self._seq = 0
        self._proc: subprocess.Popen | None = None
        self._current: Priority = Priority.DROP
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="squawk-speaker")
            self._thread.start()

    @property
    def backend_name(self) -> str:
        return self.backend.name if self.backend else "none"

    def say(self, text: str, priority: Priority = Priority.NORMAL) -> bool:
        if not self.enabled or priority < self.min_priority or not text.strip():
            self.skipped_count += 1
            return False
        with self._lock:
            self._seq += 1
            job = _Job(rank=-int(priority), seq=self._seq, text=text, priority=priority)
            # Preempt: a CRITICAL headline should not wait behind a routine one.
            if priority >= Priority.CRITICAL and self._proc is not None \
                    and self._current < Priority.CRITICAL:
                self._kill()
        self._queue.put(job)
        return True

    def _kill(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _argv(self, text: str) -> list[str]:
        assert self.backend is not None
        safe = text.replace("'", " ").replace('"', " ")
        return [part.format(rate=self.rate, text=safe) for part in self.backend.argv]

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                with self._lock:
                    self._current = job.priority
                    self._proc = subprocess.Popen(
                        self._argv(job.text),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._proc.wait()
                self.spoken_count += 1
            except (OSError, ValueError):
                self.enabled = False
                return
            finally:
                with self._lock:
                    self._proc = None
                    self._current = Priority.DROP

    def stop(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._kill()
        self._queue.put(None)
