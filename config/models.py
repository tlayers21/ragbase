from config.settings import NUM_CTX_FAST, NUM_CTX_STANDARD, NUM_CTX_VISION

# -- Model names ---------------------------------------------------------------
MODEL_STANDARD = "qwen3"  # Standard reasoning and answer generation
MODEL_FAST = "qwen2.5:3b"  # Fast model for fact-check, contradiction, classification
MODEL_VISION_HEAVY = "qwen2.5vl"  # Handwriting, complex diagrams
MODEL_VISION_FAST = "qwen2.5vl"  # Simple image classification
MODEL_EMBED = "bge-m3"  # Embedding


# -- Model routing -------------------------------------------------------------
def get_model(task: str) -> str:
    """Return the appropriate model name for a given task."""
    routing = {
        "answer": MODEL_STANDARD,
        "query_rewrite": MODEL_STANDARD,
        "fact_check": MODEL_FAST,
        "contradiction": MODEL_FAST,
        "summarize": MODEL_FAST,
        "text_cleanup": MODEL_FAST,
        "title": MODEL_FAST,
        "entity_extraction": MODEL_FAST,
        "vision_handwrite": MODEL_VISION_HEAVY,
        "vision_diagram": MODEL_VISION_HEAVY,
        "vision_simple": MODEL_VISION_FAST,
        "embed": MODEL_EMBED,
    }
    if task not in routing:
        raise ValueError(f"Unknown task '{task}'. Valid tasks: {list(routing.keys())}")
    return routing[task]


# -- Context windows -----------------------------------------------------------
# Keyed by model, not task - two tasks sharing a model must share its window
_NUM_CTX = {
    MODEL_STANDARD: NUM_CTX_STANDARD,
    MODEL_FAST: NUM_CTX_FAST,
    MODEL_VISION_HEAVY: NUM_CTX_VISION,
    MODEL_VISION_FAST: NUM_CTX_VISION,
}


def get_num_ctx(model: str) -> int | None:
    """Context window for a model, or None to let Ollama pick.

    None is correct only for the embedding model; unknown models return None rather than
    raising, so an ml/ script naming a model directly still runs.
    """
    return _NUM_CTX.get(model)
