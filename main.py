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
    WARMUP_TASK_TIMEOUT_SECONDS,
)
from ingestion.queue import start as start_ingestion_queue
from retrieval.pipeline import configure_dspy
from utils.ollama_client import unload, warm

logger = setup_logging(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RAGbase...")
    load_settings()
    logger.info(f"User ID: {USER_ID}, telemetry device ID: {DEVICE_ID}")
    configure_dspy(OLLAMA_URL, MODEL_STANDARD)
    start_ingestion_queue()

    async def _warm_one(task: str) -> None:
        """Load one model. `reranker` is a HuggingFace cross-encoder, not an Ollama task."""
        if task == "reranker":
            # warm_reranker(), not rerank(): rerank() swallows a load failure and
            # returns the original order, so warming through it reported success
            # for a model that never loaded and every later query degraded to
            # unranked passthrough with nothing in the log to say so.
            from retrieval.reranker import warm_reranker

            await asyncio.to_thread(warm_reranker)
            return
        await asyncio.to_thread(warm, task)

    async def _warmup() -> None:
        """
        Warm every model, query-critical ones first.

        Sequential and ordered on purpose: the frontend gates its UI on the
        critical group (config/runtime.py), so those must not queue behind a
        large model, and running them all at once would only have them fight
        over the same GPU while the user waits.

        WARMUP_BACKGROUND_TASKS is empty now, so in practice this loop is the
        critical group alone — the concatenation stays because the split is the
        contract, not the current contents. See the constant for why the
        ingestion-only models were dropped from warmup entirely.
        """
        logger.info("Warming up models...")
        for task in WARMUP_CRITICAL_TASKS + WARMUP_BACKGROUND_TASKS:
            warmup_started(task)
            try:
                # Bounded because the frontend's gate has no escape hatch: a step
                # that hangs rather than raises would never reach the `finally`,
                # and the UI would stay blocked forever.
                await asyncio.wait_for(_warm_one(task), timeout=WARMUP_TASK_TIMEOUT_SECONDS)
                logger.info(f"  {task} warmed up")
            except TimeoutError:
                logger.warning(
                    f"  {task} warmup timed out after {WARMUP_TASK_TIMEOUT_SECONDS}s "
                    f"(non-blocking; first use will pay the load)"
                )
            except Exception as e:
                logger.warning(f"  {task} warmup failed (non-blocking): {e}")
            finally:
                # Also on failure and timeout — a model that won't load must not
                # leave the UI waiting on it forever.
                warmup_finished(task)
            if task == WARMUP_CRITICAL_TASKS[-1] and WARMUP_BACKGROUND_TASKS:
                logger.info("Ready for queries — remaining models warm in the background")
        logger.info("All models warmed up")

    warmup_register(WARMUP_CRITICAL_TASKS)
    asyncio.create_task(_warmup())
    logger.info("RAGbase ready")

    yield

    logger.info("Shutting down RAGbase...")
    # Hand back the several GB the query models hold. They are pinned for
    # OLLAMA_KEEP_ALIVE (3h), which is a long time to keep a GPU occupied for a
    # process that has exited — but the TTL is finite precisely because this hook
    # is not guaranteed to run: it fires for Ctrl+C and SIGTERM, not for SIGHUP
    # (closing the terminal), not for the `kill -9` scripts/start.sh opens with,
    # and not for Force Quit. Best-effort by design, one model at a time, and a
    # failure here must never turn a clean shutdown into a traceback.
    #
    # The reranker is deliberately absent: it is a HuggingFace model held in a
    # module global (retrieval/reranker.py), not an Ollama runner, so it has no
    # TTL to shorten and is freed when this process exits.
    for task in ("embed", "answer"):
        try:
            await asyncio.to_thread(unload, task)
            logger.info(f"  unloaded {task}")
        except Exception as e:
            logger.warning(f"  could not unload {task} (non-blocking): {e}")


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
