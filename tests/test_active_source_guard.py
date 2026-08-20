"""The in-flight guard and retrieval's exclusion must agree on one definition.

`active_sources()` counts a cancelled job the worker still owns as in flight, because
cancellation is cooperative and the chunks stay in ChromaDB for the length of the
teardown. `find_active_job()` did not, so during that window `require_finished` said
"finished" while retrieval said "in flight" - and /documents/{source},
/sources/{source}/file and /query/explain would all serve a source being deleted.
"""

import ingestion.queue as q

USER = "u1"


def _seed(write_jobs, status, owned):
    job = {"id": "j1", "source": "s1", "user_id": USER, "status": status}
    write_jobs([job])
    q._current_job_id = "j1" if owned else None
    return job


def test_an_active_job_is_found(write_jobs):
    _seed(write_jobs, "ingesting", owned=True)
    assert q.find_active_job("s1", USER) is not None


def test_a_cancelled_job_the_worker_still_owns_counts_as_in_flight(write_jobs):
    _seed(write_jobs, "cancelled", owned=True)
    assert q.find_active_job("s1", USER) is not None


def test_a_cancelled_job_the_worker_has_released_does_not(write_jobs):
    _seed(write_jobs, "cancelled", owned=False)
    assert q.find_active_job("s1", USER) is None


def test_a_finished_job_does_not(write_jobs):
    _seed(write_jobs, "done", owned=True)
    assert q.find_active_job("s1", USER) is None


def test_the_guard_and_retrieval_never_disagree(write_jobs):
    """The invariant that was broken: one source, two answers."""
    for status in ("queued", "ingesting", "building_graph", "cancelled", "done"):
        for owned in (True, False):
            _seed(write_jobs, status, owned)
            guard_says = q.find_active_job("s1", USER) is not None
            retrieval_says = "s1" in q.active_sources(USER)
            assert guard_says == retrieval_says, (
                f"status={status} owned={owned}: guard={guard_says} retrieval={retrieval_says}"
            )


def test_another_users_job_is_invisible(write_jobs):
    write_jobs([{"id": "j1", "source": "s1", "user_id": "someone_else", "status": "ingesting"}])
    q._current_job_id = "j1"
    assert q.find_active_job("s1", USER) is None
