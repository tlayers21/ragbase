import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config.logging import setup_logging
from config.paths import QUERY_SET_EXAMPLE_PATH, QUERY_SET_PATH, TRAINING_DATA_DIR
from config.runtime import USER_ID
from config.settings import TOP_K_CANDIDATES
from ingestion.queue import active_sources
from ml.common import to_chunk_index
from retrieval.embed import embed
from retrieval.search import _build_filter, fuse
from utils.chromadb_client import get_collection, get_source_chunks

logger = setup_logging(__name__)

API_BASE_URL = "http://127.0.0.1:8001"
CHUNK_PREVIEW_CHARS = 1200

Key = tuple[str, int | None]


# -- Query set ----------------------------------------------------------------
def load(path: Path = QUERY_SET_PATH) -> list[dict[str, Any]]:
    """Load and shape-check the query set.

    The set is gitignored, so a fresh clone has none. Say how to start one rather than
    letting a bare FileNotFoundError stand in for the instruction.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path}\nNo query set yet. Start one with `python3 -m metrics.run --init`, "
            f"which copies {QUERY_SET_EXAMPLE_PATH.name}, then replace its two placeholder "
            f"entries with questions about your own corpus."
        )
    entries = json.loads(path.read_text())
    for i, entry in enumerate(entries):
        if not entry.get("question") or not entry.get("gold"):
            raise ValueError(f"Entry {i} in {path} needs both 'question' and 'gold'")
        for pair in entry["gold"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"Entry {i} in {path}: gold items must be [source, index]")
    return entries


def gold_keys(entry: dict[str, Any]) -> set[Key]:
    """The (source, chunk_index) pairs that count as a correct retrieval."""
    return {(source, to_chunk_index(index)) for source, index in entry["gold"]}


def require_verified(entries: list[dict[str, Any]]) -> None:
    """Refuse to measure while any gold chunk is unconfirmed.
    """
    pending = [i for i, e in enumerate(entries, 1) if not e.get("verified")]
    if pending:
        raise ValueError(
            f"{len(pending)} of {len(entries)} questions are unverified: {pending}\n"
            f"Run `python3 -m metrics.run --review`, confirm each gold chunk, "
            f'then set "verified": true.'
        )


# -- Retrieval ----------------------------------------------------------------
def candidates(query: str, user_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    """The candidate pool for one query, mirroring stage 3 of `retrieval.search.search()`.
    """
    collection = get_collection(user_id)
    fetch_n = min(TOP_K_CANDIDATES, collection.count())
    if fetch_n == 0:
        logger.warning("Collection is empty - no candidates for any query")
        return [], []

    results = collection.query(
        query_embeddings=[embed(query)],
        n_results=fetch_n,
        where=_build_filter(user_id, None, active_sources(user_id)),
        include=["documents", "metadatas"],
    )
    return results["documents"][0], results["metadatas"][0]


def rank(metas: list[dict[str, Any]], order: list[int]) -> list[Key]:
    """(source, chunk_index) in the given order, which is what the metrics compare on."""
    return [(metas[i].get("source"), to_chunk_index(metas[i].get("chunk_index"))) for i in order]


# -- Metrics ------------------------------------------------------------------
def recall_at_5(gold: set[Key], ranked: list[Key]) -> float:
    """Fraction of the gold chunks appearing in the top 5.

    With a single gold chunk, the usual case, this is identical to hit rate at 5.
    """
    if not gold:
        return 0.0
    return len(gold & set(ranked[:5])) / len(gold)


def first_hit_rank(gold: set[Key], ranked: list[Key]) -> int | None:
    """1-based rank of the first gold chunk, or None if none was retrieved."""
    for i, key in enumerate(ranked, start=1):
        if key in gold:
            return i
    return None


def mrr(gold: set[Key], ranked: list[Key]) -> float:
    """1/rank of the first gold hit, 0.0 if it never appears.
    """
    hit = first_hit_rank(gold, ranked)
    return 1.0 / hit if hit else 0.0


# -- Commands -----------------------------------------------------------------
def measure(entries: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    """Score every question under both methods."""
    scores: dict[str, dict[str, list[float]]] = {
        m: {"recall@5": [], "mrr": []} for m in ("vector", "hybrid")
    }

    for i, entry in enumerate(entries, 1):
        docs, metas = candidates(entry["question"], user_id)
        gold = gold_keys(entry)

        # Chroma returns ascending cosine distance, so its own order is the vector ranking
        rankings = {
            "vector": rank(metas, list(range(len(docs)))),
            "hybrid": rank(metas, fuse(entry["question"], docs) if docs else []),
        }
        for method, ranked in rankings.items():
            scores[method]["recall@5"].append(recall_at_5(gold, ranked))
            scores[method]["mrr"].append(mrr(gold, ranked))

        ranks = " ".join(f"{m}={first_hit_rank(gold, r) or 'miss'}" for m, r in rankings.items())
        logger.info(f"Q{i}/{len(entries)} {ranks}")

    collection = get_collection(user_id)
    sources = {m.get("source") for m in collection.get(include=["metadatas"])["metadatas"]}
    return {
        "questions": len(entries),
        "sources": len(sources),
        "chunks": collection.count(),
        "methods": {m: {k: sum(v) / len(v) for k, v in per.items()} for m, per in scores.items()},
    }


def review(entries: list[dict[str, Any]], user_id: str) -> None:
    """Print each question beside its gold chunk text, for confirming the mapping by eye."""
    for i, entry in enumerate(entries, 1):
        mark = "verified" if entry.get("verified") else "UNVERIFIED"
        print(f"\n{'=' * 80}\nQ{i}. {entry['question']}  [{mark}]")
        if entry.get("note"):
            print(f"  expected answer: {entry['note']}")

        for source, index in entry["gold"]:
            chunks = {
                idx: text
                for text, meta in get_source_chunks(source, user_id)
                if (idx := to_chunk_index(meta.get("chunk_index"))) is not None
            }
            text = chunks.get(index)
            if text is None:
                print(
                    f"\n  --- {source} chunk {index}: NOT IN INDEX "
                    f"(valid: 0..{max(chunks) if chunks else 'none'}) ---"
                )
                continue
            print(f"\n  --- {source} chunk {index} ---")
            print("  " + " ".join(text.split())[:CHUNK_PREVIEW_CHARS])

    pending = sum(1 for e in entries if not e.get("verified"))
    print(
        f"\n{len(entries) - pending}/{len(entries)} verified. "
        f'Set "verified": true in {QUERY_SET_PATH} for each one you confirm.\n'
    )


def init(path: Path = QUERY_SET_PATH) -> None:
    """Seed a new query set from the tracked example.

    A query set cannot be generated: the questions are written by hand and every gold
    index is confirmed by eye. All this does is put the schema in place to edit.
    """
    if path.exists():
        raise ValueError(f"{path} already exists - delete it first to start over.")
    path.write_text(QUERY_SET_EXAMPLE_PATH.read_text())
    print(
        f"\nWrote {path} from {QUERY_SET_EXAMPLE_PATH.name}.\n"
        f"Replace the placeholder entries, then `--review` each gold chunk and set "
        f'"verified": true before measuring.\n'
    )


def _slug(name: str) -> str:
    """Filename to source name, matching scripts/ingest_training_data.sh."""
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", name.lower()))


def ingest(entries: list[dict[str, Any]]) -> int:
    """Queue the corpus: every .txt, plus only the PDFs the query set actually needs.
    """
    needed = {source for e in entries for source, _ in e["gold"]}
    queued = 0

    pdfs = [p for p in sorted(TRAINING_DATA_DIR.glob("*.pdf")) if _slug(p.stem) in needed]
    missing = needed - {_slug(p.stem) for p in pdfs}
    if missing:
        logger.warning(f"No PDF in {TRAINING_DATA_DIR} for gold source(s): {sorted(missing)}")

    for path in pdfs:
        print(f"  pdf  {_slug(path.stem)}")
        with open(path, "rb") as f:
            _post_file(f.read(), path.name, _slug(path.stem))
        queued += 1

    for path in sorted(TRAINING_DATA_DIR.glob("*.txt")):
        print(f"  txt  {path.stem}")
        _post_form("/ingest/text", {"text": path.read_text(), "source": path.stem})
        queued += 1

    return queued


def _post_form(path: str, fields: dict[str, str]) -> None:
    """POST form-encoded fields to the running backend."""
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(f"{API_BASE_URL}{path}", data=data, method="POST")
    with urllib.request.urlopen(request, timeout=120):
        pass


def _post_file(content: bytes, filename: str, source: str) -> None:
    """POST one file as multipart/form-data, which urllib has no helper for."""
    boundary = "----ragbase-metrics-boundary"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        + content
        + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="source"\r\n\r\n'
            f"{source}\r\n--{boundary}--\r\n"
        ).encode()
    )

    request = urllib.request.Request(
        f"{API_BASE_URL}/ingest/file",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300):
        pass


# -- Entry point --------------------------------------------------------------
def main() -> int:
    """Dispatch, turning the expected failures into a message rather than a traceback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="Seed a query set from the example")
    parser.add_argument("--review", action="store_true", help="Print gold chunks to confirm")
    parser.add_argument("--ingest", action="store_true", help="Queue the corpus, then exit")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.add_argument("--user-id", default=USER_ID)
    parser.add_argument("--query-set", type=Path, default=QUERY_SET_PATH)
    args = parser.parse_args()

    try:
        if args.init:
            init(args.query_set)
            return 0

        entries = load(args.query_set)

        if args.ingest:
            count = ingest(entries)
            print(f"\n{count} source(s) queued. Watch: curl -s {API_BASE_URL}/ingest/status")
            return 0

        if args.review:
            review(entries, args.user_id)
            return 0

        require_verified(entries)
        results = measure(entries, args.user_id)

        if args.json:
            print(json.dumps(results, indent=2))
            return 0

        print(f"\n{'method':<10}{'recall@5':>12}{'MRR':>9}")
        print("-" * 31)
        for method, stats in results["methods"].items():
            print(f"{method:<10}{stats['recall@5']:>12.3f}{stats['mrr']:>9.3f}")
        print(
            f"\n{results['questions']} questions, {results['sources']} sources, "
            f"{results['chunks']} chunks\n"
        )
        return 0

    except FileNotFoundError as e:
        print(f"Not found: {e}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Backend unreachable at {API_BASE_URL}: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"\n{e}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
