import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config.logging import setup_logging

logger = setup_logging(__name__)

MODEL_NAME = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 512  # BGE-Reranker-v2-m3 supports up to 512 tokens


# -- Singleton loader ------------------------------------------------------
_model = None
_tokenizer = None


def _load():
    """Load the BGE-Reranker-v2-m3 model and tokenizer once, reuse on every call.

    This is a base model loaded directly from HuggingFace — no trained checkpoint
    needed. BGE-Reranker-v2-m3 loads cleanly in float32 with no NaN issues
    (confirmed via direct testing: logits=[7.79], no NaN, dtype=float32).
    """
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    logger.info(f"Loading reranker model '{MODEL_NAME}'...")
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)

    device = (
        "mps"
        if torch.backends.mps.is_available()
        else "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )
    _model = _model.to(device)
    _model.eval()
    logger.info(f"Reranker loaded on {device}")
    return _model, _tokenizer


# -- Public API ------------------------------------------------------------
def rerank(
    question: str,
    docs: list[str],
    metas: list[dict],
    top_k: int = 5,
) -> tuple[list[str], list[dict], list[float]]:
    """
    Rerank retrieved chunks using BGE-Reranker-v2-m3 cross-encoder.

    Scores each (question, chunk) pair and returns the top_k results sorted
    by relevance score descending. Uses pure top-k ranking — no absolute
    threshold, since raw cross-encoder scores are not calibrated to a fixed
    cutoff, only relative ordering is meaningful.

    Falls back to original order if loading fails.
    """
    if not docs:
        return [], [], []

    try:
        model, tokenizer = _load()
    except Exception as e:
        logger.warning(f"Reranker failed to load: {e} — returning original order")
        return docs[:top_k], metas[:top_k], [1.0] * min(top_k, len(docs))

    device = next(model.parameters()).device
    pairs = [(question, doc) for doc in docs]

    with torch.no_grad():
        try:
            encoded = tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            encoded = {k: v.to(device) for k, v in encoded.items()}
            output = model(**encoded)
            scores = output.logits.squeeze(-1).float().tolist()
            if isinstance(scores, float):  # squeeze collapses a single pair to a scalar
                scores = [scores]
        except Exception as e:
            logger.warning(f"Batch reranking failed ({e}), falling back to per-item loop")
            scores = []
            for _, doc in pairs:
                encoded = tokenizer(
                    question,
                    doc,
                    max_length=MAX_LENGTH,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                )
                encoded = {k: v.to(device) for k, v in encoded.items()}
                output = model(**encoded)
                scores.append(output.logits.squeeze(-1).float().item())

    ranked = sorted(
        zip(scores, docs, metas),
        key=lambda x: x[0],
        reverse=True,
    )

    top = ranked[:top_k]
    result_scores = [s for s, _, _ in top]
    result_docs = [d for _, d, _ in top]
    result_metas = [m for _, _, m in top]

    logger.debug(
        f"Reranked {len(docs)} chunks → top {len(top)}, "
        f"score range [{min(scores):.2f}, {max(scores):.2f}]"
    )
    return result_docs, result_metas, result_scores
