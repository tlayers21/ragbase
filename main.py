import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import (
    compact_router,
    documents_router,
    ingest_router,
    query_router,
    sessions_router,
    settings_router,
    sources_router,
    title_router,
)
from config.logging import setup_logging
from config.models import MODEL_STANDARD
from config.runtime import (
    DEVICE_ID,
    USER_ID,
    get_warmup_status,
    load_settings,
    warmup_finished,
    warmup_register,
    warmup_started,
)
from config.settings import (
    OLLAMA_URL,
    WARMUP_BACKGROUND_TASKS,
    WARMUP_CRITICAL_TASKS,
)
from ingestion.queue import start as start_ingestion_queue
from ingestion.queue import start_graph_queue
from retrieval.pipeline import configure_dspy
from utils.ollama_client import warm

logger = setup_logging(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RAGbase...")
    load_settings()
    logger.info(f"User ID: {USER_ID}, telemetry device ID: {DEVICE_ID}")
    configure_dspy(OLLAMA_URL, MODEL_STANDARD)
    start_ingestion_queue()
    start_graph_queue()

    async def _warm_one(task: str) -> None:
        """Load one model. `reranker` is a HuggingFace cross-encoder, not an Ollama task."""
        if task == "reranker":
            from retrieval.reranker import rerank

            await asyncio.to_thread(rerank, "warmup", ["warmup"], [{}])
            return
        await asyncio.to_thread(warm, task)

    async def _warmup() -> None:
        """
        Warm every model, query-critical ones first.

        Sequential and ordered on purpose: the frontend gates its UI on the
        critical group (config/runtime.py), so those must not queue behind
        qwen2.5vl, and running them all at once would only have them fight over
        the same GPU while the user waits.
        """
        logger.info("Warming up models...")
        for task in WARMUP_CRITICAL_TASKS + WARMUP_BACKGROUND_TASKS:
            warmup_started(task)
            try:
                await _warm_one(task)
                logger.info(f"  {task} warmed up")
            except Exception as e:
                logger.warning(f"  {task} warmup failed (non-blocking): {e}")
            finally:
                # Also on failure — a model that won't load must not leave the UI
                # waiting on it forever.
                warmup_finished(task)
            if task == WARMUP_CRITICAL_TASKS[-1]:
                logger.info("Ready for queries — remaining models warm in the background")
        logger.info("All models warmed up")

    warmup_register(WARMUP_CRITICAL_TASKS)
    asyncio.create_task(_warmup())
    logger.info("RAGbase ready")

    yield

    logger.info("Shutting down RAGbase...")


app = FastAPI(title="RAGbase", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"http://localhost:\d+",  # dev server may fall back to another port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Routes ----------------------------------------------------------------
app.include_router(compact_router)
app.include_router(ingest_router)
app.include_router(query_router)
app.include_router(documents_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(sources_router)
app.include_router(title_router)


@app.get("/health")
def health():
    """
    Liveness plus startup-warmup progress.

    `ready` is false while the models a query needs are still loading — the
    frontend polls this and keeps its UI blocked until it flips, because a query
    sent mid-warmup competes with it for the GPU and stalls.
    """
    return {"status": "ok", **get_warmup_status()}


@app.get("/")
async def root():
    return {"status": "RAGbase API running"}
