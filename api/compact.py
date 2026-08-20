import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model
from config.settings import COMPACT_MAX_INPUT_TOKENS
from utils.ollama_client import client as ollama_client
from utils.ollama_client import ctx_options

logger = setup_logging(__name__)
router = APIRouter(prefix="/compact", tags=["compact"])

_MAP_INSTRUCTION = (
    "Summarize this conversation segment concisely, preserving all key facts, "
    "decisions, questions asked, and answers given.\n\n"
)
_REDUCE_INSTRUCTION = (
    "Combine these summaries of consecutive parts of one conversation into a single "
    "coherent summary in 2-3 paragraphs, preserving all key facts, decisions, "
    "questions asked, and answers given.\n\n"
)


class CompactRequest(BaseModel):
    messages: list[dict]


def _estimate_tokens(text: str) -> int:
    """Rough token count for budgeting, on the same chars/4 basis as the frontend."""
    return len(text) // 4


def _render(msg: dict) -> str:
    """Render one message as a labelled transcript line, or "" if it carries no text."""
    content = (msg.get("content") or "").strip()
    if not content:
        return ""
    role = msg.get("role", "user")
    label = "EARLIER SUMMARY" if role == "system" else role.upper()
    return f"{label}: {content}"


def _batch(lines: list[str], budget: int) -> list[list[str]]:
    """Group transcript lines into batches that each stay under `budget` tokens.

    A single line over budget is truncated rather than sent whole, because an
    oversized prompt loses its instruction to Ollama's head-first truncation.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    spent = 0
    for line in lines:
        if _estimate_tokens(line) > budget:
            line = line[: budget * 4]
        cost = _estimate_tokens(line)
        if current and spent + cost > budget:
            batches.append(current)
            current, spent = [], 0
        current.append(line)
        spent += cost
    if current:
        batches.append(current)
    return batches


def _complete(prompt: str, model: str) -> str:
    """One blocking completion on the fast model."""
    response = ollama_client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options=ctx_options(model),
    )
    return response["message"]["content"].strip()


def _compact(lines: list[str], model: str) -> str:
    """Summarize a transcript, mapping over batches and reducing when it is oversized.

    Batching is what keeps the instruction intact: crossing the model's window makes
    Ollama truncate the prompt from the head, which discards the instruction itself.
    """
    budget = COMPACT_MAX_INPUT_TOKENS - _estimate_tokens(_MAP_INSTRUCTION)
    batches = _batch(lines, budget)
    if len(batches) == 1:
        return _complete(_MAP_INSTRUCTION + "\n".join(batches[0]), model)

    logger.info(f"Compaction input is oversized - summarizing in {len(batches)} batches")
    summaries = [_complete(_MAP_INSTRUCTION + "\n".join(b), model) for b in batches]

    reduce_input = [s for s in summaries if s]
    while _estimate_tokens("\n\n".join(reduce_input)) > budget and len(reduce_input) > 1:
        reduce_input = [
            _complete(_REDUCE_INSTRUCTION + "\n\n".join(b), model)
            for b in _batch(reduce_input, budget)
        ]
    return _complete(_REDUCE_INSTRUCTION + "\n\n".join(reduce_input), model)


@router.post("")
async def compact_messages(req: CompactRequest):
    """Summarize a list of messages for context compression."""
    if not req.messages:
        return {"summary": ""}

    # Prior summaries are kept - dropping them loses every earlier compaction
    lines = [line for line in (_render(m) for m in req.messages) if line]
    if not lines:
        return {"summary": ""}

    model = get_model("summarize")
    estimated = _estimate_tokens("\n".join(lines))
    summary = await asyncio.to_thread(_compact, lines, model)
    logger.info(
        f"Compacted {len(req.messages)} messages "
        f"(~{estimated} tokens in, ~{_estimate_tokens(summary)} out)"
    )
    return {"summary": summary.strip()}
