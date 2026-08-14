import asyncio
import json
import os
import tempfile
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model
from config.runtime import USER_ID, query_finished, query_started
from config.settings import (
    ANSWER_THINKING_ENABLED,
    ATTACHMENT_TEXT_MAX_CHARS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_PDF_EXTENSIONS,
)
from ingestion.helpers import describe_image
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
    "Never cite source document names inline in your response. "
    "Never reference 'the context', 'the provided context', 'retrieved documents', "
    "'the examples', 'the text', or any phrase that narrates where your information came from. "
    "Weave all information naturally into your answer as if it were already known."
)


def _answer_stream(prompt: str) -> Generator[str, None, None]:
    """
    The single entry point for every user-facing answer.

    All six generation call sites in this module previously repeated
    `system=_SYSTEM_PROMPT, model=get_model("answer")`; funnelling them through
    here means the thinking toggle can't be applied to five of them and forgotten
    on the sixth.
    """
    return generate_stream(
        prompt,
        system=_SYSTEM_PROMPT,
        model=get_model("answer"),
        think=ANSWER_THINKING_ENABLED,
    )


async def _aiter_answer(prompt: str) -> AsyncGenerator[str, None]:
    """
    Pump `_answer_stream` without holding the event loop for the whole answer.

    `generate_stream` is a *blocking* generator, so `for token in _answer_stream(...)`
    inside an `async def` never gives the loop a chance to run between tokens: no
    frame reaches the client until generation finishes (the answer lands in one
    burst instead of streaming) and every other in-flight SSE stream stalls behind
    it. One `to_thread` per `next()` restores both. The sync `/query/direct`
    generator does not need this — Starlette already iterates it in a threadpool.
    """
    gen = _answer_stream(prompt)
    sentinel = object()
    while True:
        # Sequential awaits, so the generator is only ever advanced by one thread
        # at a time even though the pool may hand out a different one each call.
        token = await asyncio.to_thread(next, gen, sentinel)
        if token is sentinel:
            return
        yield token


def _sse_token(token: str) -> str:
    """Frame one model token as an SSE event.

    The token is JSON-encoded because SSE frames are delimited by a blank line and
    answers are markdown: a raw ``\\n`` inside ``data: {token}\\n\\n`` collides with
    that delimiter, so every newline token was silently swallowed and lists,
    paragraphs and headings all collapsed onto one line. JSON escapes newlines to
    ``\\n`` literals, so whitespace survives the wire intact. Control frames keep
    their bare ``[MARKER]`` prefix, which stays unambiguous because a JSON-encoded
    token always starts with a quote.
    """
    return f"data: {json.dumps(token)}\n\n"


