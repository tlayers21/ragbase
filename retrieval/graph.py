import json
import re
import sqlite3
import time
from collections.abc import Callable

import networkx as nx
from json_repair import repair_json

from config.logging import setup_logging
from config.models import get_model
from config.paths import KNOWLEDGE_GRAPH_DB_PATH
from config.runtime import is_query_in_progress
from config.settings import (
    GRAPH_MAX_CONSECUTIVE_FAILURES,
    GRAPH_YIELD_MAX_SECONDS,
    GRAPH_YIELD_SLEEP_SECONDS,
)
from utils.ollama_client import generate_stream

logger = setup_logging(__name__)


DB_PATH = KNOWLEDGE_GRAPH_DB_PATH

_USER_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_user_id(user_id: str) -> str:
    """Ensure user_id is safe to interpolate into a SQL identifier."""
    if not _USER_ID_RE.match(user_id):
        raise ValueError(f"Invalid user_id: {user_id!r}")
    return user_id


# -- Database Setup --------------------------------------------------------
def _get_connection(user_id: str) -> sqlite3.Connection:
    """Get a SQLite connection for the user's knowledge graph."""
    user_id = _validate_user_id(user_id)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    _init_tables(conn, user_id)
    return conn


def graph_connection(user_id: str) -> sqlite3.Connection:
    """Open the knowledge-graph DB for a user, validated and WAL-enabled.

    The public entry point, so callers outside this module cannot bypass
    _validate_user_id or the patchable DB_PATH.
    """
    return _get_connection(user_id)


def _init_tables(conn: sqlite3.Connection, user_id: str) -> None:
    """Create graph tables and indexes if they don't exist."""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS nodes_{user_id} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS edges_{user_id} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_entity TEXT NOT NULL,
            to_entity TEXT NOT NULL,
            relation TEXT NOT NULL,
            source TEXT NOT NULL,
            UNIQUE(from_entity, to_entity, relation)
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_{user_id}_source ON nodes_{user_id}(source);
        CREATE INDEX IF NOT EXISTS idx_edges_{user_id}_source ON edges_{user_id}(source);
        CREATE INDEX IF NOT EXISTS idx_edges_{user_id}_from ON edges_{user_id}(from_entity);
        CREATE INDEX IF NOT EXISTS idx_edges_{user_id}_to ON edges_{user_id}(to_entity);
    """)
    conn.commit()


# -- Entity extraction -----------------------------------------------------
def _strip_latex(text: str) -> str:
    """Remove LaTeX math before entity extraction, since malformed LaTeX breaks JSON output.

    Lossy: brace and backslash stripping also mangles embedded code and JSON strings.
    """
    text = re.sub(r"\$[^$]{0,500}\$", "[math expression]", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = re.sub(r"[{}\\]", "", text)
    return text


_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "both",
        "either",
    }
)

_LATEX_RE = re.compile(r"^[\$\\]")
_NUMERIC_RE = re.compile(r"^[\d\s\.\,\-\+\%\(\)]+$")


def _is_low_quality_entity(entity: str) -> bool:
    stripped = entity.strip()
    if len(stripped) < 3:
        return True
    if stripped.lower() in _STOP_WORDS:
        return True
    if _NUMERIC_RE.match(stripped):
        return True
    if _LATEX_RE.match(stripped):
        return True
    return False


def _validate_extracted(extracted: dict, source: str) -> dict:
    """Validate model output before it reaches any DB insert. Drops
    malformed, low-quality, or duplicate entities/relationships."""
    seen_lower: set[str] = set()
    valid_entities = []
    for entity in extracted.get("entities", []):
        if not isinstance(entity, str) or not entity.strip():
            logger.debug(f"Dropping invalid entity from '{source}': {entity!r}")
            continue
        if _is_low_quality_entity(entity):
            logger.debug(f"Dropping low-quality entity from '{source}': {entity!r}")
            continue
        lower = entity.strip().lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        valid_entities.append(entity.strip())

    valid_relationships = []
    for rel in extracted.get("relationships", []):
        if isinstance(rel, dict) and all(
            isinstance(rel.get(k), str) and rel.get(k).strip() for k in ("from", "relation", "to")
        ):
            # Also drop relationships whose endpoints are low-quality
            if _is_low_quality_entity(rel["from"]) or _is_low_quality_entity(rel["to"]):
                logger.debug(f"Dropping low-quality relationship from '{source}': {rel!r}")
                continue
            valid_relationships.append(rel)
        else:
            logger.debug(f"Dropping invalid relationship from '{source}': {rel!r}")

    return {"entities": valid_entities, "relationships": valid_relationships}


class EntityExtractionUnavailable(RuntimeError):
    """The extraction call itself failed - Ollama timed out, refused, or is unreachable.

    Distinct from a chunk the model answered badly, which is skipped inline.
    """


def extract_entities(text: str, source: str) -> dict:
    """Extract validated entities and relationships from one chunk via the fast model.

    Raises EntityExtractionUnavailable if the call fails; unparseable output returns empty
    lists, because one bad chunk says nothing about the next.
    """
    text = _strip_latex(text)

    prompt = f"""Extract entities and relationships from the following text.

