"""Shared fixtures.

Every fixture here exists to keep tests off the real `data/` directory. Modules bind
their path constants at import time, so patching `config.paths` has no effect - each
fixture patches the name as bound in the module under test. See .ai/skills/testing.md.
"""

import pytest


@pytest.fixture
def tmp_queue_status(tmp_path, monkeypatch):
    """Point ingestion.queue at a throwaway status file and reset its module state."""
    import ingestion.queue as q

    path = tmp_path / "queue_status.json"
    monkeypatch.setattr(q, "QUEUE_STATUS_PATH", path)
    # _current_job_id is module state, not file state, so it survives between tests
    # and would otherwise leak "the worker is running job X" into an unrelated case.
    monkeypatch.setattr(q, "_current_job_id", None)
    return path


@pytest.fixture
def write_jobs(tmp_queue_status):
    """Seed the queue status file. Returns the writer so a test can re-seed."""
    import json

    def _write(jobs):
        tmp_queue_status.write_text(json.dumps(jobs))
        return jobs

    return _write


@pytest.fixture
def tmp_cache_db(tmp_path, monkeypatch):
    """Point utils.cache at a throwaway SQLite file."""
    import utils.cache as cache

    path = tmp_path / "cache.db"
    monkeypatch.setattr(cache, "CACHE_DB_PATH", path)
    return path


class FakeCollection:
    """Stands in for a ChromaDB collection. Records adds; reports pre-existing ids."""

    def __init__(self, existing_ids=None):
        self.existing_ids = list(existing_ids or [])
        self.added = []

    def add(self, embeddings, documents, metadatas, ids):
        self.added.append({"documents": list(documents), "metadatas": list(metadatas)})

    def get(self, where=None, limit=None, include=None):
        return {"ids": self.existing_ids}

    @property
    def stored_documents(self):
        return [d for entry in self.added for d in entry["documents"]]


@pytest.fixture
def fake_ingestor(monkeypatch):
    """A BaseIngestor whose every collaborator is recorded instead of executed.

    Returns a factory: `make(existing_ids=[...])` -> (ingestor, calls, collection).
    `calls` is an ordered list of collaborator names, which is what the ordering
    tests assert on - embed before delete before store is the whole point of the
    embed_chunks()/store() split.
    """
    import ingestion.base as base

    def make(
        existing_ids=None,
        text="chunk one text",
        embed_error=None,
        summary_error=None,
        cancelled=False,
    ):
        calls = []
        collection = FakeCollection(existing_ids)
        summary_collection = FakeCollection()

        # Without this the ingestor consults the real queue status file, finds no record
        # for its job id, and correctly treats that as cancelled - aborting every test
        # before it reaches the code under test. See test_missing_record_counts_as_cancelled.
        monkeypatch.setattr(base, "is_cancelled", lambda job_id: cancelled)

        monkeypatch.setattr(base, "get_collection", lambda user_id: collection)
        monkeypatch.setattr(base, "get_summary_collection", lambda user_id: summary_collection)

        def fake_embed_batch(batch):
            calls.append("embed_batch")
            if embed_error:
                raise embed_error
            return [[0.1, 0.2, 0.3] for _ in batch]

        def fake_delete_source(source, user_id, remove_file=True):
            calls.append("delete_source")

        def fake_generate_stream(prompt, model=None, **kwargs):
            calls.append("generate_stream")
            if summary_error:
                raise summary_error
            return iter(["a summary"])

        monkeypatch.setattr(base, "embed_batch", fake_embed_batch)
        monkeypatch.setattr(base, "delete_source", fake_delete_source)
        monkeypatch.setattr(base, "generate_stream", fake_generate_stream)
        monkeypatch.setattr(base, "embed", lambda t: [0.1, 0.2, 0.3])
        monkeypatch.setattr(base, "clear_cache", lambda user_id: calls.append("clear_cache"))
        monkeypatch.setattr(base, "send_telemetry", lambda *a, **k: None)
        monkeypatch.setattr(base, "chunk_text", lambda t: [text])

        class Ingestor(base.BaseIngestor):
            def extract_text(self, source_path, source_name):
                calls.append("extract_text")
                return text

        ingestor = Ingestor(user_id="usr_test", job_id="job_test")

        # Patched on the instance, not the module: _build_graph opens the real graph DB
        # for its progress counts, and no ordering test cares what the graph does.
        def fake_build_graph(chunks, source):
            calls.append("_build_graph")

        monkeypatch.setattr(ingestor, "_build_graph", fake_build_graph)

        def fake_store_wrapper(chunks, source, metadata=None, embeddings=None):
            calls.append("store")
            return base.BaseIngestor.store(ingestor, chunks, source, metadata, embeddings)

        monkeypatch.setattr(ingestor, "store", fake_store_wrapper)

        cleanups = []
        monkeypatch.setattr(
            ingestor, "_cleanup_partial", lambda source, reason: cleanups.append(reason)
        )
        ingestor.cleanups = cleanups

        statuses = []
        monkeypatch.setattr(ingestor, "_update_job_status", lambda s: statuses.append(s))
        ingestor.statuses = statuses

        return ingestor, calls, collection

    return make
