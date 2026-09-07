"""The analysis run slot, and cancellation actually stopping the chunk loops.

Both regressions here are silent. A broken busy gate lets two checks drive the one
Ollama process at once, which does not fail - it just makes every query and both
checks several times slower, with nothing in the logs saying why. And a cancel the
loops never read leaves the user watching a stopped progress bar while the backend
keeps making model calls for another ten minutes.

`finish()`'s identity check is the third: without it a slow teardown clears the slot
out from under the run that replaced it, and the *next* start succeeds when it should
have been refused.
"""

import pytest

import analysis.contradiction as contradiction
import analysis.fact_check as fact_check
import analysis.progress as progress

USER = "u1"


@pytest.fixture(autouse=True)
def clean_slot(monkeypatch):
    """The run slot is module state, so it leaks between tests without this."""
    monkeypatch.setattr(progress, "_run", None)


# -- The slot ------------------------------------------------------------------


def test_a_second_run_is_refused_while_one_holds_the_slot():
    progress.start("a.pdf", "facts")
    with pytest.raises(progress.AnalysisBusy) as excinfo:
        progress.start("b.pdf", "contradictions")
    # The message has to name the holder - "a check is running" is not actionable
    assert "a.pdf" in str(excinfo.value)
    assert excinfo.value.run.kind == "facts"


def test_the_slot_is_free_again_after_finish():
    run = progress.start("a.pdf", "facts")
    progress.finish(run)
    assert progress.current() is None
    progress.start("b.pdf", "facts")


def test_run_for_releases_the_slot_even_on_an_exception():
    with pytest.raises(RuntimeError):
        with progress.run_for("a.pdf", "facts"):
            raise RuntimeError("the check blew up")
    assert progress.current() is None


def test_finishing_a_stale_run_does_not_free_the_successors_slot():
    stale = progress.start("a.pdf", "facts")
    progress.finish(stale)
    live = progress.start("b.pdf", "facts")

    progress.finish(stale)

    assert progress.current() is live


# -- Cancellation --------------------------------------------------------------


def test_cancel_only_matches_the_named_source():
    run = progress.start("a.pdf", "facts")
    # A stale tab cancelling 'b.pdf' must not stop the run over 'a.pdf'
    assert progress.cancel("b.pdf") is False
    assert run.cancelled is False
    assert progress.cancel("a.pdf") is True
    assert run.cancelled is True


def test_cancel_with_nothing_running_reports_no_match():
    assert progress.cancel("a.pdf") is False


# -- The fact-check loop -------------------------------------------------------


def _seed_chunks(monkeypatch, module, count):
    chunks = [(f"chunk {i} text", {"chunk_index": i, "source": "a.pdf"}) for i in range(count)]
    monkeypatch.setattr(module, "get_source_chunks", lambda source, user_id: chunks)
    writes = []
    monkeypatch.setattr(
        module,
        "update_chunk_metadata",
        lambda source, idx, updates, user_id: writes.append((source, idx, updates)),
    )
    return chunks, writes


def test_a_cancelled_fact_check_stops_early_and_keeps_what_it_wrote(monkeypatch):
    _, writes = _seed_chunks(monkeypatch, fact_check, 5)
    run = progress.start("a.pdf", "facts")

    calls = []

    def fake_check(text):
        calls.append(text)
        # Cancelled while chunk 2 is in flight: the loop reads it before chunk 3
        if len(calls) == 2:
            run.request_cancel()
        return False, "No issues found."

    monkeypatch.setattr(fact_check, "check_chunk_facts", fake_check)

    output = fact_check.check_source_facts("a.pdf", USER, run)

    assert len(calls) == 2
    assert len(output) == 2
    # Partial results are real results - the two it graded stay written
    assert len(writes) == 2


def test_a_fact_check_with_no_run_is_unaffected(monkeypatch):
    """The `run` argument is optional so scripts and tests keep the old call."""
    _seed_chunks(monkeypatch, fact_check, 3)
    monkeypatch.setattr(fact_check, "check_chunk_facts", lambda text: (True, "wrong"))

    output = fact_check.check_source_facts("a.pdf", USER)

    assert len(output) == 3
    assert all(r["flagged"] for r in output)


def test_the_fact_check_publishes_chunk_progress(monkeypatch):
    _seed_chunks(monkeypatch, fact_check, 4)
    run = progress.start("a.pdf", "facts")
    seen = []

    def fake_check(text):
        seen.append((run.current, run.total, run.found))
        return True, "wrong"

    monkeypatch.setattr(fact_check, "check_chunk_facts", fake_check)
    fact_check.check_source_facts("a.pdf", USER, run)

    # current is 1-based and names the chunk being worked on; found trails it by one,
    # because the chunk in flight has not been graded yet
    assert seen == [(1, 4, 0), (2, 4, 1), (3, 4, 2), (4, 4, 3)]
    assert (run.current, run.found) == (4, 4)


# -- The contradiction loop ----------------------------------------------------


def _seed_contradiction(monkeypatch, count, neighbours):
    chunks, writes = _seed_chunks(monkeypatch, contradiction, count)

    class FakeCollection:
        def query(self, **kwargs):
            return {
                "documents": [[doc for doc, _ in neighbours]],
                "metadatas": [[meta for _, meta in neighbours]],
            }

    monkeypatch.setattr(contradiction, "get_collection", lambda user_id: FakeCollection())
    monkeypatch.setattr(contradiction, "embed", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(contradiction, "active_sources", lambda user_id: set())
    monkeypatch.setattr(contradiction, "_build_filter", lambda user_id, excluded=None: {})
    return chunks, writes


def test_a_cancelled_contradiction_check_stops_inside_a_chunk(monkeypatch):
    """One chunk is up to five model calls, so the inner loop has to read the flag too."""
    neighbours = [(f"other {i}", {"source": "b.pdf", "chunk_index": i}) for i in range(5)]
    _seed_contradiction(monkeypatch, count=3, neighbours=neighbours)
    run = progress.start("a.pdf", "contradictions")

    calls = []

    def fake_compare(a, b):
        calls.append((a, b))
        if len(calls) == 2:
            run.request_cancel()
        return False, "No contradiction found."

    monkeypatch.setattr(contradiction, "_check_contradiction", fake_compare)

    contradiction.find_contradictions("a.pdf", USER, run)

    # Without the inner check this runs all five comparisons of chunk 1 first
    assert len(calls) == 2


def test_a_contradiction_check_skips_its_own_source(monkeypatch):
    neighbours = [
        ("own chunk", {"source": "a.pdf", "chunk_index": 0}),
        ("other doc", {"source": "b.pdf", "chunk_index": 7}),
    ]
    _, writes = _seed_contradiction(monkeypatch, count=1, neighbours=neighbours)
    run = progress.start("a.pdf", "contradictions")

    compared = []

    def fake_compare(a, b):
        compared.append(b)
        return True, "they disagree"

    monkeypatch.setattr(contradiction, "_check_contradiction", fake_compare)

    count = contradiction.find_contradictions("a.pdf", USER, run)

    assert compared == ["other doc"]
    assert count == 1
    # Both sides are flagged, so each source's detail view shows the conflict
    assert {source for source, _, _ in writes} == {"a.pdf", "b.pdf"}