Text:
{text[:1500]}

Respond with valid JSON only in this exact format:
{{
  "entities": ["entity1", "entity2", "entity3"],
  "relationships": [
    {{"from": "entity1", "relation": "relates to", "to": "entity2"}}
  ]
}}

Only include clear factual entities and relationships. Output JSON only, no explanation."""

    # Split so a wedged model propagates while one chunk's bad output is swallowed
    try:
        raw = "".join(generate_stream(prompt, model=get_model("entity_extraction")))
    except Exception as e:
        raise EntityExtractionUnavailable(f"Entity extraction call failed: {e}") from e

    try:
        raw = (
            raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )  # models often fence JSON
        repaired = repair_json(raw)
        parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
        return _validate_extracted(parsed, source)
    except Exception as e:
        logger.warning(f"Unparseable entity extraction for '{source}', skipping chunk: {e}")
        return {"entities": [], "relationships": []}


# -- Graph building --------------------------------------------------------
def _yield_to_queries(source: str) -> None:
    """Pause the graph build while a query is being served.

    Capped at GRAPH_YIELD_MAX_SECONDS so a flag left set by a crashed request degrades
    into a slower build rather than one that never finishes.
    """
    if not is_query_in_progress():
        return

    waited = 0.0
    while is_query_in_progress() and waited < GRAPH_YIELD_MAX_SECONDS:
        time.sleep(GRAPH_YIELD_SLEEP_SECONDS)
        waited += GRAPH_YIELD_SLEEP_SECONDS

    if waited >= GRAPH_YIELD_MAX_SECONDS:
        logger.warning(
            f"Graph build for '{source}' waited {waited:.1f}s on an active query - resuming anyway"
        )
    else:
        logger.debug(f"Graph build for '{source}' yielded {waited:.1f}s to an active query")


def build_from_chunks(
    chunks: list[str],
    source: str,
    user_id: str,
    should_stop: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Extract entities and relationships from every chunk of a source into the graph.

    `should_stop` is polled per chunk and again before its inserts; the build raises
    EntityExtractionUnavailable after GRAPH_MAX_CONSECUTIVE_FAILURES calls fail in a row.
    """
    user_id = _validate_user_id(user_id)
    conn = _get_connection(user_id)

    total_entities = 0
    total_edges = 0
    stopped = False
    last_pct = -1
    consecutive_failures = 0

    try:
        for done, chunk in enumerate(chunks):
            if should_stop is not None and should_stop():
                stopped = True
                break

            if on_progress is not None:
                pct = done * 100 // len(chunks)
                if pct != last_pct:
                    last_pct = pct
                    # 1-based, matching how the PDF page loops report
                    on_progress(done + 1, len(chunks))

            _yield_to_queries(source)
            try:
                extracted = extract_entities(chunk, source)
            except EntityExtractionUnavailable as e:
                consecutive_failures += 1
                logger.warning(
                    f"Entity extraction unavailable for '{source}' "
                    f"({consecutive_failures}/{GRAPH_MAX_CONSECUTIVE_FAILURES}): {e}"
                )
                if consecutive_failures >= GRAPH_MAX_CONSECUTIVE_FAILURES:
                    raise
                continue
            consecutive_failures = 0

            # Re-checked after the LLM call, or a deleted source gains orphaned nodes
            if should_stop is not None and should_stop():
                stopped = True
                break

            for entity in extracted.get("entities", []):
                try:
                    # INSERT OR IGNORE gives no signal - total_changes counts real inserts
                    changes_before = conn.total_changes
                    conn.execute(
                        f"INSERT OR IGNORE INTO nodes_{user_id} (entity, source) VALUES (?, ?)",
                        (entity.lower()[:200], source),
                    )
                    if conn.total_changes > changes_before:
                        total_entities += 1
                except Exception as e:
                    logger.warning(f"Failed to insert entity '{entity}': {e}")

            for rel in extracted.get("relationships", []):
                try:
                    changes_before = conn.total_changes
                    conn.execute(
                        f"""INSERT OR IGNORE INTO edges_{user_id}
                            (from_entity, to_entity, relation, source)
                            VALUES (?, ?, ?, ?)""",
                        (
                            rel["from"].lower()[:200],
                            rel["to"].lower()[:200],
                            rel["relation"][:200],
                            source,
                        ),
                    )
                    if conn.total_changes > changes_before:
                        total_edges += 1
                except Exception as e:
                    logger.warning(f"Failed to insert relationship: {e}")

            # Per chunk - one deferred transaction holds SQLite's write lock all build
            conn.commit()
    finally:
        conn.close()

    if stopped:
        logger.info(
            f"Graph build for '{source}' stopped early (cancelled or deleted): "
            f"kept {total_entities} entities, {total_edges} relationships"
        )
        return

    logger.info(
        f"Built graph for '{source}': {total_entities} entities, {total_edges} relationships"
    )


