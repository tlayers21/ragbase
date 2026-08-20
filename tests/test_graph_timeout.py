"""The graph build's failure handling.

The bug these guard: `generate_stream` had no timeout of any kind, so a wedged
Ollama parked the single ingestion worker inside one entity-extraction call
forever. Nothing could recover it - cancellation here is cooperative and is only
polled *between* chunks - so the job never ended and every source queued behind it
sat at "queued" indefinitely.

The transport timeout that fixes it lives in `utils/ollama_client.py`. What is
tested here is the half that timeout is not enough on its own to fix: 155 chunks
failing one at a time would still hold the worker for hours, so a run of failures
has to abort the build. The distinction between "the model is gone" and "this one
chunk produced junk" is the whole design, so both directions are asserted.
"""

import pytest

import retrieval.graph as graph
from config.settings import GRAPH_MAX_CONSECUTIVE_FAILURES


@pytest.fixture
def tmp_graph_db(tmp_path, monkeypatch):
    """Point retrieval.graph at a throwaway SQLite file.

    Patched on the module, not on config.paths: DB_PATH is bound at import time,
    so patching the source constant would leave the real graph in play. See
    .ai/skills/testing.md.
    """
    monkeypatch.setattr(graph, "DB_PATH", tmp_path / "graph.db")
    return tmp_path / "graph.db"


def test_transport_failures_abort_the_build(tmp_graph_db, monkeypatch):
    """A dead model fails the job instead of grinding through every chunk.

    Without the breaker this walks all 50 chunks, which at the real timeout is
    hours of a held queue rather than a job that ends and lets the next one start.
    """
    calls = []

    def dead_ollama(prompt, model=None):
        calls.append(prompt)
        raise TimeoutError("read timed out")

    monkeypatch.setattr(graph, "generate_stream", dead_ollama)

    with pytest.raises(graph.EntityExtractionUnavailable):
        graph.build_from_chunks(
            [f"chunk {i}" for i in range(50)], "src", "u1", should_stop=lambda: False
        )

    assert len(calls) == GRAPH_MAX_CONSECUTIVE_FAILURES


def test_unparseable_output_skips_only_that_chunk(tmp_graph_db, monkeypatch):
    """Junk from the model is a chunk problem, not a health problem.

    Every chunk here returns something that is not JSON. That must not trip the
    breaker: the model is answering, so the build finishes with an empty graph
    rather than failing the whole ingestion.
    """
    calls = []

    def junk_ollama(prompt, model=None):
        calls.append(prompt)
        return iter(["not json at all"])

    monkeypatch.setattr(graph, "generate_stream", junk_ollama)

    graph.build_from_chunks(
        [f"chunk {i}" for i in range(10)], "src", "u1", should_stop=lambda: False
    )

    assert len(calls) == 10


def test_recovered_call_resets_the_failure_run(tmp_graph_db, monkeypatch):
    """The breaker counts *consecutive* failures, not failures.

    A model that blips and comes back must not accumulate strikes across an
    otherwise healthy build - that would fail long documents at random.
    """
    calls = []

    def flaky_ollama(prompt, model=None):
        calls.append(prompt)
        # Fail every other call: never GRAPH_MAX_CONSECUTIVE_FAILURES in a row.
        if len(calls) % 2 == 1:
            raise TimeoutError("read timed out")
        return iter(['{"entities": ["thing"], "relationships": []}'])

    monkeypatch.setattr(graph, "generate_stream", flaky_ollama)

    graph.build_from_chunks(
        [f"chunk {i}" for i in range(12)], "src", "u1", should_stop=lambda: False
    )

    assert len(calls) == 12
