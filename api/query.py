import asyncio
import json
import time
from collections.abc import AsyncGenerator, Generator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model
from retrieval.embed import embed
from retrieval.graph import has_graph
from retrieval.pipeline import (
    RAGPipeline,
    build_answer_prompt,
    build_context,
    build_direct_prompt,
    format_history,
)
from utils.cache import get_cached_response, set_cached_response
from utils.ollama_client import generate_stream
from utils.telemetry import send_telemetry

logger = setup_logging(__name__)
router = APIRouter(prefix="/query", tags=["query"])

_pipeline = RAGPipeline()

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant for a personal knowledge base. Be concise and direct. "
    "Answer in 2-3 paragraphs unless the user explicitly asks for more detail or the topic "
    "genuinely requires a longer explanation. "
    "Do not add unnecessary preamble, summaries, or padding. "
    "Never cite source document names inline in your response."
)


class QueryRequest(BaseModel):
    question: str
    user_id: str
    history: list[dict] = []
    source_filter: list[str] | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    scores: list[float]


@router.post("", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    Run the full RAG pipeline: retrieval, rerank, and answer generation.
    Checks the semantic cache first; on a hit, reuses retrieved chunks but
    regenerates a fresh answer against the new question.
    """
    t0 = time.time()
    logger.info(f"Query from user '{req.user_id}': {req.question}")

    query_embedding = embed(req.question)
    cached = get_cached_response(query_embedding, req.user_id)

    if cached:
        # Cache hit: reuse retrieved context, generate a fresh answer for the new question.
        history_str = format_history(req.history)
        prompt = build_answer_prompt(req.question, cached["context"], history_str)
        answer = "".join(generate_stream(prompt, system=_SYSTEM_PROMPT, model=get_model("answer")))
        latency = time.time() - t0
        logger.info(f"Cache hit — response in {latency:.2f}s")
        send_telemetry(
            "query_rag",
            req.user_id,
            {"latency": round(latency, 2), "question_len": len(req.question), "cache_hit": True},
        )
        return QueryResponse(answer=answer, sources=cached["sources"], scores=cached["scores"])

    # Cache miss: run full retrieval, then generate answer via generate_stream.
    retrieval = _pipeline.retrieve_context(
        question=req.question,
        user_id=req.user_id,
        history=req.history,
        source_filter=req.source_filter,
    )
    prompt = build_answer_prompt(req.question, retrieval["context"], retrieval["history_str"])
    answer = "".join(generate_stream(prompt, system=_SYSTEM_PROMPT, model=get_model("answer")))

    set_cached_response(
        req.question,
        query_embedding,
        {
            "context": retrieval["context"],
            "sources": retrieval["sources"],
            "scores": retrieval["scores"],
        },
        req.user_id,
    )

    latency = time.time() - t0
    logger.info(f"Query latency: {latency:.2f}s")
    send_telemetry(
        "query_rag",
        req.user_id,
        {
            "latency": round(latency, 2),
            "question_len": len(req.question),
            "cache_hit": False,
        },
    )
    return QueryResponse(
        answer=answer,
        sources=retrieval["sources"],
        scores=retrieval["scores"],
    )


@router.post("/stream")
async def query_stream(req: QueryRequest) -> StreamingResponse:
    """
    Same retrieval as /query, but streams progress and the answer as
    Server-Sent Events. `data: [STAGE]{"stage": ...}\\n\\n` events mark
    retrieval/reranking/generation as they begin, followed by token events
    (`data: {token}\\n\\n`), a `data: [SOURCES]{json}\\n\\n` citation event,
    and `data: [DONE]\\n\\n`. `data: [HEARTBEAT]\\n\\n` keep-alive events are
    emitted before each blocking call so the connection does not time out.
    """
    t0 = time.time()
    logger.info(f"Streaming query from user '{req.user_id}': {req.question}")

    async def event_stream() -> AsyncGenerator[str, None]:
        history_str = format_history(req.history)

        yield f"data: [STAGE]{json.dumps({'stage': 'retrieving_sources'})}\n\n"
        if has_graph(req.user_id):
            yield f"data: [STAGE]{json.dumps({'stage': 'traversing_graph'})}\n\n"
        yield "data: [HEARTBEAT]\n\n"
        docs, metas = await asyncio.to_thread(
            _pipeline.search_candidates,
            query=req.question,
            user_id=req.user_id,
            source_filter=req.source_filter,
        )

        yield f"data: [STAGE]{json.dumps({'stage': 'reranking'})}\n\n"
        yield "data: [HEARTBEAT]\n\n"
        docs, metas, scores = await asyncio.to_thread(
            _pipeline.rerank_candidates, req.question, docs, metas
        )

        context = build_context(docs, metas)
        sources = list({meta["source"] for meta in metas})
        chunks = [
            {"source": meta["source"], "text": doc, "score": round(score, 3)}
            for doc, meta, score in zip(docs, metas, scores)
        ]
        prompt = build_answer_prompt(req.question, context, history_str)

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        for token in generate_stream(prompt, system=_SYSTEM_PROMPT, model=get_model("answer")):
            yield f"data: {token}\n\n"

        sources_payload = json.dumps({"sources": sources, "scores": scores, "chunks": chunks})
        yield f"data: [SOURCES]{sources_payload}\n\n"
        yield "data: [DONE]\n\n"

        latency = time.time() - t0
        logger.info(f"Streaming query latency: {latency:.2f}s")
        send_telemetry(
            "query",
            req.user_id,
            {"latency": round(latency, 2), "question_len": len(req.question)},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/direct")
async def query_direct(req: QueryRequest) -> StreamingResponse:
    """
    Bypass the RAG pipeline entirely — no retrieval, reranking, or ChromaDB
    queries. Sends the question straight to generate_stream() with qwen3.
    Used when the user has deselected all sources ("direct LLM mode"), so
    the response feels near-instant compared to the full pipeline. Same SSE
    event format as /query/stream (no [STAGE] events, empty [SOURCES]).
    """
    t0 = time.time()
    logger.info(f"Direct query (no RAG) from user '{req.user_id}': {req.question}")

    def event_stream() -> Generator[str, None, None]:
        history_str = format_history(req.history)
        prompt = build_direct_prompt(req.question, history_str)

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        for token in generate_stream(prompt, system=_SYSTEM_PROMPT, model=get_model("answer")):
            yield f"data: {token}\n\n"

        yield f"data: [SOURCES]{json.dumps({'sources': [], 'scores': []})}\n\n"
        yield "data: [DONE]\n\n"

        latency = time.time() - t0
        logger.info(f"Direct query latency: {latency:.2f}s")
        send_telemetry(
            "query_direct",
            req.user_id,
            {"latency": round(latency, 2), "question_len": len(req.question)},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
