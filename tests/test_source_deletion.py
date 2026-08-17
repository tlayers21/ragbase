"""What deleting a source has to clean up.

`delete_source` is the single teardown path - the DELETE endpoint, the re-ingest cleanup,
and every cancellation route through `_cleanup_partial` all land here. Anything it forgets
survives the source and leaks into the next ingestion of the same file.
"""

import json

import ingestion.helpers as helpers


class _Collection:
    """Minimal ChromaDB stand-in: reports ids, records deletes."""

    def __init__(self, ids=None):
        self.ids = list(ids or [])
        self.deleted = []

    def get(self, where=None, include=None):
        return {"ids": self.ids}

    def delete(self, ids):
        self.deleted.extend(ids)


def _patch_collaborators(monkeypatch, chunk_ids=("c0",)):
    """Neutralise everything delete_source touches except the filesystem."""
    collection = _Collection(chunk_ids)
    monkeypatch.setattr(helpers, "get_collection", lambda user_id: collection)
    monkeypatch.setattr(helpers, "get_summary_collection", lambda user_id: _Collection())
    monkeypatch.setattr(helpers, "delete_graph_source", lambda source, user_id: None)
    monkeypatch.setattr(helpers, "clear_cache", lambda user_id: None)
    return collection


def test_delete_source_removes_the_scanned_pdf_checkpoint(tmp_path, monkeypatch):
    """The page-resume checkpoint must not outlive the source.

    PdfIngestor writes data/{source}_progress.json after every page and unlinks it only
    on success, so a cancelled or failed run left it behind. Re-ingesting the same file
    then resumed from the stale page offset and skipped pages it never transcribed.
    """
    _patch_collaborators(monkeypatch)
    # Patched as bound in helpers, not on config.paths - see .ai/skills/testing.md.
    monkeypatch.setattr(helpers, "DATA_DIR", tmp_path)
    monkeypatch.setattr(helpers, "SOURCES_DIR", tmp_path / "sources")

    checkpoint = tmp_path / "lecture_notes_progress.json"
    checkpoint.write_text(json.dumps({"last_page": 12, "text": "partial"}))

    helpers.delete_source("lecture_notes", "usr_test")

    assert not checkpoint.exists()


def test_delete_source_tolerates_a_missing_checkpoint(tmp_path, monkeypatch):
    """The normal case: most sources never create one, and that is not an error."""
    _patch_collaborators(monkeypatch)
    monkeypatch.setattr(helpers, "DATA_DIR", tmp_path)
    monkeypatch.setattr(helpers, "SOURCES_DIR", tmp_path / "sources")

    assert helpers.delete_source("never_scanned", "usr_test") == 1


def test_delete_source_leaves_another_sources_checkpoint_alone(tmp_path, monkeypatch):
    """Slug matching must be exact - checkpoints are keyed by source name."""
    _patch_collaborators(monkeypatch)
    monkeypatch.setattr(helpers, "DATA_DIR", tmp_path)
    monkeypatch.setattr(helpers, "SOURCES_DIR", tmp_path / "sources")

    keep = tmp_path / "other_source_progress.json"
    keep.write_text("{}")

    helpers.delete_source("lecture_notes", "usr_test")

    assert keep.exists()
