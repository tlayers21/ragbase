"""The job status mutators and the duplicate-enqueue guard.

Three functions used to repeat the same lock-load-find-mutate-save loop and one guard was
copied verbatim into three enqueue paths. Both were consolidated, and neither had any
direct coverage before: the ingest-ordering tests assert on a stubbed `_update_job_status`,
so the real mutators were never exercised.
"""

import time

import ingestion.queue as q

USER = "u1"


def _job(job_id="j1", **extra):
    base = {"id": job_id, "source": "s1", "user_id": USER, "status": "queued"}
    base.update(extra)
    return base


# -- The mutators --------------------------------------------------------------
def test_status_update_sets_the_status(write_jobs):
    write_jobs([_job()])
    q._update_job("j1", "ingesting")
    assert q._load_status()[0]["status"] == "ingesting"


def test_a_terminal_status_stamps_finished_at(write_jobs):
    write_jobs([_job()])
    q._update_job("j1", "done")
    assert q._load_status()[0]["finished_at"] > 0


def test_a_non_terminal_status_clears_finished_at(write_jobs):
    write_jobs([_job(finished_at=time.time())])
    q._update_job("j1", "ingesting")
    assert "finished_at" not in q._load_status()[0]


def test_a_status_change_clears_stale_progress(write_jobs):
    """Counts belong to one phase - "page 4 of 4" must not survive into the graph build."""
    write_jobs([_job(progress={"current": 4, "total": 4, "unit": "page"})])
    q._update_job("j1", "building_graph")
    assert "progress" not in q._load_status()[0]


def test_estimate_update_only_touches_the_estimate(write_jobs):
    write_jobs([_job(status="ingesting")])
    q.update_job_estimate("j1", 120)
    row = q._load_status()[0]
    assert row["estimated_seconds"] == 120
    assert row["status"] == "ingesting"


def test_progress_update_records_all_three_fields(write_jobs):
    write_jobs([_job(status="ingesting")])
    q.update_job_progress("j1", 3, 10, "chunk")
    assert q._load_status()[0]["progress"] == {"current": 3, "total": 10, "unit": "chunk"}


def test_a_mutator_only_touches_its_own_job(write_jobs):
    write_jobs([_job("j1"), _job("j2", source="s2")])
    q.update_job_progress("j1", 1, 2)
    rows = {r["id"]: r for r in q._load_status()}
    assert "progress" in rows["j1"]
    assert "progress" not in rows["j2"]


def test_a_missing_job_does_not_rewrite_the_file(write_jobs, tmp_queue_status):
    """A row already swept must not cost a full file rewrite to change nothing."""
    write_jobs([_job()])
    before = tmp_queue_status.stat().st_mtime_ns
    q.update_job_progress("nonexistent", 1, 2)
    assert tmp_queue_status.stat().st_mtime_ns == before
    assert len(q._load_status()) == 1


# -- The duplicate-enqueue guard ----------------------------------------------
def test_enqueue_text_refuses_a_duplicate(write_jobs):
    write_jobs([_job(status="ingesting")])
    q._current_job_id = "j1"
    assert q.enqueue_text("some text", "s1", USER) == "j1"
    assert len(q._load_status()) == 1, "no second row may be created"


def test_enqueue_url_refuses_a_duplicate(write_jobs):
    write_jobs([_job(status="building_graph")])
    q._current_job_id = "j1"
    assert q.enqueue_url("https://example.com/v", "s1", USER) == "j1"
    assert len(q._load_status()) == 1


def test_enqueue_file_refuses_a_duplicate_and_leaks_no_temp_file(write_jobs, monkeypatch):
    """The guard must return before the temp copy is written, or the file is orphaned."""
    write_jobs([_job(status="ingesting")])
    q._current_job_id = "j1"
    made = []
    real = q.tempfile.NamedTemporaryFile

    def spy(*a, **k):
        made.append(1)
        return real(*a, **k)

    monkeypatch.setattr(q.tempfile, "NamedTemporaryFile", spy)
    assert q.enqueue(b"data", "f.txt", "s1", USER) == "j1"
    assert not made, "a rejected enqueue must not create a temp file"
    assert len(q._load_status()) == 1


def test_a_finished_job_does_not_block_a_re_ingest(write_jobs):
    write_jobs([_job(status="done", finished_at=time.time())])
    q._current_job_id = None
    new_id = q.enqueue_text("fresh text", "s1", USER)
    assert new_id != "j1"
    assert len(q._load_status()) == 2


def test_a_different_source_is_never_blocked(write_jobs):
    write_jobs([_job(status="ingesting")])
    q._current_job_id = "j1"
    new_id = q.enqueue_text("other", "s2", USER)
    assert new_id != "j1"
