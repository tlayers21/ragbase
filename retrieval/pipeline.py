import dspy

from config.logging import setup_logging
from config.models import get_num_ctx
from config.runtime import get_reranker_min_score
from config.settings import (
    HISTORY_MESSAGE_MAX_CHARS,
    HISTORY_TOKEN_BUDGET,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_URL,
    RELEVANCE_SCALE_MIN,
    RERANKER_MAX_SCORE_GAP,
    TOP_K_CANDIDATES,
)
from ingestion.queue import active_sources
from retrieval.graph import has_graph, query_related_sources
from retrieval.reranker import rerank
from retrieval.search import search, search_summaries

logger = setup_logging(__name__)


# -- DSPy signatures -------------------------------------------------------
class QueryRewriter(dspy.Signature):
    """Rewrite a user question into an optimized search query.
    Use conversation history for context if provided."""

    question: str = dspy.InputField(desc="The user's original question")
    history: str = dspy.InputField(desc="Recent conversation history for context", default="")
    rewritten_query: str = dspy.OutputField(desc="Optimized search query for retrieval")


class TextCleanup(dspy.Signature):
    """Clean raw extracted text without changing meaning.

    Restore missing whitespace, spacing, and character-encoding issues while
    preserving all factual content exactly as written. Do not summarize, rewrite,
    reorder, add, or drop information. Preserve all numbers, units, technical
    terms, and document structure exactly as they should appear.
    """

    raw_text: str = dspy.InputField(
        desc="A page of raw extracted text that may have spacing or encoding issues"
    )
    cleaned_text: str = dspy.OutputField(
        desc="The same text with spacing and character-encoding issues corrected"
    )


class TranscriptionRefinement(dspy.Signature):
    """Refine raw handwritten transcription by removing narration and paraphrase.

    The raw transcription may mix literal content with descriptive commentary
    about that content. Remove the commentary, keep only the literal content.

    Example:
    Raw: "The variables W_0 and w_i are defined. It is mentioned that mu_i is
    calculated for each position i, and the final expression represents the
    sum of these weights over the range i=1,2,...,n."
    Refined: "W_0, w_i, v_i. mu_i, i < n. sum_{i=1}^{n} mu_i"

    Keep only mathematical notation, symbols, and short labels as literally
    written. Remove all full sentences that describe, explain, or narrate
    what the math means or does - even if they sound like part of the notes.
    Preserve LaTeX exactly. Do not add new content.
    """

    raw_transcription: str = dspy.InputField(desc="Raw Qwen2.5-VL transcription for one page")
    refined_transcription: str = dspy.OutputField(
        desc="Only the literal notation and labels, with all narrative/explanatory "
        "sentences removed"
    )


class RAGPipeline(dspy.Module):
    """Retrieval pipeline: summaries, graph, hybrid search, rerank, threshold.

    `self.rewriter` is unused here but retained - ml/collect_pairs.py and ml/eval.py call
    it directly.
    """

    def __init__(self):
        self.rewriter = dspy.Predict(QueryRewriter)

    def retrieve_context(
        self,
        question: str,
        user_id: str,
        history: list[dict] | None = None,
        source_filter: list[str] | None = None,
    ) -> dict:
        """Run retrieval only, so callers can stream the answer themselves.

        Returns the same shape as a full answer minus the answer itself.
        """
        history_str = format_history(history or [])

        docs, metas, scores = self._retrieve(
            query=question,
            original_question=question,
            user_id=user_id,
            source_filter=source_filter,
        )

        context = build_context(docs, metas)
        sources = list({meta["source"] for meta in metas})

        return {
            "context": context,
            "sources": sources,
            "scores": scores,
            "history_str": history_str,
        }

    def search_candidates(
        self,
        query: str,
        user_id: str,
        source_filter: list[str] | None = None,
    ) -> tuple[list[str], list[dict]]:
        """Steps 1-3 of retrieval: summary search, graph augmentation, chunk-level hybrid search.

        Returns unranked candidates, and excludes sources with an in-flight ingestion job.
        """
        excluded = active_sources(user_id)

        # Narrowed, never widened - an all-unfinished filter must not fall through
        if source_filter:
            source_filter = [s for s in source_filter if s not in excluded]
            if not source_filter:
                logger.info("Every requested source is still ingesting - no candidates")
                return [], []

        # Step 1 - Document-level retrieval (already excludes unfinished sources)
        relevant_sources = search_summaries(query, user_id)
        logger.info(f"Stage 1 found {len(relevant_sources)} relevant sources")

        # Step 2 - graph augmentation, filtered because SQLite already holds partial rows
        if has_graph(user_id):
            graph_sources = [s for s in query_related_sources(query, user_id) if s not in excluded]
            all_sources = list(set(relevant_sources + graph_sources))
        else:
            all_sources = relevant_sources

        # Fall back to the filtered sources when stage 1 and the graph found nothing
        if source_filter:
            all_sources = [s for s in all_sources if s in source_filter] or source_filter

        # Step 3 - TOP_K_CANDIDATES so the cross-encoder sees the full candidate pool
        docs, metas = search(
            query=query,
            user_id=user_id,
            n_results=TOP_K_CANDIDATES,
            source_filter=all_sources if all_sources else source_filter,
        )
        return docs, metas

    def rerank_candidates(
        self,
        question: str,
        docs: list[str],
        metas: list[dict],
    ) -> tuple[list[str], list[dict], list[float]]:
        """Step 4: rerank candidates and drop chunks too weak to cite or prompt with.

        Two cutoffs in raw logits - the user-tunable absolute floor, read per call, and
        RERANKER_MAX_SCORE_GAP relative to the best chunk in this result set.
        """
        if not docs:
            return [], [], []

        docs, metas, scores = rerank(
            question=question,
            docs=docs,
            metas=metas,
        )

        # rerank() returns descending by score, so scores[0] is the best
        min_score = get_reranker_min_score()
        # At the bottom of the scale the slider means "show everything", gap included
        if min_score <= RELEVANCE_SCALE_MIN:
            floor = min_score
        else:
            floor = max(min_score, scores[0] - RERANKER_MAX_SCORE_GAP)
        filtered = [(d, m, s) for d, m, s in zip(docs, metas, scores) if s >= floor]
        if filtered:
            docs = [d for d, _, _ in filtered]
            metas = [m for _, m, _ in filtered]
            scores = [s for _, _, s in filtered]
            logger.info(f"Passing {len(docs)} chunks above threshold to LLM")
        else:
            logger.info("No chunks above threshold - LLM will answer from own knowledge")
            docs, metas, scores = [], [], []

        return docs, metas, scores

    def _retrieve(
        self,
        query: str,
        original_question: str,
        user_id: str,
        source_filter: list[str] | None,
    ) -> tuple[list[str], list[dict], list[float]]:
        """
        Full retrieval: candidate search with `query`, then rerank against
        `original_question` - the two differ when callers (ml/ scripts) search
        with a rewritten query but still score against the user's phrasing.
        """
        docs, metas = self.search_candidates(query, user_id, source_filter)
        return self.rerank_candidates(original_question, docs, metas)


