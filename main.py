from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import compact_router, documents_router, ingest_router, query_router, sessions_router, sources_router, title_router
from config.logging import setup_logging
from config.models import MODEL_STANDARD, get_model
from config.settings import OLLAMA_URL
from ingestion.queue import start as start_ingestion_queue
from retrieval.pipeline import configure_dspy

logger = setup_logging(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    logger.info("Starting RAGbase...")
    configure_dspy(OLLAMA_URL, MODEL_STANDARD)
    start_ingestion_queue()

    async def _warmup_reranker() -> None:
        try:
            from retrieval.reranker import rerank
            await asyncio.to_thread(rerank, "warmup", ["warmup"], [{}])
            logger.info("Reranker warmed up")
        except Exception as e:
            logger.warning(f"Reranker warmup failed (first query may be slow): {e}")

    async def _warmup_models() -> None:
        import ollama as _ollama
        logger.info("Warming up models...")
        for task in ("answer", "summarize", "embed", "vision_simple"):
            model = get_model(task)
            try:
                if task == "embed":
                    await asyncio.to_thread(_ollama.embeddings, model=model, prompt="hi")
                else:
                    await asyncio.to_thread(
                        _ollama.generate, model, "hi"
                    )
                logger.info(f"  {task} ({model}) warmed up")
            except Exception as e:
                logger.warning(f"  {task} ({model}) warmup failed (non-blocking): {e}")
        logger.info("All models warmed up")

    asyncio.create_task(_warmup_reranker())
    asyncio.create_task(_warmup_models())
    logger.info("RAGbase ready")

    yield

    logger.info("Shutting down RAGbase...")


app = FastAPI(title="RAGbase", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
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
app.include_router(sources_router)
app.include_router(title_router)


@app.get("/health")
def health():
    return {"status": "ok"}
