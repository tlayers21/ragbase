import asyncio

import ollama
from fastapi import APIRouter
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model

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

    def _call() -> str:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]

    summary = await asyncio.to_thread(_call)
    logger.info(f"Compacted {len(req.messages)} messages")
    return {"summary": summary.strip()}
