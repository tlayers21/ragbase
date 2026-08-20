"""The cancellation-defeat fixes.

Each of these guards a path where cancellation was accepted by the UI and then silently
undone, letting a cancelled job run to completion and publish a half-built source.
"""

import json
import time
from pathlib import Path

import ingestion.queue as q
from config.settings import QUEUE_TERMINAL_ROW_TTL_SECONDS


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
    # "b" carries a fresh finished_at so get_status()'s TTL sweep leaves it alone; this
    # test is about which statuses cancel_job will transition, not about expiry.
    write_jobs(
        [
            {"id": "a", "status": "ingesting"},
            {"id": "b", "status": "done", "finished_at": time.time()},
        ]
    )

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


def test_cancel_job_clears_stale_progress(tmp_queue_status, write_jobs):
    """Progress counts belong to the interrupted phase, so cancelling has to drop them.

    _update_job clears them on every status change for this reason; cancel_job writes the
    status directly and used to skip it, leaving "chunk 9 of 19" beside "Cancelled".
    """
    write_jobs(
        [
            {
                "id": "a",
                "status": "building_graph",
                "progress": {"current": 9, "total": 19, "unit": "chunk"},
            }
        ]
    )

    assert q.cancel_job("a") is True

    (job,) = q.get_status()
    assert job["status"] == "cancelled"
    assert "progress" not in job


def test_active_sources_holds_a_cancelled_source_the_worker_still_owns(
    tmp_queue_status, write_jobs, monkeypatch
):
    """A cancelled job mid-teardown must still read as in flight.

    DELETE /documents/{source} flips the status to "cancelled" before it deletes the
    data, so for the length of the teardown the chunks are still in ChromaDB. Reporting
    the source as finished in that window is what made GET /documents/ return a phantom
    entry with a real chunk_count, no preview and no stored file.
    """
    write_jobs([{"id": "1", "status": "cancelled", "source": "dying", "user_id": "u"}])

    monkeypatch.setattr(q, "_current_job_id", "1")
    assert q.active_sources("u") == {"dying"}

    # Once the worker releases the job its cleanup has finished and the data is gone,
    # so the source is free to disappear from the in-flight set.
    monkeypatch.setattr(q, "_current_job_id", None)
    assert q.active_sources("u") == set()


def test_get_status_expires_terminal_rows_past_the_ttl(tmp_queue_status, write_jobs):
    """Terminal rows self-clear, because nothing else reliably removes them.

    clear_completed() is only reachable from POST /ingest/clear_completed, which no
    client calls, and restart recovery rewrites active rows only - so without this
    sweep a cancelled job stayed pinned in the UI queue forever.
    """
    stale = time.time() - QUEUE_TERMINAL_ROW_TTL_SECONDS - 1
    write_jobs(
        [
            {"id": "old_cancel", "status": "cancelled", "finished_at": stale},
            {"id": "old_done", "status": "done", "finished_at": stale},
            {"id": "old_error", "status": "error: boom", "finished_at": stale},
            {"id": "recent", "status": "cancelled", "finished_at": time.time()},
            {"id": "active", "status": "building_graph"},
        ]
    )

    assert {j["id"] for j in q.get_status()} == {"recent", "active"}
    # The sweep is persisted, not just filtered on the way out.
    assert {j["id"] for j in json.loads(tmp_queue_status.read_text())} == {"recent", "active"}


def test_get_status_expires_rows_with_no_finished_at(tmp_queue_status, write_jobs):
    """A row predating finished_at counts as long expired.

    This is what clears a queue that is already stuck when the TTL first ships.
    """
    write_jobs([{"id": "legacy", "status": "cancelled"}, {"id": "live", "status": "queued"}])
    assert {j["id"] for j in q.get_status()} == {"live"}


def test_get_status_keeps_the_running_job_even_when_cancelled(
    tmp_queue_status, write_jobs, monkeypatch
):
    """Mirrors clear_completed()'s guard: cancellation is cooperative.

    A cancelled job polls its own record to learn it should stop, so expiring the record
    of a job that is still running would tell it to keep going.
    """
    write_jobs(
        [{"id": "running", "status": "cancelled", "finished_at": time.time() - 3600}],
    )
    monkeypatch.setattr(q, "_current_job_id", "running")
    assert [j["id"] for j in q.get_status()] == ["running"]


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
