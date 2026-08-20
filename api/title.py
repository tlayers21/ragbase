import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.logging import setup_logging
from config.models import get_model
from utils.ollama_client import generate_stream
from utils.text import normalize_title

logger = setup_logging(__name__)
router = APIRouter(prefix="/title", tags=["title"])


def _generate(prompt: str) -> str:
    """Blocking title generation, kept module-level so tests can patch it."""
    return "".join(generate_stream(prompt, model=get_model("title")))


async def build_title(instruction: str, text: str, max_chars: int, clip: int | None = None) -> str:
    """Generate one normalized title, raising 500 if the model call fails.

    An empty title is a real answer and stays a 200, so a caller can tell a model that
    returned nothing from one that could not be reached.
    """
    prompt = (
        f"{instruction} "
        "Reply in English with only the title, as plain words separated by single "
        "spaces. No punctuation, no quotes.\n\n"
        f"{text[:max_chars]}"
    )
    try:
        # to_thread - this runs concurrently with the first /query/stream of a new chat
        raw = await asyncio.to_thread(_generate, prompt)
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Title generation failed: {e}") from e
    title = normalize_title(raw.strip())
    return title[:clip] if clip else title


class TitleRequest(BaseModel):
    message: str


@router.post("")
async def generate_title(req: TitleRequest):
    """Generate a short chat title from the first user message."""
    title = await build_title(
        "Write a 3-6 word title for a conversation that starts with this message.",
        req.message,
        max_chars=200,
        clip=60,
    )
    return {"title": title}