def delete_source(source: str, user_id: str) -> None:
    """Remove all graph nodes and edges for a source when it is deleted."""
    user_id = _validate_user_id(user_id)
    conn = _get_connection(user_id)
    try:
        conn.execute(f"DELETE FROM nodes_{user_id} WHERE source = ?", (source,))
        conn.execute(f"DELETE FROM edges_{user_id} WHERE source = ?", (source,))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Removed graph data for '{source}'")


# -- Graph querying --------------------------------------------------------
def has_graph(user_id: str) -> bool:
    """Return True if the user has at least one node in their knowledge graph."""
    user_id = _validate_user_id(user_id)
    if not DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            row = conn.execute(
                f"SELECT 1 FROM nodes_{user_id} LIMIT 1"  # noqa: S608
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()
    except Exception:
        return False


def query_related_sources(query: str, user_id: str, hops: int = 2) -> list[str]:
    """
    Find sources related to the query by traversing the knowledge graph.
    Extracts query entities, finds matching nodes, traverses up to `hops`
    edges, and returns the source names of connected nodes.
    """
    user_id = _validate_user_id(user_id)
    conn = _get_connection(user_id)

    try:
        rows = conn.execute(
            f"SELECT from_entity, to_entity, relation, source FROM edges_{user_id}"
        ).fetchall()

        node_rows = conn.execute(f"SELECT entity, source FROM nodes_{user_id}").fetchall()
    finally:
        conn.close()

    if not rows and not node_rows:
        return []

    G = nx.DiGraph()
    for from_e, to_e, relation, source in rows:
        G.add_edge(from_e, to_e, relation=relation, source=source)

    node_sources = {entity: source for entity, source in node_rows}

    if G.number_of_nodes() == 0:
        return []

    query_words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
    if not query_words:
        return []

    seed_nodes = [node for node in G.nodes() if query_words & set(re.findall(r"\w+", node))]

    if not seed_nodes:
        return []

    related_sources = set()
    for seed in seed_nodes:
        try:
            neighbors = nx.single_source_shortest_path_length(G, seed, cutoff=hops)
            for node in neighbors:
                if node in node_sources:
                    related_sources.add(node_sources[node])
        except nx.NetworkXError:
            continue

    logger.debug(f"Graph traversal found related sources: {related_sources}")
    return list(related_sources)
