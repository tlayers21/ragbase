import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from config.logging import setup_logging
from config.paths import KNOWLEDGE_GRAPH_DB_PATH
from config.settings import EMBED_BATCH_SIZE
from ingestion.queue import _update_job, is_cancelled, update_job_estimate
from retrieval.embed import chunk_text, embed, embed_batch
from retrieval.graph import build_from_chunks
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
    """Base class for all ingestors. Handles chunking, embedding, and storing.
    Subclasses only need to implement extract_text()."""

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
    def store(self, chunks: list[str], source: str, metadata: dict | None = None) -> int:
        """Embed and store chunks in ChromaDB. Returns number of chunks stored."""
        base_meta = {"source": source, "user_id": self.user_id}
        if metadata:
            base_meta.update(metadata)

        stored = 0
        # Batch embeddings and batched upserts to ChromaDB for efficiency
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            if self.job_id and is_cancelled(self.job_id):
                logger.info(f"Ingestion of '{source}' cancelled — stopping chunk processing")
                raise IngestionCancelled(f"Ingestion of '{source}' was cancelled")

            batch_chunks = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            try:
                embeddings = embed_batch(batch_chunks)
            except Exception as e:
                logger.error(f"embed_batch failed for '{source}' at start {batch_start}: {e}")
                embeddings = [None] * len(batch_chunks)

            ids = [str(uuid.uuid4()) for _ in batch_chunks]
            metadatas = [
                {**base_meta, "chunk_index": batch_start + idx} for idx in range(len(batch_chunks))
            ]

            # Filter out any None embeddings and attempt to add in a single call
            valid_docs = []
            valid_metas = []
            valid_embs = []
            valid_ids = []
            for i, (chunk_txt, emb, _id, meta) in enumerate(
                zip(batch_chunks, embeddings, ids, metadatas)
            ):
                if emb is None:
                    logger.error(
                        f"Missing embedding for chunk {batch_start + i} of '{source}' — skipping"
                    )
                    continue
                valid_docs.append(chunk_txt)
                valid_metas.append(meta)
                valid_embs.append(emb)
                valid_ids.append(_id)

            if not valid_docs:
                continue

            try:
                self.collection.add(
                    embeddings=valid_embs,
                    documents=valid_docs,
                    metadatas=valid_metas,
                    ids=valid_ids,
                )
                stored += len(valid_docs)
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

    def _count_graph_items_for_source(self, source: str) -> tuple[int, int]:
        """Count graph nodes/edges for a source to report background build progress."""
        conn = sqlite3.connect(KNOWLEDGE_GRAPH_DB_PATH)
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

    def _build_graph_background(self, chunks: list[str], source: str) -> None:
        """Build the knowledge graph asynchronously so ingestion can finish quickly."""
        logger.info(f"Building knowledge graph for '{source}' in background...")
        self._update_job_status("building_graph")
        if self.job_id and is_cancelled(self.job_id):
            logger.info(f"Graph build for '{source}' cancelled before starting")
            return
        start = time.time()
        try:
            build_from_chunks(chunks, source, self.user_id)
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
            logger.error(f"Background knowledge graph build failed for '{source}': {e}")
            self._update_job_status(f"error: {e}")

    def ingest(
        self,
        source_path: str | Path,
        source_name: str,
        metadata: dict | None = None,
    ) -> int:
        """Full ingestion pipeline: extract -> chunk -> store -> summarize."""
        if not str(source_path).startswith(("http://", "https://")):
            source_path = Path(source_path)
        logger.info(f"Ingesting '{source_name}' for user '{self.user_id}'")
        self._update_job_status("ingesting")

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

            # -- Re-ingestion cleanup --------------------------------------
            # Only wipe existing data when re-ingesting a known source.
            # For brand-new sources this would be a no-op on ChromaDB but
            # would still exercise the graph DELETE path unnecessarily.
            existing = self.collection.get(
                where={"source": source_name}, limit=1, include=["metadatas"]
            )
            if existing["ids"]:
                delete_source(source_name, self.user_id)

            # Store chunks
            stored = self.store(chunks, source_name, extra_meta)
            if stored <= 0:
                self._update_job_status("error: no chunks stored")
                return stored

            # Generate and store document summary for hierarchical retrieval
            summary_prompt = (
                f"Summarize the following document in 3-4 sentences for search indexing. "
                f"Document: {text[:2000]}"
            )
            summary = "".join(generate_stream(summary_prompt))
            self.store_summary(summary, source_name)
            self._update_job_status("ingested")
            clear_cache(self.user_id)
            send_telemetry(
                "ingest",
                {
                    "source": source_name,
                    "chunks": stored,
                },
            )

            # Phase 2: build knowledge graph in background; do not block completion.
            threading.Thread(
                target=self._build_graph_background,
                args=(chunks, source_name),
                daemon=True,
            ).start()

            return stored
        except IngestionCancelled as e:
            logger.info(f"Ingestion of '{source_name}' cancelled: {e}")
            # Status was already set to "cancelled" by the cancel endpoint —
            # don't overwrite it here.
            return 0
