"""The cancellation-defeat fixes.

Each of these guards a path where cancellation was accepted by the UI and then silently
undone, letting a cancelled job run to completion and publish a half-built source.
"""

from pathlib import Path

import ingestion.queue as q


def test_missing_record_counts_as_cancelled(tmp_queue_status, write_jobs):
    """The fix: no record means cancelled, not "keep going".

    clear_completed() used to be able to delete a cancelled-but-still-running job's
    record, and is_cancelled() returned False from then on - so the worker never saw
    the cancellation and finished the build.
    """
    write_jobs([{"id": "other", "status": "ingesting"}])
    assert q.is_cancelled("job_that_was_cleared") is True


def test_missing_status_file_counts_as_cancelled(tmp_queue_status):
    assert not tmp_queue_status.exists()
    assert q.is_cancelled("anything") is True


def test_cancelled_and_active_statuses(tmp_queue_status, write_jobs):
    write_jobs(
        [
            {"id": "a", "status": "cancelled"},
            {"id": "b", "status": "ingesting"},
            {"id": "c", "status": "building_graph"},
            {"id": "d", "status": "done"},
        ]
    )
    assert q.is_cancelled("a") is True
    assert q.is_cancelled("b") is False
    assert q.is_cancelled("c") is False
    assert q.is_cancelled("d") is False


def test_clear_completed_keeps_active_jobs(tmp_queue_status, write_jobs):
    write_jobs(
        [
            {"id": "done", "status": "done"},
            {"id": "cancelled", "status": "cancelled"},
            {"id": "errored", "status": "error: boom"},
            {"id": "queued", "status": "queued"},
            {"id": "ingesting", "status": "ingesting"},
            {"id": "graph", "status": "building_graph"},
        ]
    )
    q.clear_completed()
    remaining = {j["id"] for j in q.get_status()}
    assert remaining == {"queued", "ingesting", "graph"}


def test_clear_completed_keeps_the_running_job_even_when_cancelled(
    tmp_queue_status, write_jobs, monkeypatch
):
    """Cancellation is cooperative: a cancelled job keeps running until it notices.

    Deleting its record is what made is_cancelled() lose the cancellation, so the
    worker's current job survives clear_completed() regardless of status.
    """
    write_jobs([{"id": "running", "status": "cancelled"}, {"id": "old", "status": "cancelled"}])
    monkeypatch.setattr(q, "_current_job_id", "running")

    q.clear_completed()

    remaining = {j["id"] for j in q.get_status()}
    assert remaining == {"running"}
    assert q.is_cancelled("running") is True


def test_cancel_job_only_transitions_active_jobs(tmp_queue_status, write_jobs):
    write_jobs([{"id": "a", "status": "ingesting"}, {"id": "b", "status": "done"}])

    assert q.cancel_job("a") is True
    assert q.cancel_job("b") is False
    assert q.cancel_job("missing") is False

    by_id = {j["id"]: j["status"] for j in q.get_status()}
    assert by_id == {"a": "cancelled", "b": "done"}


def test_active_sources_excludes_finished(tmp_queue_status, write_jobs):
    write_jobs(
        [
            {"id": "1", "status": "ingesting", "source": "live", "user_id": "u"},
            {"id": "2", "status": "done", "source": "finished", "user_id": "u"},
            {"id": "3", "status": "queued", "source": "other_user", "user_id": "v"},
        ]
    )
    assert q.active_sources("u") == {"live"}


def test_status_script_does_not_clear_the_queue():
    """scripts/status.sh must stay read-only.

    It used to POST /ingest/clear_completed before printing, which deleted the record
    a cancelled-but-running job needed - a status check defeated a cancellation.
    """
    script = Path(__file__).resolve().parent.parent / "scripts" / "status.sh"
    # Comments are excluded on purpose: the file documents the removal by name, and
    # asserting on the raw text would fail on the explanation rather than a call.
    code = [line for line in script.read_text().splitlines() if not line.strip().startswith("#")]
    assert not any("clear_completed" in line for line in code)
