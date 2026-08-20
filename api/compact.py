import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model
from utils.ollama_client import client as ollama_client
from utils.ollama_client import ctx_options

logger = setup_logging(__name__)
router = APIRouter(prefix="/compact", tags=["compact"])


class CompactRequest(BaseModel):
    messages: list[dict]


@router.post("")
async def compact_messages(req: CompactRequest):
    """Summarize a list of messages for context compression."""
    if not req.messages:
        return {"summary": ""}

    conversation = "\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
        for m in req.messages
        if m.get("content") and m.get("role") != "system"
    )
    if not conversation.strip():
        return {"summary": ""}

    prompt = (
        "Summarize this conversation segment concisely in 2-3 paragraphs, "
        "preserving all key facts, decisions, questions asked, and answers given.\n\n"
        f"{conversation}"
    )
    model = get_model("summarize")

    # This module is the one documented exception to "all Ollama traffic goes
    # through utils/ollama_client.py" - it needs a single blocking completion
    # rather than a stream. It still borrows that module's *client* and its
    # context-window lookup, so it inherits OLLAMA_TIMEOUT_SECONDS and the model's
    # num_ctx instead of ollama-python's unbounded timeout and Ollama's 4096.
    #
    # The window matters more here than anywhere: compaction runs precisely because
    # a conversation is near the context limit, so this prompt is the largest the
    # app ever builds. At 4096 it would summarize the opening of a conversation and
    # silently drop the rest - losing exactly the history it was asked to preserve.
    def _call() -> str:
        response = ollama_client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options=ctx_options(model),
        )
        return response["message"]["content"]

    summary = await asyncio.to_thread(_call)
    logger.info(f"Compacted {len(req.messages)} messages")
    return {"summary": summary.strip()}