# -- Helpers ---------------------------------------------------------------
def _history_label(msg: dict) -> str:
    """Prompt label for one history message."""
    role = msg.get("role")
    if role == "user":
        return "User"
    if role == "system":
        return "Earlier conversation summary"
    return "Assistant"


def format_history(history: list[dict], budget: int = HISTORY_TOKEN_BUDGET) -> str:
    """Format chat history as prompt text, newest-first up to a token budget.

    A compaction summary is pinned regardless of age, since dropping it would
    discard the only record of everything it replaced.
    """
    if not history:
        return ""

    pinned, ordinary = [], []
    for i, msg in enumerate(history):
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        entry = (i, f"{_history_label(msg)}: {content[:HISTORY_MESSAGE_MAX_CHARS]}")
        (pinned if msg.get("role") == "system" else ordinary).append(entry)

    kept = list(pinned)
    spent = sum(len(text) for _, text in pinned) // 4
    for entry in reversed(ordinary):
        cost = len(entry[1]) // 4
        if spent + cost > budget:
            break
        kept.append(entry)
        spent += cost

    return "\n".join(text for _, text in sorted(kept))


def build_context(docs: list[str], metas: list[dict]) -> str:
    """Build a numbered context string with source names for the LLM."""
    parts = []
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        source = meta.get("source", "unknown")
        parts.append(f"[{i + 1}] (from '{source}'):\n{doc}")
    return "\n\n".join(parts)


def build_answer_prompt(question: str, context: str, history_str: str) -> str:
    """Construct the plain-text answer prompt for generate_stream().

    Built as text rather than a DSPy signature because dspy.Predict cannot stream.
    """
    history_block = f"\nConversation history:\n{history_str}\n" if history_str else ""
    return (
        "Answer the question using the context below when available. "
        "If no relevant context is provided, answer from your own knowledge. "
        "Do not cite source names or refer to 'the context', 'provided examples', "
        "'the text', or any phrase that narrates where information came from. "
        "Weave information naturally into your answer as if already known.\n"
        f"{history_block}\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\nAnswer:"
    )


def build_direct_prompt(question: str, history_str: str) -> str:
    """
    Construct a minimal prompt for direct (non-RAG) mode - no retrieved
    context, just the question and recent conversation history.
    """
    if not history_str:
        return question
    return f"Conversation history:\n{history_str}\n\nQuestion: {question}"


def build_explain_prompt(source: str, context: str, partial: bool = False) -> str:
    """Construct the prompt for explaining one whole source in depth.

    `partial` marks the reduce step, where `context` holds batch summaries rather than raw
    chunks, so the model does not present them as the document's own words.
    """
    material = (
        "section summaries of a document, in order" if partial else "the full text of a document"
    )
    return (
        f"Below is {material} titled '{source}'.\n\n"
        "Explain this document in depth. Cover what it is about, the key ideas and "
        "how they connect, any important details, definitions or results, and the "
        "conclusions it reaches. Organise the explanation with markdown headings and "
        "follow the document's own structure. Be specific and concrete - prefer the "
        "document's actual content over general statements about the topic. Do not "
        "invent material that is not present.\n\n"
        f"Document:\n{context}\n\nExplanation:"
    )


def make_lm(model: str, ollama_url: str = OLLAMA_URL) -> dspy.LM:
    """Build a dspy.LM carrying this model's window and the shared socket timeout.

    DSPy reaches Ollama through LiteLLM rather than utils/ollama_client, so both have
    to be passed explicitly or the call runs at Ollama's 4096 default with no timeout.
    """
    return dspy.LM(
        model=f"ollama/{model}",
        api_base=ollama_url,
        num_ctx=get_num_ctx(model),
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )


def configure_dspy(ollama_url: str, model: str) -> None:
    """Configure DSPy to use a local Ollama model, once on app startup."""
    lm = make_lm(model, ollama_url)
    dspy.settings.configure(lm=lm)
    logger.info(f"DSPy configured with model '{model}' at {ollama_url}")
