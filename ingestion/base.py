import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from config.logging import setup_logging
from config.models import get_model
from config.settings import EMBED_BATCH_SIZE, GRAPH_SECONDS_PER_CHUNK
from ingestion.queue import _update_job, is_cancelled, update_job_estimate, update_job_progress
from retrieval.embed import chunk_text, embed, embed_batch
from retrieval.graph import build_from_chunks, graph_connection
from utils.cache import clear_cache
from utils.chromadb_client import get_collection, get_summary_collection
from utils.ollama_client import generate_stream
from utils.telemetry import send_telemetry

from .helpers import delete_source

logger = setup_logging(__name__)


class IngestionCancelled(Exception):
    """Raised when a job's status is set to 'cancelled' mid-run so ingest() can
    stop cleanly instead of continuing to chunk/store/summarize."""


class BaseIngestor(ABC):
    """Base class for all ingestors, handling chunking, embedding, and storing.

    Subclasses only need to implement extract_text().
    """

    def __init__(self, user_id: str, job_id: str | None = None):
        self.user_id = user_id
        self.job_id = job_id
        self.collection = get_collection(user_id)
        self.summary_collection = get_summary_collection(user_id)

    # To be implemented by each subclass
    @abstractmethod
    def extract_text(self, source_path: str | Path, source_name: str) -> str:
        """Extract raw text from the source. Implemented by each subclass."""
        pass

    # -- Shared logic ----------------------------------------------------------
    def embed_chunks(self, chunks: list[str], source: str) -> list[list[float]]:
        """Embed every chunk up front, raising on the first failure.

        Separate from store() so a re-ingest proves the new content embeds before
        delete_source() removes the old.
        """
        embeddings: list[list[float]] = []
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            if self.job_id and is_cancelled(self.job_id):
                logger.info(f"Ingestion of '{source}' cancelled - stopping chunk processing")
                raise IngestionCancelled(f"Ingestion of '{source}' was cancelled")

            batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            batch_embeddings = embed_batch(batch)
            if len(batch_embeddings) != len(batch) or any(e is None for e in batch_embeddings):
                raise RuntimeError(
                    f"embed_batch returned {len(batch_embeddings)} embeddings for "
                    f"{len(batch)} chunks of '{source}' at offset {batch_start}"
                )
            embeddings.extend(batch_embeddings)
        return embeddings

    def store(
        self,
        chunks: list[str],
        source: str,
        metadata: dict | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> int:
        """Store pre-embedded chunks in ChromaDB and return the number stored.

        `embeddings` is computed by embed_chunks() when omitted.
        """
        base_meta = {"source": source, "user_id": self.user_id}
        if metadata:
            base_meta.update(metadata)

        if embeddings is None:
            embeddings = self.embed_chunks(chunks, source)

        stored = 0
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            if self.job_id and is_cancelled(self.job_id):
                logger.info(f"Ingestion of '{source}' cancelled - stopping chunk processing")
                raise IngestionCancelled(f"Ingestion of '{source}' was cancelled")

            batch_chunks = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            batch_embeddings = embeddings[batch_start : batch_start + EMBED_BATCH_SIZE]

            ids = [str(uuid.uuid4()) for _ in batch_chunks]
            metadatas = [
                {**base_meta, "chunk_index": batch_start + idx} for idx in range(len(batch_chunks))
            ]

            try:
                self.collection.add(
                    embeddings=batch_embeddings,
                    documents=batch_chunks,
                    metadatas=metadatas,
                    ids=ids,
                )
                stored += len(batch_chunks)
            except Exception as e:
                logger.error(f"Failed batched store for '{source}' at start {batch_start}: {e}")

        logger.info(f"Stored {stored}/{len(chunks)} chunks from '{source}'")
        return stored

    def store_summary(self, summary: str, source: str) -> None:
        """Store a document-level summary for stage 1 hierarchical retrieval."""
        try:
            embedding = embed(summary)
            self.summary_collection.add(
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{"source": source, "user_id": self.user_id}],
                ids=[str(uuid.uuid4())],
            )
            logger.info(f"Stored summary for '{source}'")
        except Exception as e:
            logger.error(f"Failed to store summary for '{source}': {e}")

    def _update_job_status(self, new_status: str) -> None:
        """Update the queue status for the active job, if one is attached."""
        if not self.job_id:
            return
        _update_job(self.job_id, new_status)

    def _set_estimate(self, seconds: int) -> None:
        """Update the time estimate for the current job."""
        if not self.job_id:
            return
        update_job_estimate(self.job_id, seconds)

    def _set_progress(self, current: int, total: int, unit: str = "page") -> None:
        """Report "unit `current` of `total`" for the current job's active phase.

        Only phases with a countable loop call this; the frontend falls back to its
        time-based estimate wherever it stays absent.
        """
        if not self.job_id:
            return
        update_job_progress(self.job_id, current, total, unit)

    def _count_graph_items_for_source(self, source: str) -> tuple[int, int]:
        """Count graph nodes/edges for a source to report background build progress."""
        conn = graph_connection(self.user_id)
        try:
            entity_count = conn.execute(
                f"SELECT COUNT(*) FROM nodes_{self.user_id} WHERE source = ?",
                (source,),
            ).fetchone()[0]
            relationship_count = conn.execute(
                f"SELECT COUNT(*) FROM edges_{self.user_id} WHERE source = ?",
                (source,),
            ).fetchone()[0]
            return entity_count, relationship_count
        finally:
            conn.close()

    def _cleanup_partial(self, source: str, reason: str) -> None:
        """Remove everything a job that did not reach "done" had already written.

        Chunks, summary, graph rows, cache and stored original all go; safe to call twice.
        """
        try:
            delete_source(source, self.user_id)
            logger.info(f"Removed partial data for {reason} '{source}'")
        except Exception as e:
            logger.error(f"Cleanup after {reason} '{source}' failed: {e}")

    def _build_graph(self, chunks: list[str], source: str) -> None:
        """Build the knowledge graph - the second half of the job, run inline on
        the ingestion worker so the source isn't 'ready' until it finishes."""
        # Before the status write, which would clobber a "cancelled" landing in the handoff
        if self.job_id and is_cancelled(self.job_id):
            logger.info(f"Graph build for '{source}' cancelled before starting")
            self._cleanup_partial(source, "cancelled")
            return
        logger.info(f"Building knowledge graph for '{source}'...")
        # Before the status flip, so one poll carries both and the bar has no stale estimate
        self._set_estimate(len(chunks) * GRAPH_SECONDS_PER_CHUNK)
        self._update_job_status("building_graph")
        start = time.time()
        try:
            # Polled per chunk - cancel_job() only flips a string, nothing else stops a build
            build_from_chunks(
                chunks,
                source,
                self.user_id,
                should_stop=(lambda: is_cancelled(self.job_id)) if self.job_id else None,
                on_progress=lambda done, total: self._set_progress(done, total, "chunk"),
            )
            if self.job_id and is_cancelled(self.job_id):
                logger.info(f"Graph build for '{source}' cancelled mid-build")
                # Leave it "cancelled" - "done" would claim a build the user stopped
                self._cleanup_partial(source, "cancelled")
                return
            entities, relationships = self._count_graph_items_for_source(source)
            elapsed = time.time() - start
            logger.info(
                f"Knowledge graph complete for '{source}': "
                f"{entities} entities, {relationships} relationships"
            )
            self._update_job_status("done")
            send_telemetry(
                "graph_complete",
                {
                    "source": source,
                    "entities": entities,
                    "relationships": relationships,
                    "duration_s": round(elapsed, 1),
                },
            )
        except Exception as e:
            logger.error(f"Knowledge graph build failed for '{source}': {e}")
            # Before the terminal status, which makes the source visible to retrieval
            self._cleanup_partial(source, "failed")
            self._update_job_status(f"error: {e}")

    def ingest(
        self,
        source_path: str | Path,
        source_name: str,
        metadata: dict | None = None,
    ) -> int:
        """Full pipeline for one job: extract -> chunk -> store -> summarize ->
        build the knowledge graph. Returns only once all of it is done, because
        the job's queue slot is held for the whole thing."""
        if not str(source_path).startswith(("http://", "https://")):
            source_path = Path(source_path)
        logger.info(f"Ingesting '{source_name}' for user '{self.user_id}'")
        # No status write - repeating "ingesting" here overwrote a cancel set during the import

        try:
            # Extract text
            text = self.extract_text(source_path, source_name)
            if not text or not text.strip():
                logger.warning(f"No text extracted from '{source_name}'")
                self._update_job_status("error: no text extracted")
                return 0

            # Chunk
            chunks = chunk_text(text)
            logger.info(f"Split '{source_name}' into {len(chunks)} chunks")

            # Build metadata
            extra_meta = {"type": self.__class__.__name__}
            if metadata:
                extra_meta.update(metadata)

            # Before the re-ingest delete - a failed embed must not destroy the old copy
            embeddings = self.embed_chunks(chunks, source_name)

            # -- Re-ingestion cleanup --------------------------------------
            # Only wipe on re-ingest - a new source would exercise the graph DELETE for nothing
            existing = self.collection.get(
                where={"source": source_name}, limit=1, include=["metadatas"]
            )
            if existing["ids"]:
                # remove_file=False - the new upload is already at that path
                delete_source(source_name, self.user_id, remove_file=False)

            stored = self.store(chunks, source_name, extra_meta, embeddings=embeddings)
            if stored <= 0:
                self._update_job_status("error: no chunks stored")
                return stored

            # Generate and store document summary for hierarchical retrieval
            summary_prompt = (
                f"Summarize the following document in 3-4 sentences for search indexing. "
                f"Document: {text[:2000]}"
            )
            summary = "".join(generate_stream(summary_prompt, model=get_model("summarize")))
            self.store_summary(summary, source_name)
            # Extraction flows straight into the graph build, which owns the next transition
            send_telemetry(
                "ingest",
                {
                    "source": source_name,
                    "chunks": stored,
                },
            )

            # Inline on this worker thread - the source is not "done" until it finishes
            self._build_graph(chunks, source_name)

            # The source becomes visible here, so this is when cached retrievals go stale
            clear_cache(self.user_id)

            return stored
        except IngestionCancelled as e:
            logger.info(f"Ingestion of '{source_name}' cancelled: {e}")
            # Status is already "cancelled"; only the chunks stored before it landed must go
            self._cleanup_partial(source_name, "cancelled")
            return 0
        except Exception as e:
            # Guards the window where a raise left chunks queryable with no graph
            logger.error(f"Ingestion of '{source_name}' failed: {e}")
            self._cleanup_partial(source_name, "failed")
            raise  # the worker owns the terminal "error: ..." status
