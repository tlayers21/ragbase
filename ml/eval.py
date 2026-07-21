import argparse
import json
from pathlib import Path
from typing import Any

import wandb
from config.logging import setup_logging
from config.models import get_model
from config.paths import EVAL_SET_PATH
from config.settings import OLLAMA_URL, WANDB_PROJECT
from ml.common import to_chunk_index
from retrieval.pipeline import RAGPipeline, configure_dspy

logger = setup_logging(__name__)


def _load_eval_set(path: Path) -> list[dict[str, Any]]:
    """Load eval examples from disk."""
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected list in eval file: {path}")
    if not data:
        raise ValueError(f"Eval file is empty: {path}")
    return data


def _retrieve_metas(
    pipeline: RAGPipeline,
    question: str,
    user_id: str,
) -> list[dict[str, Any]]:
    """
    Run retrieval exactly through the live DSPy pipeline path and return chunk metadatas.
    """
    rewritten_query = pipeline.rewriter(question=question, history="").rewritten_query
    _, metas, _ = pipeline._retrieve(
        query=rewritten_query,
        original_question=question,
        user_id=user_id,
        source_filter=None,
    )
    return metas


def run_eval(
    run_name: str = "retrieval_eval",
    eval_file: Path = EVAL_SET_PATH,
    user_id: str = "test_user",
    top_k: int = 5,
) -> tuple[float, float]:
    """
    Evaluate retrieval quality with top-k accuracy and MRR on eval_set.json.
    """
    examples = _load_eval_set(eval_file)
    pipeline = RAGPipeline()

    logger.info(f"Running retrieval eval on {len(examples)} questions from {eval_file}")

    hits = 0
    reciprocal_ranks: list[float] = []

    for i, item in enumerate(examples, start=1):
        question = item["question"]
        expected_source = item["source"]
        expected_chunk_index = to_chunk_index(item.get("correct_chunk_index"))

        metas = _retrieve_metas(pipeline, question, user_id)[:top_k]

        rank: int | None = None
        for j, meta in enumerate(metas, start=1):
            retrieved_source = meta.get("source")
            retrieved_chunk_index = to_chunk_index(meta.get("chunk_index"))
            if (
                retrieved_source == expected_source
                and retrieved_chunk_index == expected_chunk_index
            ):
                rank = j
                break

        hit = rank is not None
        if hit:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

        logger.info(
            f"Q{i}/{len(examples)} {'HIT' if hit else 'MISS'} "
            f"(source={expected_source}, chunk={expected_chunk_index})"
        )

    accuracy = hits / len(examples)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)

    logger.info(f"Top-{top_k} accuracy: {accuracy:.1%} ({hits}/{len(examples)})")
    logger.info(f"MRR: {mrr:.3f}")

    wandb.init(project=WANDB_PROJECT, name=run_name)
    wandb.log(
        {
            f"top{top_k}_accuracy": accuracy,
            "mrr": mrr,
            "total_questions": len(examples),
            "hits": hits,
            "top_k": top_k,
            "user_id": user_id,
        }
    )
    wandb.finish()

    return accuracy, mrr


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality on eval_set.json")
    parser.add_argument("run_name", nargs="?", default="retrieval_eval")
    parser.add_argument("--eval-file", type=Path, default=EVAL_SET_PATH)
    parser.add_argument("--user-id", default="test_user")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    configure_dspy(OLLAMA_URL, get_model("answer"))
    run_eval(
        run_name=args.run_name,
        eval_file=args.eval_file,
        user_id=args.user_id,
        top_k=args.top_k,
    )
