"""The data-loss paths in ingest().

Both are ordering and error-handling guarantees rather than outputs, so they are
asserted on the order collaborators were called in and on what cleanup ran.
"""

import pytest

from ingestion.base import IngestionCancelled


def test_reingest_embeds_before_deleting_the_old_copy(fake_ingestor):
    """The whole reason embed_chunks() is split out of store().

    delete_source() must not run until the new content has proven it embeds.
    """
    ingestor, calls, _ = fake_ingestor(existing_ids=["old-chunk-id"])

    ingestor.ingest("path.txt", "notes")

    assert calls.index("embed_batch") < calls.index("delete_source")
    assert calls.index("delete_source") < calls.index("store")


def test_embed_failure_leaves_the_existing_document_intact(fake_ingestor):
    """A transient Ollama fault must not destroy a working source.

    Deleting first meant one failed embed call wiped the document and stored nothing
    in its place.
    """
    ingestor, calls, _ = fake_ingestor(
        existing_ids=["old-chunk-id"], embed_error=RuntimeError("ollama down")
    )

    with pytest.raises(RuntimeError, match="ollama down"):
        ingestor.ingest("path.txt", "notes")

    assert "delete_source" not in calls
    assert "store" not in calls


def test_embed_failure_cleans_up_and_reraises(fake_ingestor):
    ingestor, _, _ = fake_ingestor(embed_error=RuntimeError("ollama down"))

    with pytest.raises(RuntimeError):
        ingestor.ingest("path.txt", "notes")

    assert ingestor.cleanups == ["failed"]


def test_summary_failure_is_caught_and_cleaned_up(fake_ingestor):
    """The window between store() and _build_graph() used to run unguarded.

    The summary call is a live Ollama request; a raise there left chunks in ChromaDB
    while the worker wrote a terminal error status, so the source immediately became
    queryable with no summary and no graph.
    """
    ingestor, calls, _ = fake_ingestor(summary_error=RuntimeError("summary boom"))

    with pytest.raises(RuntimeError, match="summary boom"):
        ingestor.ingest("path.txt", "notes")

    assert "store" in calls
    assert ingestor.cleanups == ["failed"]
    assert "_build_graph" not in calls


def test_cancellation_cleans_up_without_overwriting_the_status(fake_ingestor):
    """The cancel endpoint already wrote "cancelled" - ingest() must not clobber it."""
    ingestor, _, _ = fake_ingestor(embed_error=IngestionCancelled("cancelled"))

    assert ingestor.ingest("path.txt", "notes") == 0
    assert ingestor.cleanups == ["cancelled"]
    assert ingestor.statuses == []


def test_no_redundant_ingesting_status_write(fake_ingestor):
    """The worker already set "ingesting" before importing this ingestor's heavy deps.

    Repeating it after that multi-second gap overwrote any "cancelled" the user set in
    between: the cancel was accepted, hidden in the UI, and then silently undone.
    """
    ingestor, _, _ = fake_ingestor()

    ingestor.ingest("path.txt", "notes")

    assert "ingesting" not in ingestor.statuses


def test_new_source_skips_the_delete_path(fake_ingestor):
    """Nothing to remove, and calling it would exercise the graph DELETE for nothing."""
    ingestor, calls, _ = fake_ingestor(existing_ids=[])

    ingestor.ingest("path.txt", "notes")

    assert "delete_source" not in calls
    assert "store" in calls


def test_successful_ingest_stores_and_builds_the_graph(fake_ingestor):
    ingestor, calls, collection = fake_ingestor(text="the document body")

    stored = ingestor.ingest("path.txt", "notes")

    assert stored == 1
    assert collection.stored_documents == ["the document body"]
    assert calls.index("store") < calls.index("_build_graph")
    # Cached retrievals built without this source only go stale once it is visible.
    assert calls.index("_build_graph") < calls.index("clear_cache")


def test_empty_extraction_stops_before_storing(fake_ingestor):
    ingestor, calls, _ = fake_ingestor(text="")

    assert ingestor.ingest("path.txt", "notes") == 0
    assert "store" not in calls
    assert ingestor.statuses == ["error: no text extracted"]
