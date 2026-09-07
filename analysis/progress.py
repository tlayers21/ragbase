import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Literal

from config.logging import setup_logging

logger = setup_logging(__name__)

AnalysisKind = Literal["facts", "contradictions"]


class AnalysisBusy(Exception):
    """Raised by `start()` when another run already holds the slot.

    Carries the run that holds it so the caller can name it - "a check is
    running" is not actionable, "'notes.pdf' is being fact checked" is.
    """

    def __init__(self, run: "AnalysisRun"):
        self.run = run
        super().__init__(f"'{run.source}' is already running the {run.kind} check")


@dataclass
class AnalysisRun:
    """One in-flight check over one source.

    `current`/`total` count chunks of the source, not model calls: contradiction
    detection makes up to five calls per chunk, and a bar that jumped by five
    would be measuring the wrong thing. `found` is flagged chunks or detected
    contradictions, whichever check this is.
    """

    source: str
    kind: str
    total: int = 0
    current: int = 0
    found: int = 0
    started_at: float = field(default_factory=time.time)
    _cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        """Whether a cancel has been requested. Checked between model calls."""
        return self._cancel.is_set()

    def begin(self, total: int) -> None:
        """Publish the chunk count, once it is known."""
        self.total = total

    def advance(self, current: int, found: int) -> None:
        """Record that chunk `current` is now being worked on."""
        self.current = current
        self.found = found

    def request_cancel(self) -> None:
        self._cancel.set()

    def snapshot(self) -> dict:
        """A plain dict for the status endpoint, taken without the lock.

        Every field is a single int or str assignment, so a snapshot can be one
        chunk stale but never internally inconsistent.
        """
        return {
            "source": self.source,
            "kind": self.kind,
            "current": self.current,
            "total": self.total,
            "found": self.found,
            "cancelled": self.cancelled,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
        }


_lock = threading.Lock()
_run: AnalysisRun | None = None


def start(source: str, kind: str) -> AnalysisRun:
    """Claim the single run slot for `source`, or raise `AnalysisBusy`."""
    global _run
    with _lock:
        if _run is not None:
            raise AnalysisBusy(_run)
        _run = AnalysisRun(source=source, kind=kind)
        logger.info(f"Analysis run started: {kind} on '{source}'")
        return _run


def finish(run: AnalysisRun) -> None:
    """Release the slot, but only if `run` still holds it.

    The identity check is not defensive noise: without it a slow teardown could
    clear the slot out from under the run that replaced it, and the next `start()`
    would then run two checks against one Ollama.
    """
    global _run
    with _lock:
        if _run is run:
            _run = None


@contextmanager
def run_for(source: str, kind: str) -> Iterator[AnalysisRun]:
    """`start()` + guaranteed `finish()`. Raises `AnalysisBusy` like `start()`."""
    run = start(source, kind)
    try:
        yield run
    finally:
        finish(run)


def current() -> AnalysisRun | None:
    """The run in flight, or None."""
    with _lock:
        return _run


def cancel(source: str) -> bool:
    """Ask the run over `source` to stop, returning whether one matched.

    Keyed by source rather than cancelling whatever is running: a stale tab can
    otherwise kill a run the user started afterwards on a different document.

    A model call already in flight is not interrupted, so the run stops within
    one chunk rather than instantly. Whatever it has already written to ChromaDB
    stays - partial results are real results, and re-running only overwrites them.
    """
    with _lock:
        if _run is None or _run.source != source:
            return False
        _run.request_cancel()
        logger.info(f"Analysis run cancelled: {_run.kind} on '{source}'")
        return True
