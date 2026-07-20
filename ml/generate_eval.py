import json
from pathlib import Path

from config.logging import setup_logging
from config.paths import EVAL_SET_PATH
from utils.chromadb_client import get_collection
from utils.ollama_client import generate_stream

logger = setup_logging(__name__)


def generate_eval_set(
    source: str,
    user_id: str,
    output_file: Path | None = None,
    questions_per_chunk: int = 2,
) -> list[dict]:
    """
    Generate eval questions from a source's chunks using the LLM.
    Appends to the existing eval set rather than overwriting.
    """
    output_file = output_file or EVAL_SET_PATH

    collection = get_collection(user_id)
    results = collection.get(where={"source": source}, include=["documents", "metadatas"])

    if not results["ids"]:
        logger.warning(f"No chunks found for source '{source}'")
        return []

    chunks = sorted(
        zip(results["documents"], results["metadatas"]), key=lambda x: x[1].get("chunk_index", 0)
    )

    new_questions = []

    for doc, meta in chunks:
        chunk_index = meta.get("chunk_index", 0)
        logger.info(
            f"Generating questions for chunk {chunk_index + 1}/{len(chunks)} of '{source}'..."
        )

        prompt = f"""Based on the following text, generate {questions_per_chunk} specific
factual questions that can ONLY be answered using this exact text.

Text:
{doc}

Respond with one question per line, no numbering, no extra text."""

        try:
            raw = "".join(generate_stream(prompt))
            questions = [q.strip() for q in raw.strip().split("\n") if q.strip()]

            for q in questions[:questions_per_chunk]:
                new_questions.append(
                    {
                        "question": q,
                        "source": source,
                        "correct_chunk_index": chunk_index,
                        "correct_chunk_text": doc,
                    }
                )
        except Exception as e:
            logger.error(f"Failed to generate questions for chunk {chunk_index}: {e}")

    # Load existing and append
    if output_file.exists():
        with open(output_file, "r") as f:
            existing = json.load(f)
    else:
        existing = []

    combined = existing + new_questions
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(combined, f, indent=2)

    logger.info(f"Added {len(new_questions)} questions from '{source}'. Total: {len(combined)}")
    return new_questions


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python3 -m ml.generate_eval <source_name> <user_id>")
    else:
        generate_eval_set(sys.argv[1], sys.argv[2])
