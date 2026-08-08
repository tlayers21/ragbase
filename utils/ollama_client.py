import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ollama

from config.logging import setup_logging
from config.models import get_model
from config.settings import OLLAMA_VISION_NUM_CTX

logger = setup_logging(__name__)


# -- Response shape handling -------------------------------------------------
# ollama-python has changed its embeddings response type across versions
# (typed object, dict, or bare list). These extractors accept every known
# shape so an Ollama upgrade doesn't silently break embedding.
def _extract_single_embedding(response) -> list[float]:
    """Extract one embedding vector from Ollama response shapes."""
    if hasattr(response, "embedding"):
        return list(response.embedding)

    if isinstance(response, dict):
        if "embedding" in response:
            return response["embedding"]
        if "embeddings" in response and response["embeddings"]:
            return response["embeddings"][0]

    if hasattr(response, "embeddings"):
        embeddings = getattr(response, "embeddings")
        if embeddings:
            return list(embeddings[0])

    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict) and "embedding" in first:
            return first["embedding"]
        return first

    raise RuntimeError("Unexpected response from ollama.embeddings")


def _extract_batch_embeddings(response) -> list[list[float]]:
    """Extract batch embeddings from Ollama response shapes."""
    if hasattr(response, "embeddings"):
        return [list(emb) for emb in response.embeddings]

    if isinstance(response, dict):
        if "embeddings" in response:
            return response["embeddings"]
        if "embedding" in response:
            return [response["embedding"]]

    if isinstance(response, list):
        embeddings = []
        for item in response:
            if isinstance(item, dict) and "embedding" in item:
                embeddings.append(item["embedding"])
            else:
                embeddings.append(item)
        return embeddings

    return []


# -- Public API --------------------------------------------------------------
def embed(text: str) -> list[float]:
    """Embed text using the embedding model."""
    model = get_model("embed")
    response = ollama.embed(model=model, input=text)
    return _extract_single_embedding(response)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts. Try a single batch call to Ollama first; if that
    fails, fall back to parallel single-item calls.

    Returns a list of embeddings in the same order as `texts`.
    """
    if not texts:
        return []

    model = get_model("embed")

    # Try one-shot batch call
    try:
        response = ollama.embed(model=model, input=texts)
        embeddings = _extract_batch_embeddings(response)
        if len(embeddings) == len(texts):
            return embeddings
    except Exception:
        logger.debug("Batch embed attempt failed, falling back to per-item embedding")

    # Fallback: parallel per-item embedding
    embeddings = [None] * len(texts)

    def _single(i, txt):
        try:
            response = ollama.embed(model=model, input=txt)
            return _extract_single_embedding(response)
        except Exception as e:
            logger.error(f"embed_batch: single embed failed for idx={i}: {e}")
            return None

    # Limit threads so we don't overwhelm the local model
    max_workers = min(8, max(1, len(texts)))  # cap threads — local Ollama saturates quickly
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_single, i, t): i for i, t in enumerate(texts)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                embeddings[idx] = fut.result()
            except Exception as e:
                logger.error(f"embed_batch: unexpected error for idx={idx}: {e}")
                embeddings[idx] = None

    return embeddings


def vision(image_path: str | Path, prompt: str, task: str = "vision_handwrite") -> str:
    """Describe or transcribe an image using a vision model."""
    model = get_model(task)
    logger.debug(f"vision | task={task} model={model}")
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": [image_data]}],
        options={"num_ctx": OLLAMA_VISION_NUM_CTX},
    )
    return response["message"]["content"]


def generate_stream(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    think: bool | None = None,
):
    """
    Stream output tokens for UI responses.

    `think` is Ollama's thinking toggle for reasoning models like qwen3. Leave it
    None to keep the model's default; pass False to suppress the reasoning pass
    entirely. Do *not* try to do this by putting `/no_think` in the prompt — that
    soft switch is not honored here and the literal text only confuses the model
    (see §8 of `.ai/instructions.md`).
    """
    model = model or get_model("answer")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Only forward the option when explicitly set — sending think=None would
    # override the model's own default rather than defer to it.
    kwargs = {} if think is None else {"think": think}
    for chunk in ollama.chat(model=model, messages=messages, stream=True, **kwargs):
        yield chunk["message"]["content"]
