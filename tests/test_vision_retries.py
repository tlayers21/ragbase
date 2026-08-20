"""The per-page transcription retry ladder.

A timed-out page is retried; any other error abandons the page after one attempt. That
asymmetry is load-bearing and easy to break silently, because the exception class that
signals a timeout depends on who bounds the call. `vision_with_timeout` used to raise a
builtin TimeoutError; the shared Ollama client's socket timeout raises
httpx.ReadTimeout, which is NOT a subclass of it. Getting this wrong turns three
attempts into one with nothing in the log to say so.
"""

import httpx
import pytest

import ingestion.pdf as pdf


@pytest.fixture
def ingestor(monkeypatch):
    """A PdfIngestor with no ChromaDB behind it."""
    inst = pdf.PdfIngestor.__new__(pdf.PdfIngestor)
    inst.job_id = None
    return inst


def _counting(exc, succeed_on=None):
    """A _transcribe_page stand-in that records attempts and raises `exc`."""
    calls = []

    def fake(image_path, page_num, *a, **k):
        calls.append(page_num)
        if succeed_on is not None and len(calls) >= succeed_on:
            return "transcribed"
        raise exc

    return fake, calls


def test_a_socket_timeout_is_retried(ingestor, monkeypatch):
    """httpx.ReadTimeout is what the shared client raises when a page stalls."""
    fake, calls = _counting(httpx.ReadTimeout("timed out"))
    monkeypatch.setattr(pdf.PdfIngestor, "_transcribe_page", staticmethod(fake))
    assert ingestor._transcribe_with_retries("/tmp/x.png", 1) is None
    assert len(calls) == pdf.MAX_TRANSCRIBE_RETRIES


def test_a_builtin_timeout_is_retried(ingestor, monkeypatch):
    fake, calls = _counting(TimeoutError("timed out"))
    monkeypatch.setattr(pdf.PdfIngestor, "_transcribe_page", staticmethod(fake))
    assert ingestor._transcribe_with_retries("/tmp/x.png", 1) is None
    assert len(calls) == pdf.MAX_TRANSCRIBE_RETRIES


def test_a_transient_stall_recovers_on_a_later_attempt(ingestor, monkeypatch):
    fake, calls = _counting(httpx.ReadTimeout("timed out"), succeed_on=2)
    monkeypatch.setattr(pdf.PdfIngestor, "_transcribe_page", staticmethod(fake))
    assert ingestor._transcribe_with_retries("/tmp/x.png", 1) == "transcribed"
    assert len(calls) == 2


def test_a_non_timeout_error_abandons_the_page_immediately(ingestor, monkeypatch):
    """One bad page must not cost three slow attempts - only a timeout is worth retrying."""
    fake, calls = _counting(ValueError("malformed image"))
    monkeypatch.setattr(pdf.PdfIngestor, "_transcribe_page", staticmethod(fake))
    assert ingestor._transcribe_with_retries("/tmp/x.png", 1) is None
    assert len(calls) == 1


def test_a_successful_page_makes_one_call(ingestor, monkeypatch):
    fake, calls = _counting(RuntimeError("unused"), succeed_on=1)
    monkeypatch.setattr(pdf.PdfIngestor, "_transcribe_page", staticmethod(fake))
    assert ingestor._transcribe_with_retries("/tmp/x.png", 1) == "transcribed"
    assert len(calls) == 1
