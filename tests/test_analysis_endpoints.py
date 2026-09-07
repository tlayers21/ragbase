"""The two analysis endpoints: the run slot they claim, and what they report.

These cover the wiring rather than the checks themselves - that the endpoint hands the
*registered* run to the analysis function (so the status endpoint and the chunk loop are
talking about the same object), that an unfinished source is still refused, and that the
slot is released whether the check returns or raises.

The last one is the quiet one: a slot leaked by an exception makes every later check
answer 409 until the backend is restarted, with nothing in the logs to explain it.
"""

import asyncio

import pytest
from fastapi import HTTPException

import analysis.progress as progress
import api.documents as documents

USER = "u1"


@pytest.fixture(autouse=True)
def clean_slot(monkeypatch):
    monkeypatch.setattr(progress, "_run", None)


@pytest.fixture(autouse=True)
def no_ingestion_guard(monkeypatch):
    """The default: nothing is ingesting, so the guard passes."""

    async def passes(source):
        return None

    monkeypatch.setattr(documents, "require_finished", passes)


def _fake_facts(monkeypatch, captured=None, flagged=0, checked=3, cancel=False):
    def fake(source, user_id, run=None):
        if captured is not None:
            captured["run"] = run
            captured["registry"] = progress.current()
        run.begin(checked)
        if cancel:
            run.request_cancel()
        return [{"chunk_index": i, "flagged": i < flagged, "reason": ""} for i in range(checked)]

    monkeypatch.setattr(documents, "check_source_facts", fake)


# -- What the endpoints report -------------------------------------------------


def test_a_finished_fact_check_reports_its_totals(monkeypatch):
    _fake_facts(monkeypatch, flagged=2, checked=5)
    body = asyncio.run(documents.check_facts("a.pdf"))
    assert body == {
        "status": "ok",
        "flagged": 2,
        "checked": 5,
        "total": 5,
        "cancelled": False,
    }


def test_a_cancelled_fact_check_says_so(monkeypatch):
    # `checked` below `total` is the whole signal that the rest went ungraded
    def fake(source, user_id, run=None):
        run.begin(10)
        run.request_cancel()
        return [{"chunk_index": 0, "flagged": True, "reason": ""}]

    monkeypatch.setattr(documents, "check_source_facts", fake)

    body = asyncio.run(documents.check_facts("a.pdf"))
    assert body["status"] == "cancelled"
    assert body["cancelled"] is True
    assert (body["checked"], body["total"]) == (1, 10)


def test_a_contradiction_check_reports_its_own_count(monkeypatch):
    def fake(source, user_id, run=None):
        run.begin(4)
        run.advance(4, 3)
        return 3

    monkeypatch.setattr(documents, "find_contradictions", fake)

    body = asyncio.run(documents.check_contradictions("a.pdf"))
    assert body["contradictions_found"] == 3
    assert (body["checked"], body["total"]) == (4, 4)


# -- The slot ------------------------------------------------------------------


def test_the_endpoint_hands_the_registered_run_to_the_check(monkeypatch):
    """The status endpoint and the chunk loop must be reading one object."""
    captured = {}
    _fake_facts(monkeypatch, captured=captured)

    asyncio.run(documents.check_facts("a.pdf"))

    assert captured["run"] is not None
    assert captured["run"] is captured["registry"]
    assert (captured["run"].source, captured["run"].kind) == ("a.pdf", "facts")


def test_the_slot_is_released_when_the_check_returns(monkeypatch):
    _fake_facts(monkeypatch)
    asyncio.run(documents.check_facts("a.pdf"))
    assert progress.current() is None


def test_the_slot_is_released_when_the_check_raises(monkeypatch):
    def explodes(source, user_id, run=None):
        raise RuntimeError("ollama went away")

    monkeypatch.setattr(documents, "check_source_facts", explodes)

    with pytest.raises(RuntimeError):
        asyncio.run(documents.check_facts("a.pdf"))
    assert progress.current() is None


def test_a_second_check_is_refused_with_409_naming_the_holder(monkeypatch):
    _fake_facts(monkeypatch)
    progress.start("busy.pdf", "contradictions")

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(documents.check_facts("a.pdf"))

    assert excinfo.value.status_code == 409
    # The detail is the only thing separating this 409 from the ingestion one
    assert "busy.pdf" in excinfo.value.detail


def test_an_unfinished_source_is_never_graded(monkeypatch):
    """Grading mid-extraction writes flags onto chunks the job may still delete.

    Both refusals are 409, so the detail is the only thing telling the user whether
    to wait for an ingest or for another check - and it has to survive the check
    never being reached at all.
    """
    graded = []

    async def still_ingesting(source):
        raise HTTPException(status_code=409, detail=f"Source '{source}' is still being ingested")

    monkeypatch.setattr(documents, "require_finished", still_ingesting)
    _fake_facts(monkeypatch, captured={"run": None, "registry": None})
    monkeypatch.setattr(documents, "check_source_facts", lambda *a, **k: graded.append(a) or [])

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(documents.check_facts("a.pdf"))

    assert excinfo.value.status_code == 409
    assert "ingested" in excinfo.value.detail
    assert graded == []
    # And the refusal leaves the slot free, so a real check is not locked out by it
    assert progress.current() is None


# -- Status and cancel ---------------------------------------------------------


def test_the_status_endpoint_is_null_when_nothing_runs():
    assert asyncio.run(documents.analysis_status()).run is None


def test_the_status_endpoint_reports_the_live_run():
    run = progress.start("a.pdf", "contradictions")
    run.begin(88)
    run.advance(12, 2)

    status = asyncio.run(documents.analysis_status())

    assert status.run is not None
    assert (status.run.source, status.run.kind) == ("a.pdf", "contradictions")
    assert (status.run.current, status.run.total, status.run.found) == (12, 88, 2)


def test_cancel_only_stops_the_run_over_the_named_source():
    run = progress.start("a.pdf", "facts")

    # A stale tab asking for a source that is not the one running gets a 404,
    # rather than stopping whatever happens to hold the slot
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(documents.cancel_analysis("b.pdf"))
    assert excinfo.value.status_code == 404
    assert run.cancelled is False

    assert asyncio.run(documents.cancel_analysis("a.pdf"))["status"] == "cancelling"
    assert run.cancelled is True


def test_cancelling_with_nothing_running_is_a_404():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(documents.cancel_analysis("a.pdf"))
    assert excinfo.value.status_code == 404
