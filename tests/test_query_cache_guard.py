"""_fresh_cached_response: which cached entries are safe to serve.

Two independent reasons to reject an entry - it names a source that is mid-ingest, or
it has no context at all. The second is the empty-retrieval guard: caching a miss makes
every semantically similar question miss for CACHE_TTL, without ever re-running the
pipeline, so it cannot recover even once the document it needed finishes ingesting.
"""

import pytest

# api.query pulls DSPy, transformers and chromadb, so import it once at module scope
# rather than per test.
import api.query as query


@pytest.fixture
def cached(monkeypatch):
    """Feed a chosen entry to _fresh_cached_response and stub the in-flight check."""

    def _setup(entry, in_flight=frozenset()):
        monkeypatch.setattr(query, "get_cached_response", lambda user_id, emb: entry)
        monkeypatch.setattr(query, "active_sources", lambda user_id: set(in_flight))

    return _setup


def test_serves_a_complete_entry(cached):
    entry = {"context": "ctx", "sources": ["notes"], "scores": [1.0], "chunks": [{"text": "a"}]}
    cached(entry)
    assert query._fresh_cached_response([0.1]) == entry


def test_rejects_an_empty_context(cached):
    """A retrieval that found nothing is a cached failure, not a cached answer."""
    cached({"context": "", "sources": [], "scores": [], "chunks": []})
    assert query._fresh_cached_response([0.1]) is None


def test_rejects_a_missing_context_key(cached):
    cached({"sources": [], "scores": []})
    assert query._fresh_cached_response([0.1]) is None


def test_serves_a_legacy_entry_that_has_context_but_no_chunks(cached):
    """The guard is keyed on `context`, never on `chunks`.

    Entries written before chunks were stored have no `chunks` key but a perfectly
    good context. Rewriting this guard as `if not cached.get("chunks")` would silently
    throw away every one of them - this is the test that catches that "simplification".
    """
    entry = {"context": "real context", "sources": ["notes"], "scores": [1.0]}
    cached(entry)
    assert query._fresh_cached_response([0.1]) == entry


def test_rejects_an_entry_whose_source_is_mid_ingest(cached):
    """A cache hit skips search_candidates(), which is where the exclusion lives."""
    cached(
        {"context": "ctx", "sources": ["being_reingested"], "scores": [1.0]},
        in_flight={"being_reingested"},
    )
    assert query._fresh_cached_response([0.1]) is None


def test_serves_when_an_unrelated_source_is_mid_ingest(cached):
    entry = {"context": "ctx", "sources": ["notes"], "scores": [1.0]}
    cached(entry, in_flight={"something_else"})
    assert query._fresh_cached_response([0.1]) == entry


def test_miss_returns_none(cached):
    cached(None)
    assert query._fresh_cached_response([0.1]) is None
