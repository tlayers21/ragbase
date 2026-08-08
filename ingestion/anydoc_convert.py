import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from config.logging import setup_logging
from config.settings import PDF_ANYDOC_TIMEOUT_SECONDS

logger = setup_logging(__name__)

_WORKER = Path(__file__).parent / "_anydoc_worker.py"

# Outcomes the caller can act on. Anything else means "anydoc could not do it" and
# the caller should fall back (Docling for PDFs) or fail the job.
STATUS_OK = "ok"
STATUS_OCR_REQUIRED = "ocr_required"


@dataclass
class AnydocResult:
    """Outcome of one conversion attempt. `markdown` is set only when ok."""

    status: str
    markdown: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def needs_ocr(self) -> bool:
        return self.status == STATUS_OCR_REQUIRED


def to_markdown(source_path: str | Path, source_name: str) -> AnydocResult:
    """
    Convert a document to Markdown with anydoc, in a child process.

    The isolation is not paranoia. anydoc buffers the whole document in memory
    while converting; a 381MB image-heavy PDF in the training corpus reached
    13.5GB RSS and was SIGKILLed by the OS. In-process that kills the FastAPI
    server and the ingestion worker along with it. In a child process it is just
    a non-zero return code, and the caller falls back.

    Never raises — every failure comes back as a non-ok status so ingestion can
    degrade rather than crash.
    """
    source_path = Path(source_path)
    out_fd, out_path = tempfile.mkstemp(suffix=".md")
    os.close(out_fd)

    try:
        proc = subprocess.run(
            [sys.executable, str(_WORKER), str(source_path), out_path],
            capture_output=True,
            text=True,
            timeout=PDF_ANYDOC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        os.unlink(out_path)
        logger.warning(f"anydoc timed out after {PDF_ANYDOC_TIMEOUT_SECONDS}s on '{source_name}'")
        return AnydocResult(status="timeout", detail="conversion exceeded the time limit")

    try:
        if proc.returncode != 0:
            # Negative return codes are signals — SIGKILL (-9) is the OOM killer.
            logger.warning(
                f"anydoc worker exited with {proc.returncode} on '{source_name}': "
                f"{proc.stderr.strip()[-500:]}"
            )
            return AnydocResult(status="crashed", detail=f"worker exited {proc.returncode}")

        try:
            verdict = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"anydoc worker returned unreadable output for '{source_name}': {e}")
            return AnydocResult(status="crashed", detail="unreadable worker output")

        status = verdict.get("status", "error")
        if status != STATUS_OK:
            logger.info(
                f"anydoc could not convert '{source_name}' ({status}): {verdict.get('detail', '')}"
            )
            return AnydocResult(status=status, detail=verdict.get("detail", ""))

        with open(out_path, "r", encoding="utf-8") as f:
            markdown = f.read()

        logger.info(f"anydoc converted '{source_name}' to {len(markdown)} chars of Markdown")
        return AnydocResult(status=STATUS_OK, markdown=markdown)

    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
