import json
import random
from pathlib import Path

from config.logging import setup_logging
from config.models import get_model
from config.paths import EVAL_SET_PATH, TRAINING_PAIRS_PATH
from config.settings import OLLAMA_URL
from ml.common import to_chunk_index
from retrieval.pipeline import RAGPipeline, configure_dspy

logger = setup_logging(__name__)

N_RESULTS = 10
MAX_NEGATIVES_PER_POSITIVE = 5


def collect_training_pairs(
    eval_file: Path | None = None,
    output_file: Path | None = None,
    user_id: str = "test_user",
    n_results: int = N_RESULTS,
    max_negatives: int = MAX_NEGATIVES_PER_POSITIVE,
) -> list[dict]:
    eval_file = eval_file or EVAL_SET_PATH
    output_file = output_file or TRAINING_PAIRS_PATH

    with open(eval_file, "r") as f:
        eval_set = json.load(f)

    logger.info(f"Collecting pairwise training data from {len(eval_set)} questions...")

    pipeline = RAGPipeline()
    pairs = []
    skipped = 0

    for i, item in enumerate(eval_set, start=1):
        question = item["question"]
        expected_source = item["source"]
        expected_chunk_index = to_chunk_index(item.get("correct_chunk_index"))

        rewritten_query = pipeline.rewriter(question=question, history="").rewritten_query
        docs, metas, _ = pipeline._retrieve(
            query=rewritten_query,
            original_question=question,
            user_id=user_id,
            source_filter=None,
        )
        docs = docs[:n_results]
        metas = metas[:n_results]

        positive_chunk = None
        negative_chunks = []

        for doc, meta in zip(docs, metas):
            retrieved_source = meta.get("source")
            retrieved_chunk_index = to_chunk_index(meta.get("chunk_index"))
            is_correct = (
                retrieved_source == expected_source
                and retrieved_chunk_index == expected_chunk_index
            )
            if is_correct:
                positive_chunk = doc
            else:
                negative_chunks.append(doc)

        if positive_chunk is None:
            skipped += 1
            logger.debug(f"Q{i}: correct chunk not in top {n_results}, skipping")
            continue

        if len(negative_chunks) > max_negatives:
            negative_chunks = random.sample(negative_chunks, max_negatives)

        for neg in negative_chunks:
            pairs.append(
                {
                    "question": question,
                    "positive_chunk": positive_chunk,
                    "negative_chunk": neg,
                }
            )

        logger.info(f"Processed {i}/{len(eval_set)} questions...")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(pairs, f, indent=2)

    logger.info(f"Collected {len(pairs)} pairwise training examples")
    logger.info(f"Skipped {skipped} questions where correct chunk wasn't in top {n_results}")
    logger.info(f"Saved to {output_file}")

    return pairs


if __name__ == "__main__":
    configure_dspy(OLLAMA_URL, get_model("answer"))
    collect_training_pairs()
