import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config.logging import setup_logging
from config.settings import MAX_FINAL_RESULTS

logger = setup_logging(__name__)

MODEL_NAME = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 512  # BGE-Reranker-v2-m3 supports up to 512 tokens


# -- Singleton loader ------------------------------------------------------
_model = None
_tokenizer = None


def _load():
    """Load the BGE-Reranker-v2-m3 model and tokenizer once, reusing them on every call.

    A base model straight from HuggingFace, loaded in float32.
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
def warm_reranker() -> None:
    """Load the cross-encoder and run one real forward pass, letting failures propagate.

    Warmup needs the opposite behaviour to `rerank()`, which swallows a load failure and
    would report success for a reranker that never loaded.
    """
    model, tokenizer = _load()
    with torch.no_grad():
        encoded = tokenizer(
            [("warmup", "warmup")],
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        device = next(model.parameters()).device
        model(**{k: v.to(device) for k, v in encoded.items()})


def rerank(
    question: str,
    docs: list[str],
    metas: list[dict],
    top_k: int = MAX_FINAL_RESULTS,
) -> tuple[list[str], list[dict], list[float]]:
    """Rerank chunks with the BGE cross-encoder and return the top_k by relevance.

    Pure top-k with no absolute threshold, and falls back to the original order if loading
    fails.
    """
    if not docs:
        return [], [], []

    try:
        model, tokenizer = _load()
    except Exception as e:
        logger.warning(f"Reranker failed to load: {e} - returning original order")
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
        f"Reranked {len(docs)} chunks -> top {len(top)}, "
        f"score range [{min(scores):.2f}, {max(scores):.2f}]"
    )
    return result_docs, result_metas, result_scores
