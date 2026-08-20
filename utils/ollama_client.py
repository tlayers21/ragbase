import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ollama

from config.logging import setup_logging
from config.models import get_model, get_num_ctx
from config.settings import OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT_SECONDS

logger = setup_logging(__name__)

# Every Ollama call goes through this client - a bare ollama.chat() has no timeout
client = ollama.Client(timeout=OLLAMA_TIMEOUT_SECONDS)


def ctx_options(model: str) -> dict | None:
    """Ollama options carrying this model's context window, or None if it has none.

    Every generation call goes through this, so a model is only ever loaded at one
    window - asking for a second tears the runner down and reloads several GB.
    """
    num_ctx = get_num_ctx(model)
    return {"num_ctx": num_ctx} if num_ctx else None


# -- Response shape handling -------------------------------------------------
# ollama-python has changed its embeddings response type across versions
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
# Embedding is query-critical, so every call renews OLLAMA_KEEP_ALIVE residency
def embed(text: str) -> list[float]:
    """Embed text using the embedding model."""
    model = get_model("embed")
    response = client.embed(model=model, input=text, keep_alive=OLLAMA_KEEP_ALIVE)
    return _extract_single_embedding(response)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, returning embeddings in the same order.

    Tries one batch call and falls back to parallel single-item calls.
    """
    if not texts:
        return []

    model = get_model("embed")

    try:
        response = client.embed(model=model, input=texts, keep_alive=OLLAMA_KEEP_ALIVE)
        embeddings = _extract_batch_embeddings(response)
        if len(embeddings) == len(texts):
            return embeddings
    except Exception:
        logger.debug("Batch embed attempt failed, falling back to per-item embedding")

    embeddings = [None] * len(texts)

    def _single(i, txt):
        try:
            response = client.embed(model=model, input=txt, keep_alive=OLLAMA_KEEP_ALIVE)
            return _extract_single_embedding(response)
        except Exception as e:
            logger.error(f"embed_batch: single embed failed for idx={i}: {e}")
            return None

    max_workers = min(8, max(1, len(texts)))  # local Ollama saturates quickly
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


def warm(task: str, keep_alive: float | str = OLLAMA_KEEP_ALIVE) -> None:
    """Load the model for `task` into Ollama's memory at its configured num_ctx.

    Must warm at the same window the real calls request, or the first query pays
    a full reload instead of the cold start warmup exists to remove.
    """
    model = get_model(task)
    if task == "embed":
        client.embed(model=model, input="warmup", keep_alive=keep_alive)
    else:
        client.generate(model=model, prompt="hi", keep_alive=keep_alive, options=ctx_options(model))


def unload(task: str) -> None:
    """Evict the model for `task` from Ollama's memory immediately.

    Raises like any other Ollama call, so callers decide whether a failed unload
    matters.
    """
    model = get_model(task)
    if task == "embed":
        client.embed(model=model, input="", keep_alive=0)
    else:
        # Same window as warm(), so this addresses the runner that is actually loaded
        client.generate(model=model, prompt="", keep_alive=0, options=ctx_options(model))


def restore_query_models() -> None:
    """Unload the ingestion-only models, then re-warm the query-critical ones.

    Best-effort throughout: this runs in the ingestion worker's `finally`, and a
    failure here must not turn a successful job into a failed one.
    """
    for task in ("vision_simple", "summarize"):
        try:
            unload(task)
        except Exception as e:
            logger.warning(f"Could not unload '{task}' after ingestion: {e}")

    for task in ("embed", "answer"):
        try:
            warm(task)
        except Exception as e:
            logger.warning(f"Could not re-warm '{task}' after ingestion: {e}")

    # The only signal that the GPU was handed back
    logger.info("Query models restored after ingestion (ingestion models unloaded)")


def vision(image_path: str | Path, prompt: str, task: str = "vision_handwrite") -> str:
    """Describe or transcribe an image using a vision model."""
    model = get_model(task)
    logger.debug(f"vision | task={task} model={model}")
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": [image_data]}],
        options=ctx_options(model),
    )
    return response["message"]["content"]


def generate_stream(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    think: bool | None = None,
    keep_alive: float | str | None = None,
    options: dict | None = None,
):
    """Stream output tokens for UI responses.

    `think` is Ollama's reasoning toggle (None keeps the model default, False
    suppresses it); `keep_alive` and `options` are opt-in and default per model.
    """
    model = model or get_model("answer")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Forward only when set - think=None would override the model default, not defer
    kwargs = {} if think is None else {"think": think}
    if keep_alive is not None:
        kwargs["keep_alive"] = keep_alive
    # Defaulted so a new call site cannot silently inherit Ollama's 4096 and truncate
    resolved_options = options if options is not None else ctx_options(model)
    if resolved_options:
        kwargs["options"] = resolved_options
    for chunk in client.chat(model=model, messages=messages, stream=True, **kwargs):
        yield chunk["message"]["content"]