async def _with_query_priority(
    stream: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """
    Flag the process as serving a query for as long as `stream` is producing.

    The knowledge-graph worker polls this flag between entity extractions and
    pauses while it is set, so a build in progress stops competing with the query
    the user is actually waiting on (see retrieval/graph.py::_yield_to_queries).

    Wrapping the generator rather than setting the flag in the endpoint is what
    makes the clear reliable: the ``finally`` runs when the stream completes, when
    it raises, and when the client disconnects and Starlette closes the generator.
    """
    query_started()
    try:
        async for frame in stream:
            yield frame
    finally:
        query_finished()


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
    t0 = time.time()
    logger.info(f"Query: {req.question}")

    query_embedding = embed(req.question)
    cached = get_cached_response(USER_ID, query_embedding)

    if cached:
        # Cache hit: reuse retrieved context, generate a fresh answer for the new question.
        history_str = format_history(req.history)
        prompt = build_answer_prompt(req.question, cached["context"], history_str)
        answer = "".join(_answer_stream(prompt))
        latency = time.time() - t0
        logger.info(f"Cache hit — response in {latency:.2f}s")
        send_telemetry(
            "query_rag",
            {"latency": round(latency, 2), "question_len": len(req.question), "cache_hit": True},
        )
        return QueryResponse(answer=answer, sources=cached["sources"], scores=cached["scores"])

    # Cache miss: run full retrieval, then generate answer via generate_stream.
    retrieval = _pipeline.retrieve_context(
        question=req.question,
        user_id=USER_ID,
        history=req.history,
        source_filter=req.source_filter,
    )
    prompt = build_answer_prompt(req.question, retrieval["context"], retrieval["history_str"])
    answer = "".join(_answer_stream(prompt))

    set_cached_response(
        USER_ID,
        query_embedding,
        {
            "context": retrieval["context"],
            "sources": retrieval["sources"],
            "scores": retrieval["scores"],
        },
    )

    latency = time.time() - t0
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
    """
    Same retrieval as /query, but streams progress and the answer as
    Server-Sent Events. `data: [STAGE]{"stage": ...}\\n\\n` events mark
    retrieval/reranking/generation as they begin, followed by token events
    (`data: {json-encoded token}\\n\\n`), a `data: [SOURCES]{json}\\n\\n` citation event,
    and `data: [DONE]\\n\\n`. `data: [HEARTBEAT]\\n\\n` keep-alive events are
    emitted before each blocking call so the connection does not time out.
    """
    t0 = time.time()
    logger.info(f"Streaming query: {req.question}")

    async def event_stream() -> AsyncGenerator[str, None]:
        history_str = format_history(req.history)

        yield f"data: [STAGE]{json.dumps({'stage': 'retrieving_sources'})}\n\n"

        # The semantic cache is keyed on the query embedding, so a paraphrase of an
        # earlier question reuses its retrieval and skips stages 1-4 entirely. Only
        # the retrieval context is reused — the answer is always regenerated against
        # the wording actually asked. Source-filtered queries bypass the cache: the
        # cached context was built under a different filter and would leak chunks
        # from sources the user has deselected.
        cached = None
        if not req.source_filter:
            query_embedding = await asyncio.to_thread(embed, req.question)
            cached = await asyncio.to_thread(get_cached_response, USER_ID, query_embedding)

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

            if not req.source_filter:
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

        logger.info("Emitting [STAGE] generating")
        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        async for token in _aiter_answer(prompt):
            if token:
                yield _sse_token(token)

        sources_payload = json.dumps({"sources": sources, "scores": scores, "chunks": chunks})
        yield f"data: [SOURCES]{sources_payload}\n\n"
        yield "data: [DONE]\n\n"

        latency = time.time() - t0
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
    """
    Bypass the RAG pipeline entirely — no retrieval, reranking, or ChromaDB
    queries. Sends the question straight to generate_stream() with qwen3.
    Used when the user has deselected all sources ("direct LLM mode"), so
    the response feels near-instant compared to the full pipeline. Same SSE
    event format as /query/stream (no [STAGE] events, empty [SOURCES]).
    """
    t0 = time.time()
    logger.info(f"Direct query (no RAG): {req.question}")

    def event_stream() -> Generator[str, None, None]:
        history_str = format_history(req.history)
        prompt = build_direct_prompt(req.question, history_str)

        yield f"data: [STAGE]{json.dumps({'stage': 'generating'})}\n\n"
        for token in _answer_stream(prompt):
            if token:
                yield _sse_token(token)

        yield f"data: [SOURCES]{json.dumps({'sources': [], 'scores': []})}\n\n"
        yield "data: [DONE]\n\n"

        latency = time.time() - t0
        logger.info(f"Direct query latency: {latency:.2f}s")
        send_telemetry(
            "query_direct",
            {"latency": round(latency, 2), "question_len": len(req.question)},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# -- Attachments -------------------------------------------------------------
# A saved attachment: (temp file path, original filename, content-type, suffix).
# Attachments are per-turn context only — never ingested into ChromaDB, so
# they don't need chunking/embedding, just a text description per file.
_SavedAttachment = tuple[str, str, str, str]


def _extract_pdf_text(path: str) -> str:
    """Extract plain text from a PDF attachment via PyMuPDF (not Docling —
    attachments need a fast one-shot extraction, not the full ingestion pipeline)."""
    import fitz  # pymupdf is a heavy optional dependency — only load for PDF attachments

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
    """
    Process a single saved attachment into a {type, name, description, block} dict.
    `block` is the "[Attached ...]" string prepended to the question; `description`
    is the bare text stored on the message so follow-up turns retain the context.
    Split out from the old batch version so the caller can check for client
    disconnects between attachments instead of blocking on the whole batch.
    """
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
    """
    Same SSE contract as /query/stream and /query/direct, but accepts multipart
    file attachments (images, PDFs, text files) as extra per-turn context.

    Attachments are processed up front (vision description / text extraction),
    emitted as a `data: [ATTACHMENTS]{json}\\n\\n` event, then prepended to the
    question before retrieval/generation. They are never stored as a retrievable
    source — this is inline context for this conversation only, not ingestion.
    """
    t0 = time.time()
    history_list = json.loads(history) if history else []
    filter_list = json.loads(source_filter) if source_filter else None
    direct = is_direct.strip().lower() == "true"
    logger.info(f"Attachment query ({'direct' if direct else 'RAG'}): {question}")

    # UploadFile handles are only valid within this request; read + persist to
    # temp files now, before the streaming generator (which runs after the
    # response is returned) needs them.
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
                    # Bail before each attachment (vision calls can run 30-50s+) so a
                    # client that already clicked stop doesn't keep the pipeline busy.
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

            yield "data: [DONE]\n\n"

            latency = time.time() - t0
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
