import asyncio
import json
import os
import tempfile
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.guards import require_finished
from config.logging import setup_logging
from config.models import get_model
from config.runtime import USER_ID, query_finished, query_started
from config.settings import (
    ANSWER_THINKING_ENABLED,
    ATTACHMENT_TEXT_MAX_CHARS,
    EXPLAIN_BATCH_CHUNKS,
    EXPLAIN_HEARTBEAT_SECONDS,
    EXPLAIN_MAX_CHUNKS,
    OLLAMA_KEEP_ALIVE,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_PDF_EXTENSIONS,
)
from ingestion.helpers import describe_image
from ingestion.queue import active_sources, find_active_job
from retrieval.embed import embed
from retrieval.graph import has_graph
from retrieval.pipeline import (
    RAGPipeline,
    build_answer_prompt,
    build_context,
    build_direct_prompt,
    build_explain_prompt,
    format_history,
)
from utils.cache import get_cached_response, set_cached_response
from utils.chromadb_client import get_source_chunks
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
    "Never cite source document names inline in your response. "
    "Never reference 'the context', 'the provided context', 'retrieved documents', "
    "'the examples', 'the text', or any phrase that narrates where your information came from. "
    "Weave all information naturally into your answer as if it were already known."
)


def _answer_stream(prompt: str, system: str = _SYSTEM_PROMPT) -> Generator[str, None, None]:
    """The single entry point for every user-facing answer.

    Also the only place the answer model's long residency is renewed.
    """
    return generate_stream(
        prompt,
        system=system,
        model=get_model("answer"),
        think=ANSWER_THINKING_ENABLED,
        keep_alive=OLLAMA_KEEP_ALIVE,
    )


async def _aiter_answer(prompt: str, system: str = _SYSTEM_PROMPT) -> AsyncGenerator[str, None]:
    """Pump `_answer_stream` without holding the event loop for the whole answer.

    One `to_thread` per `next()`, because a blocking generator inside an `async def`
    stalls every other in-flight SSE stream until generation finishes.
    """
    gen = _answer_stream(prompt, system=system)
    sentinel = object()
    while True:
        # Sequential awaits, so only one thread ever advances the generator at a time
        token = await asyncio.to_thread(next, gen, sentinel)
        if token is sentinel:
            return
        yield token


def _sse_token(token: str) -> str:
    """Frame one model token as an SSE event, JSON-encoded.

    A raw newline in the payload would collide with the blank-line frame delimiter and
    be swallowed; matched pair with the frontend's `consumeQueryStream`.
    """
    return f"data: {json.dumps(token)}\n\n"


def _sse_timing(t0: float) -> str:
    """Frame the server's elapsed time as the last control event before [DONE].

    Milliseconds rather than a timestamp so no clock skew enters the number, and a
    separate frame because the parser matches [DONE] exactly.
    """
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    return f"data: [TIMING]{json.dumps({'server_ms': elapsed_ms})}\n\n"


