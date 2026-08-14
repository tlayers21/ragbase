from fastapi import APIRouter
from pydantic import BaseModel

from config.models import get_model
from utils.ollama_client import generate_stream
from utils.text import normalize_title

router = APIRouter(prefix="/title", tags=["title"])


class TitleRequest(BaseModel):
    message: str


@router.post("")
async def generate_title(req: TitleRequest):
    """Generate a short chat title from the first user message."""
    prompt = (
        "Write a 3-6 word title for a conversation that starts with this message. "
        "Reply in English with only the title, as plain words separated by single "
        "spaces. No punctuation, no quotes, no explanation:\n\n"
        f"{req.message[:200]}"
    )
    title = "".join(generate_stream(prompt, model=get_model("title")))
    return {"title": normalize_title(title)[:60]}
