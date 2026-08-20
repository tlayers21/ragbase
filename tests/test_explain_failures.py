"""A failing map batch must not drop the explain stream on the floor.

`/query/explain` summarizes an oversized source in batches inside an already-started
StreamingResponse. An exception raised there aborts the SSE connection with no [DONE]
and no error frame, which a browser cannot tell apart from a hung request - and the
map step is exactly where a slow local model times out.
"""

import asyncio

import pytest


class _FakeRequest:
    """Stands in for starlette's Request; only is_disconnected() is consulted."""

    def __init__(self, disconnected=False):
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


@pytest.fixture
def explain_stream(monkeypatch):
    """Drive query_explain's event stream over a fake oversized source."""
    import api.query as query
    from config.settings import EXPLAIN_MAX_CHUNKS

    chunks = [(f"chunk {i}", {"chunk_index": i}) for i in range(EXPLAIN_MAX_CHUNKS + 12)]
    monkeypatch.setattr(query, "get_source_chunks", lambda *a, **k: chunks)

    async def _ok(source):
        return None

    monkeypatch.setattr(query, "require_finished", _ok)
    monkeypatch.setattr(query, "send_telemetry", lambda *a, **k: None)
    # No job in flight unless a test says otherwise.
    monkeypatch.setattr(query, "find_active_job", lambda *a, **k: None)

    async def _run(request=None):
        response = await query.query_explain(
            query.ExplainRequest(source="s1"), request or _FakeRequest()
        )
        return [frame async for frame in response.body_iterator]

    return _run


def test_a_failing_batch_still_closes_the_stream(monkeypatch, explain_stream):
    import api.query as query

    def boom(*a, **k):
        raise TimeoutError("ollama went away")

    monkeypatch.setattr(query, "_summarize_batch", boom)
    frames = asyncio.run(explain_stream())

    assert any(f == "data: [DONE]\n\n" for f in frames), "stream must terminate with [DONE]"
    assert any("[TIMING]" in f for f in frames), "the timing frame must still be sent"
    assert any("ollama went away" in f for f in frames), "the reason must reach the client"


def test_a_healthy_source_still_streams(monkeypatch, explain_stream):
    import api.query as query

    monkeypatch.setattr(query, "_summarize_batch", lambda *a, **k: "a summary")

    async def _tokens(prompt, system=None):
        for t in ("hello", " world"):
            yield t

    monkeypatch.setattr(query, "_aiter_answer", _tokens)
    frames = asyncio.run(explain_stream())

    assert any(f == "data: [DONE]\n\n" for f in frames)
    assert any("[SOURCES]" in f for f in frames)


def test_a_source_that_goes_in_flight_mid_run_stops_the_explanation(monkeypatch, explain_stream):
    """The pre-stream check is minutes stale on a source this size."""
    import api.query as query

    monkeypatch.setattr(query, "_summarize_batch", lambda *a, **k: "a summary")
    monkeypatch.setattr(
        query, "find_active_job", lambda *a, **k: {"id": "j1", "status": "ingesting"}
    )
    frames = asyncio.run(explain_stream())

    assert any("changed while it was being explained" in f for f in frames)
    assert any(f == "data: [DONE]\n\n" for f in frames), "stream must still terminate cleanly"
    assert not any("[SOURCES]" in f for f in frames), "a stopped run must not cite the source"


def test_a_disconnected_client_abandons_the_run(monkeypatch, explain_stream):
    import api.query as query

    calls = []

    def counting(*a, **k):
        calls.append(1)
        return "a summary"

    monkeypatch.setattr(query, "_summarize_batch", counting)
    frames = asyncio.run(explain_stream(_FakeRequest(disconnected=True)))

    assert not calls, "no batch should be summarized for a client that has gone"
    assert not any(f == "data: [DONE]\n\n" for f in frames)


def test_heartbeats_continue_while_a_slow_batch_runs(monkeypatch, explain_stream):
    """One heartbeat per batch leaves multi-minute silences on a large source."""
    import time as _time

    import api.query as query
    from config import settings

    monkeypatch.setattr(settings, "EXPLAIN_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(query, "EXPLAIN_HEARTBEAT_SECONDS", 0.01)

    def slow(*a, **k):
        _time.sleep(0.08)
        return "a summary"

    monkeypatch.setattr(query, "_summarize_batch", slow)

    async def _tokens(prompt, system=None):
        yield "done"

    monkeypatch.setattr(query, "_aiter_answer", _tokens)
    frames = asyncio.run(explain_stream())

    beats = [f for f in frames if f == "data: [HEARTBEAT]\n\n"]
    assert len(beats) > 3, f"expected repeated beats during the batches, got {len(beats)}"
