import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ollama

from config.logging import setup_logging
from config.models import get_model
from config.settings import OLLAMA_KEEP_ALIVE, OLLAMA_VISION_NUM_CTX

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
# The embedding model is query-critical, so every call here renews the long
# residency set by OLLAMA_KEEP_ALIVE rather than Ollama's 5-minute default.
# Ingestion embeds too, but it is the *same* model either way - there is no
# version of this worth letting expire between a warmup and the first question.
def embed(text: str) -> list[float]:
    """Embed text using the embedding model."""
    model = get_model("embed")
    response = ollama.embed(model=model, input=text, keep_alive=OLLAMA_KEEP_ALIVE)
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
        response = ollama.embed(model=model, input=texts, keep_alive=OLLAMA_KEEP_ALIVE)
        embeddings = _extract_batch_embeddings(response)
        if len(embeddings) == len(texts):
            return embeddings
    except Exception:
        logger.debug("Batch embed attempt failed, falling back to per-item embedding")

    # Fallback: parallel per-item embedding
    embeddings = [None] * len(texts)

    def _single(i, txt):
        try:
            response = ollama.embed(model=model, input=txt, keep_alive=OLLAMA_KEEP_ALIVE)
            return _extract_single_embedding(response)
        except Exception as e:
            logger.error(f"embed_batch: single embed failed for idx={i}: {e}")
            return None

    # Limit threads so we don't overwhelm the local model
    max_workers = min(8, max(1, len(texts)))  # cap threads - local Ollama saturates quickly
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
    """
    Load the model for `task` into Ollama's memory (startup warmup).

    Embedding models can't answer a generate call, so the task picks the
    endpoint. Lives here rather than in main.py so every Ollama call in the app
    still goes through one module.

    `keep_alive` defaults to the long query-critical residency because every
    caller is now a WARMUP_CRITICAL_TASKS entry: warming a model under Ollama's
    5-minute default just means it has expired again before the user's first
    question, which is the whole failure this was meant to prevent.
    """
    model = get_model(task)
    if task == "embed":
        ollama.embed(model=model, input="warmup", keep_alive=keep_alive)
    else:
        ollama.generate(model=model, prompt="hi", keep_alive=keep_alive)


def unload(task: str) -> None:
    """
    Evict the model for `task` from Ollama's memory immediately.

    `keep_alive=0` is Ollama's documented "unload now" (see .ai/docs/ollama.md).
    Two callers: the shutdown hook in main.py, which returns the several GB the
    query models hold rather than leaving them pinned for the rest of the TTL,
    and the ingestion vision path, which hands its runner slot back so a
    following fast-model call doesn't push Ollama over its runner budget and
    evict a query model to make room.

    Raises like any other Ollama call - callers decide whether a failed unload
    matters. It never does on shutdown; the finite TTL is the backstop.
    """
    model = get_model(task)
    if task == "embed":
        ollama.embed(model=model, input="", keep_alive=0)
    else:
        ollama.generate(model=model, prompt="", keep_alive=0)


def restore_query_models() -> None:
    """
    Give the GPU back to queries after an ingestion job.

    Called from the ingestion worker once a job is completely finished. It does
    two things, in order: unloads the ingestion-only models, then reloads the
    query-critical ones under their long residency.

    **Why this exists rather than serializing the ingestion calls.** The obvious
    reading is that ingestion evicts a query model by asking for a fourth runner
    (Ollama allows three), so keeping ingestion to one model at a time would fix
    it. Measured on the M3 (2026-08-16), that is not what happens. The ingestion
    calls are already strictly sequential - `ImageIngestor.extract_text` runs
    OCR, then vision, then fusion with no concurrency anywhere - and `ollama ps`
    through an image ingest showed the resident set going:

        [bge-m3, qwen3] -> [] -> [qwen2.5vl] -> [bge-m3, qwen2.5vl]
                              -> [bge-m3, qwen2.5:3b, qwen2.5vl]

    Both query models were evicted at the *second* step, when qwen2.5vl alone was
    loading. qwen2.5vl needs 7.3GB at OLLAMA_VISION_NUM_CTX and simply does not
    fit beside qwen3 in Ollama's Metal budget on 24GB, so it displaces whatever
    is resident no matter what order the calls are made in. Ordering cannot fix
    a capacity problem, and `keep_alive` never protected against eviction under
    pressure - only against idle expiry.

    What *is* fixable is the state the machine is left in. Pre-fix, a job ended
    with [bge-m3, qwen2.5:3b, qwen2.5vl] resident and the answer model gone, so
    the next question paid a full cold load - the original "first query is slow"
    symptom, reached through ingestion instead of through startup. Unloading the
    ingestion models frees that space, and re-warming moves the reload onto this
    worker thread, where nobody is waiting on it.

    Best-effort throughout: this runs in the worker's `finally`, and a failure
    here must not turn a successful ingestion into a failed job.
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

    # Logged because this is the only signal that the GPU was handed back. A
    # silent no-op here looks identical to the pre-fix behaviour, where the next
    # query paid a cold load and nothing said why.
    logger.info("Query models restored after ingestion (ingestion models unloaded)")


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
    keep_alive: float | str | None = None,
):
    """
    Stream output tokens for UI responses.

    `think` is Ollama's thinking toggle for reasoning models like qwen3. Leave it
    None to keep the model's default; pass False to suppress the reasoning pass
    entirely. Do *not* try to do this by putting `/no_think` in the prompt - that
    soft switch is not honored here and the literal text only confuses the model
    (see section 8 of `.ai/instructions.md`).

    `keep_alive` is **opt-in**, unlike `embed()`. Most callers here are
    ingestion-only tasks (summarize, title, fact_check, ...), and pinning those
    would spend a runner slot Ollama needs for the query models: the budget is 3,
    embed and the answer model hold two of them, and anything ingestion keeps
    resident competes for the last one. Leaving them on Ollama's 5-minute default
    means they release it on their own. `api/query.py::_answer_stream` passes
    OLLAMA_KEEP_ALIVE because the answer model *is* query-critical.
    """
    model = model or get_model("answer")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Only forward each option when explicitly set - sending think=None or
    # keep_alive=None would override the model's own default rather than defer
    # to it.
    kwargs = {} if think is None else {"think": think}
    if keep_alive is not None:
        kwargs["keep_alive"] = keep_alive
    for chunk in ollama.chat(model=model, messages=messages, stream=True, **kwargs):
        yield chunk["message"]["content"]