async def _with_query_priority(
    stream: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """Flag the process as serving a query for as long as `stream` is producing.

    Wraps the generator rather than the endpoint so the `finally` also runs when the
    client disconnects mid-stream.
    """
    query_started()
    try:
        async for frame in stream:
            yield frame
    finally:
        query_finished()


def _fresh_cached_response(query_embedding: list[float]) -> dict | None:
    """A cached retrieval, unless it draws on a source that is mid-ingest.

    A cache hit skips `search_candidates()`, so this is the only place the
    unfinished-source exclusion can be applied to a cached entry.
    """
    cached = get_cached_response(USER_ID, query_embedding)
    if not cached:
        return None

    # An empty context is a cached failure - serving it replays the miss for the TTL
    if not cached.get("context"):
        logger.info("Discarding cached retrieval - empty context, retrieval returned nothing")
        return None

    in_flight = active_sources(USER_ID)
    stale = in_flight.intersection(cached.get("sources", []))
    if stale:
        logger.info(f"Discarding cached retrieval - sources still ingesting: {sorted(stale)}")
        return None
    return cached


class QueryRequest(BaseModel):
    question: str
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
    t0 = time.perf_counter()
    logger.info(f"Query: {req.question}")

    query_embedding = embed(req.question)
    cached = _fresh_cached_response(query_embedding)

    if cached:
        # Cache hit: reuse retrieved context, generate a fresh answer for the new question
        history_str = format_history(req.history)
        prompt = build_answer_prompt(req.question, cached["context"], history_str)
        answer = "".join(_answer_stream(prompt))
        latency = time.perf_counter() - t0
        logger.info(f"Cache hit - response in {latency:.2f}s")
        send_telemetry(
            "query_rag",
            {"latency": round(latency, 2), "question_len": len(req.question), "cache_hit": True},
        )
        return QueryResponse(answer=answer, sources=cached["sources"], scores=cached["scores"])

    # Cache miss: run full retrieval, then generate answer via generate_stream
    retrieval = _pipeline.retrieve_context(
        question=req.question,
        user_id=USER_ID,
        history=req.history,
        source_filter=req.source_filter,
    )
    prompt = build_answer_prompt(req.question, retrieval["context"], retrieval["history_str"])
    answer = "".join(_answer_stream(prompt))

    # Same empty-retrieval guard as the streaming path, which is the only live caller
    if retrieval["context"]:
        set_cached_response(
            USER_ID,
            query_embedding,
            {
                "context": retrieval["context"],
                "sources": retrieval["sources"],
                "scores": retrieval["scores"],
            },
        )

    latency = time.perf_counter() - t0
    logger.info(f"Query latency: {latency:.2f}s")
    send_telemetry(
        "query_rag",
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
async def query_stream(req: QueryRequest, request: Request) -> StreamingResponse:
    """Same retrieval as /query, but streams progress and the answer as Server-Sent Events.

    Emits [STAGE], token, [SOURCES], [TIMING], [HEARTBEAT] and [DONE] frames.
    """
    t0 = time.perf_counter()
    logger.info(f"Streaming query: {req.question}")

    async def event_stream() -> AsyncGenerator[str, None]:
        history_str = format_history(req.history)

        yield f"data: [STAGE]{json.dumps({'stage': 'retrieving_sources'})}\n\n"

        # Filtered queries bypass the cache - it would leak deselected sources' chunks
        cached = None
        if not req.source_filter:
            query_embedding = await asyncio.to_thread(embed, req.question)
            cached = await asyncio.to_thread(_fresh_cached_response, query_embedding)

        if cached:
            context = cached["context"]
            sources = cached["sources"]
            scores = cached["scores"]
            chunks = cached.get("chunks", [])  # entries cached before chunks were stored
        else:
            if has_graph(USER_ID):
                yield f"data: [STAGE]{json.dumps({'stage': 'traversing_graph'})}\n\n"
            yield "data: [HEARTBEAT]\n\n"
            docs, metas = await asyncio.to_thread(
                _pipeline.search_candidates,
                query=req.question,
                user_id=USER_ID,
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

            # Caching a miss would cost every similar question for CACHE_TTL
            if not req.source_filter and chunks:
                await asyncio.to_thread(
                    set_cached_response,
                    USER_ID,
                    query_embedding,
                    {
                        "context": context,
                        "sources": sources,
                        "scores": scores,
                        "chunks": chunks,
                    },
                )

        prompt = build_answer_prompt(req.question, context, history_str)

        if await request.is_disconnected():
            return

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        async for token in _aiter_answer(prompt):
            if token:
                yield _sse_token(token)

        sources_payload = json.dumps({"sources": sources, "scores": scores, "chunks": chunks})
        yield f"data: [SOURCES]{sources_payload}\n\n"
        yield _sse_timing(t0)
        yield "data: [DONE]\n\n"

        latency = time.perf_counter() - t0
        logger.info(f"Streaming query latency: {latency:.2f}s (cache_hit={bool(cached)})")
        send_telemetry(
            "query_rag",
            {
                "latency": round(latency, 2),
                "question_len": len(req.question),
                "cache_hit": bool(cached),
            },
        )

    return StreamingResponse(_with_query_priority(event_stream()), media_type="text/event-stream")


@router.post("/direct")
async def query_direct(req: QueryRequest) -> StreamingResponse:
    """Answer without retrieval, using only the question and recent conversation history.

    Same SSE frames as /query/stream, minus [SOURCES].
    """
    t0 = time.perf_counter()
    logger.info(f"Direct query (no RAG): {req.question}")

    def event_stream() -> Generator[str, None, None]:
        history_str = format_history(req.history)
        prompt = build_direct_prompt(req.question, history_str)

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        for token in _answer_stream(prompt):
            if token:
                yield _sse_token(token)

        yield f"data: [SOURCES]{json.dumps({'sources': [], 'scores': []})}\n\n"
        yield _sse_timing(t0)
        yield "data: [DONE]\n\n"

        latency = time.perf_counter() - t0
        logger.info(f"Direct query latency: {latency:.2f}s")
        send_telemetry(
            "query_direct",
            {"latency": round(latency, 2), "question_len": len(req.question)},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# -- Explain in depth ---------------------------------------------------------
# Builds its own context rather than reusing RAGPipeline - there is no question to rank against
_EXPLAIN_SYSTEM_PROMPT = (
    "You are a helpful AI assistant for a personal knowledge base. You are explaining "
    "one document from that knowledge base to its owner. Be thorough and well "
    "organised: use markdown headings, and take as much room as the material needs. "
    "Ground every statement in the document you are given, and do not invent material "
    "it does not contain."
)


class ExplainRequest(BaseModel):
    source: str


def _explain_context(chunks: list[tuple[str, dict]]) -> str:
    """Format whole-source chunks for the prompt, in document order."""
    docs = [doc for doc, _ in chunks]
    metas = [meta for _, meta in chunks]
    return build_context(docs, metas)


def _summarize_batch(chunks: list[tuple[str, dict]], source: str, part: int, total: int) -> str:
    """Map step: condense one batch of chunks so an oversized source still fits.

    Runs on the fast model, which `generate_stream` would otherwise not select.
    """
    prompt = (
        f"Below is part {part} of {total} of a document titled '{source}'.\n\n"
        "Summarize this part in detail. Keep every key idea, definition, result and "
        "conclusion, along with enough specifics that the summary could stand in for "
        "the text itself. Do not add anything that is not present.\n\n"
        f"Text:\n{_explain_context(chunks)}\n\nSummary:"
    )
    return "".join(generate_stream(prompt, model=get_model("summarize"))).strip()


@router.post("/explain")
async def query_explain(req: ExplainRequest, request: Request) -> StreamingResponse:
    """Explain one source in depth, using all of its chunks in document order and no ranking.

    Sources over EXPLAIN_MAX_CHUNKS are summarized in batches first; [SOURCES] carries the
    source name with no chunks, because nothing here was matched.
    """
    t0 = time.perf_counter()
    await require_finished(req.source)

    chunks = await asyncio.to_thread(get_source_chunks, req.source, USER_ID)
    if not chunks:
        raise HTTPException(status_code=404, detail=f"Source '{req.source}' not found")

    logger.info(f"Explain request for '{req.source}' ({len(chunks)} chunks)")

    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"data: [STAGE]{json.dumps({'stage': 'loading_source'})}\n\n"

        oversized = len(chunks) > EXPLAIN_MAX_CHUNKS
        if oversized:
            batches = [
                chunks[i : i + EXPLAIN_BATCH_CHUNKS]
                for i in range(0, len(chunks), EXPLAIN_BATCH_CHUNKS)
            ]
            logger.info(
                f"'{req.source}' exceeds {EXPLAIN_MAX_CHUNKS} chunks - "
                f"summarizing in {len(batches)} batches first"
            )
            yield f"data: [STAGE]{json.dumps({'stage': 'summarizing_source'})}\n\n"

            summaries = []
            for i, batch in enumerate(batches):
                # Nobody is waiting on this any more, and a batch costs minutes
                if await request.is_disconnected():
                    logger.info(f"Explain for '{req.source}' abandoned - client disconnected")
                    return
                # Re-checked per batch - the pre-stream check is minutes stale by now
                if await asyncio.to_thread(find_active_job, req.source, USER_ID):
                    logger.info(f"Explain for '{req.source}' abandoned - source went in flight")
                    yield _sse_token(
                        "\n\nThis source changed while it was being explained, so the "
                        "explanation was stopped."
                    )
                    yield _sse_timing(t0)
                    yield "data: [DONE]\n\n"
                    return

                # Keep beating while the batch runs - a silent SSE looks like a hung one
                task = asyncio.create_task(
                    asyncio.to_thread(_summarize_batch, batch, req.source, i + 1, len(batches))
                )
                while True:
                    done, _ = await asyncio.wait({task}, timeout=EXPLAIN_HEARTBEAT_SECONDS)
                    if done:
                        break
                    yield "data: [HEARTBEAT]\n\n"
                try:
                    summaries.append(await task)
                except Exception as e:
                    # Raising here drops the connection with no [DONE], which reads as a hang
                    logger.error(f"Explain map step failed on batch {i + 1}: {e}")
                    yield _sse_token(f"\n\nCould not summarize part {i + 1} of this source: {e}")
                    yield _sse_timing(t0)
                    yield "data: [DONE]\n\n"
                    return
            context = "\n\n".join(summaries)
        else:
            context = _explain_context(chunks)

        prompt = build_explain_prompt(req.source, context, partial=oversized)

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        async for token in _aiter_answer(prompt, system=_EXPLAIN_SYSTEM_PROMPT):
            if token:
                yield _sse_token(token)

        # No chunks, but `sources` carries the name so the UI can label the message
        sources_payload = json.dumps({"sources": [req.source], "scores": [], "chunks": []})
        yield f"data: [SOURCES]{sources_payload}\n\n"
        yield _sse_timing(t0)
        yield "data: [DONE]\n\n"

        latency = time.perf_counter() - t0
        logger.info(f"Explain latency for '{req.source}': {latency:.2f}s (oversized={oversized})")
        send_telemetry(
            "query_explain",
            {
                "latency": round(latency, 2),
                "chunks": len(chunks),
                "oversized": oversized,
            },
        )

    return StreamingResponse(_with_query_priority(event_stream()), media_type="text/event-stream")


# -- Attachments -------------------------------------------------------------
# A saved attachment: (temp path, original filename, content-type, suffix). Per-turn only
_SavedAttachment = tuple[str, str, str, str]


def _extract_pdf_text(path: str) -> str:
    """Extract plain text from a PDF attachment via PyMuPDF (not Docling -
    attachments need a fast one-shot extraction, not the full ingestion pipeline)."""
    import fitz  # pymupdf is a heavy optional dependency - only load for PDF attachments

    doc = fitz.open(path)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return text[:ATTACHMENT_TEXT_MAX_CHARS]


def _read_text_attachment(path: str) -> str:
    """Read a plain text/markdown attachment, tolerating bad encoding from
    arbitrary user-supplied files."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return text[:ATTACHMENT_TEXT_MAX_CHARS]


def _process_one_attachment(saved_item: _SavedAttachment) -> dict:
    """Save one upload to a temp file and describe it for the answer prompt."""
    path, filename, content_type, suffix = saved_item
    try:
        if suffix in SUPPORTED_IMAGE_EXTENSIONS or content_type.startswith("image/"):
            description = describe_image(path, filename)
            return {
                "type": "image",
                "name": filename,
                "description": description,
                "block": f"[Attached image: {description}]",
            }
        elif suffix in SUPPORTED_PDF_EXTENSIONS or content_type == "application/pdf":
            text = _extract_pdf_text(path)
            return {
                "type": "pdf",
                "name": filename,
                "description": text,
                "block": f"[Attached PDF '{filename}': {text}]",
            }
        else:
            text = _read_text_attachment(path)
            return {
                "type": "text",
                "name": filename,
                "description": text,
                "block": f"[Attached text '{filename}': {text}]",
            }
    except Exception as e:
        logger.error(f"Failed to process attachment '{filename}': {e}")
        return {"type": "text", "name": filename, "description": "", "block": ""}


@router.post("/with_attachments")
async def query_with_attachments(
    request: Request,
    question: str = Form(...),
    history: str = Form("[]"),
    source_filter: str = Form(""),
    is_direct: str = Form("false"),
    attachments: list[UploadFile] | None = FastAPIFile(None),
) -> StreamingResponse:
    """Answer a question with per-turn file attachments, retrieval optional.

    Emits an extra [ATTACHMENTS] frame naming what was read.
    """
    t0 = time.perf_counter()
    history_list = json.loads(history) if history else []
    filter_list = json.loads(source_filter) if source_filter else None
    direct = is_direct.strip().lower() == "true"
    logger.info(f"Attachment query ({'direct' if direct else 'RAG'}): {question}")

    # UploadFile handles die with the request, and the generator runs after it returns
    saved: list[_SavedAttachment] = []
    for f in attachments or []:
        data = await f.read()
        suffix = Path(f.filename or "").suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
        saved.append((tmp.name, f.filename or "attachment", f.content_type or "", suffix))

    async def event_stream() -> AsyncGenerator[str, None]:
        history_str = format_history(history_list)

        try:
            results: list[dict] = []
            if saved:
                yield f"data: [STAGE]{json.dumps({'stage': 'processing_attachments'})}\n\n"
                for item in saved:
                    # Bail before each attachment - a vision call can run 30-50s
                    if await request.is_disconnected():
                        return
                    yield "data: [HEARTBEAT]\n\n"
                    results.append(await asyncio.to_thread(_process_one_attachment, item))
                attachments_payload = [
                    {"type": r["type"], "name": r["name"], "description": r["description"]}
                    for r in results
                ]
                yield f"data: [ATTACHMENTS]{json.dumps({'attachments': attachments_payload})}\n\n"

            if await request.is_disconnected():
                return

            attachment_context = "\n".join(r["block"] for r in results if r["block"])
            augmented_question = (
                f"{attachment_context}\n\n{question}" if attachment_context else question
            )

            if direct:
                prompt = build_direct_prompt(augmented_question, history_str)
                yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
                async for token in _aiter_answer(prompt):
                    if token:
                        yield _sse_token(token)
                yield f"data: [SOURCES]{json.dumps({'sources': [], 'scores': []})}\n\n"
            else:
                yield f"data: [STAGE]{json.dumps({'stage': 'retrieving_sources'})}\n\n"
                if has_graph(USER_ID):
                    yield f"data: [STAGE]{json.dumps({'stage': 'traversing_graph'})}\n\n"
                yield "data: [HEARTBEAT]\n\n"
                docs, metas = await asyncio.to_thread(
                    _pipeline.search_candidates,
                    query=augmented_question,
                    user_id=USER_ID,
                    source_filter=filter_list,
                )

                yield f"data: [STAGE]{json.dumps({'stage': 'reranking'})}\n\n"
                yield "data: [HEARTBEAT]\n\n"
                docs, metas, scores = await asyncio.to_thread(
                    _pipeline.rerank_candidates, augmented_question, docs, metas
                )

                context = build_context(docs, metas)
                sources = list({meta["source"] for meta in metas})
                chunks = [
                    {"source": meta["source"], "text": doc, "score": round(score, 3)}
                    for doc, meta, score in zip(docs, metas, scores)
                ]
                prompt = build_answer_prompt(augmented_question, context, history_str)

                yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
                async for token in _aiter_answer(prompt):
                    if token:
                        yield _sse_token(token)

                sources_payload = json.dumps(
                    {"sources": sources, "scores": scores, "chunks": chunks}
                )
                yield f"data: [SOURCES]{sources_payload}\n\n"

            yield _sse_timing(t0)
            yield "data: [DONE]\n\n"

            latency = time.perf_counter() - t0
            logger.info(f"Attachment query latency: {latency:.2f}s")
            send_telemetry(
                "query_attachments",
                {
                    "latency": round(latency, 2),
                    "question_len": len(question),
                    "attachment_count": len(saved),
                    "is_direct": direct,
                },
            )
        finally:
            for path, _, _, _ in saved:
                try:
                    os.remove(path)
                except OSError:
                    pass

    return StreamingResponse(_with_query_priority(event_stream()), media_type="text/event-stream")
