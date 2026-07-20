import dspy

from config.logging import setup_logging
from config.settings import RERANKER_MIN_SCORE
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


class RAGAnswerer(dspy.Signature):
    """Answer a question using context chunks when available.
    If no relevant context is provided, answer from your own knowledge.
    Never reference 'the context', 'provided examples', 'the text', or where information
    came from. Do not cite source document names inline. Weave information naturally
    into your answer as if already known."""

    question: str = dspy.InputField(desc="The user's question")
    context: str = dspy.InputField(desc="Retrieved context chunks")
    history: str = dspy.InputField(desc="Recent conversation history", default="")
    answer: str = dspy.OutputField(desc="Concise answer without inline source citations or context references")


class QueryRefinement(dspy.Signature):
    """Refine a search query when initial results were insufficient."""

    original_question: str = dspy.InputField(desc="The user's original question")
    previous_query: str = dspy.InputField(
        desc="The previous search query that returned poor results"
    )
    refined_query: str = dspy.OutputField(desc="A refined query to try a different angle")


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
    what the math means or does — even if they sound like part of the notes.
    Preserve LaTeX exactly. Do not add new content.
    """

    raw_transcription: str = dspy.InputField(desc="Raw Qwen2.5-VL transcription for one page")
    refined_transcription: str = dspy.OutputField(
        desc="Only the literal notation and labels, with all narrative/explanatory "
        "sentences removed"
    )


class RAGPipeline(dspy.Module):
    """
    RAG pipeline:
    1. Document-level retrieval (summaries)
    2. Knowledge graph augmentation
    3. Chunk-level hybrid search
    4. Rerank
    5. Threshold filter
    6. Multi-hop if needed
    7. Answer generation

    NOTE: self.rewriter (QueryRewriter) is retained but unused in forward() —
    ml/collect_pairs.py and ml/eval.py still call pipeline.rewriter directly
    to reproduce the retrieval path with a rewritten query for training data
    collection and evaluation.
    """

    def __init__(self):
        self.rewriter = dspy.Predict(QueryRewriter)
        self.answerer = dspy.Predict(RAGAnswerer)
        self.refiner = dspy.Predict(QueryRefinement)

    def forward(
        self,
        question: str,
        user_id: str,
        history: list[dict] | None = None,
        source_filter: list[str] | None = None,
    ) -> dict:
        history_str = format_history(history or [])

        docs, metas, scores = self._retrieve(
            query=question,
            original_question=question,
            user_id=user_id,
            source_filter=source_filter,
            history_str=history_str,
        )

        # Step 7 - Answer generation
        context = build_context(docs, metas)
        answer = self.answerer(
            question=question,
            context=context,
            history=history_str,
        ).answer

        sources = list({meta["source"] for meta in metas})

        return {
            "answer": answer,
            "sources": sources,
            "scores": scores,
        }

    def retrieve_context(
        self,
        question: str,
        user_id: str,
        history: list[dict] | None = None,
        source_filter: list[str] | None = None,
    ) -> dict:
        """
        Run retrieval only (no answer generation) so callers can stream the
        answer themselves via generate_stream() instead of going through the
        non-streaming DSPy answerer.
        """
        history_str = format_history(history or [])

        docs, metas, scores = self._retrieve(
            query=question,
            original_question=question,
            user_id=user_id,
            source_filter=source_filter,
            history_str=history_str,
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
        """
        Steps 1-3 of retrieval: document-level summary search, knowledge graph
        augmentation, and chunk-level hybrid search. Returns raw (unranked)
        candidate chunks. Split out from rerank_candidates() so callers (e.g.
        the streaming API) can report progress between retrieval and rerank.
        """
        # Step 1 - Document-level retrieval
        relevant_sources = search_summaries(query, user_id)
        logger.info(f"Stage 1 found {len(relevant_sources)} relevant sources")

        # Step 2 - Knowledge graph augmentation (skip when no graph built yet)
        if has_graph(user_id):
            graph_sources = query_related_sources(query, user_id)
            all_sources = list(set(relevant_sources + graph_sources))
        else:
            all_sources = relevant_sources

        # Respect source filter if set
        if source_filter:
            all_sources = [s for s in all_sources if s in source_filter] or source_filter

        # Step 3 - Chunk-level hybrid search
        docs, metas = search(
            query=query,
            user_id=user_id,
            source_filter=all_sources if all_sources else source_filter,
        )
        return docs, metas

    def rerank_candidates(
        self,
        question: str,
        docs: list[str],
        metas: list[dict],
    ) -> tuple[list[str], list[dict], list[float]]:
        """
        Step 4 of retrieval: rerank candidate chunks against the original
        question and drop anything below RERANKER_MIN_SCORE.
        """
        if not docs:
            return [], [], []

        docs, metas, scores = rerank(
            question=question,
            docs=docs,
            metas=metas,
        )

        filtered = [(d, m, s) for d, m, s in zip(docs, metas, scores) if s >= RERANKER_MIN_SCORE]
        if filtered:
            docs = [d for d, _, _ in filtered]
            metas = [m for _, m, _ in filtered]
            scores = [s for _, _, s in filtered]
            logger.info(f"Passing {len(docs)} chunks above threshold to LLM")
        else:
            logger.info("No chunks above threshold — LLM will answer from own knowledge")
            docs, metas, scores = [], [], []

        return docs, metas, scores

    def _retrieve(
        self,
        query: str,
        original_question: str,
        user_id: str,
        source_filter: list[str],
        history_str: str,
        pass_num: int = 1,
    ) -> tuple[list[str], list[dict], list[float]]:
        """
        Retrieval with multi-hop support. If results are poor, refines
        the query and tries again up to MAX_RETRIEVAL_PASSES times.
        """
        docs, metas = self.search_candidates(query, user_id, source_filter)
        return self.rerank_candidates(original_question, docs, metas)


# -- Helpers ---------------------------------------------------------------
def format_history(history: list[dict]) -> str:
    """Format chat history as a readable string for context."""
    if not history:
        return ""
    lines = []
    for msg in history[-6:]:  # last 3 turns
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content'][:300]}")
    return "\n".join(lines)


def build_context(docs: list[str], metas: list[dict]) -> str:
    """Build a numbered context string with source names for the LLM."""
    parts = []
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        source = meta.get("source", "unknown")
        parts.append(f"[{i + 1}] (from '{source}'):\n{doc}")
    return "\n\n".join(parts)


def build_answer_prompt(question: str, context: str, history_str: str) -> str:
    """
    Construct a plain-text prompt mirroring the RAGAnswerer signature, for use
    with generate_stream() directly when streaming (DSPy Predict itself does
    not stream token-by-token).
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
    Construct a minimal prompt for direct (non-RAG) mode — no retrieved
    context, just the question and recent conversation history.
    """
    if not history_str:
        return question
    return f"Conversation history:\n{history_str}\n\nQuestion: {question}"


def configure_dspy(ollama_url: str, model: str) -> None:
    """
    Configure DSPy to use a local Ollama model.
    Call this once on app startup before using RAGPipeline.
    """
    lm = dspy.LM(
        model=f"ollama/{model}",
        api_base=ollama_url,
    )
    dspy.settings.configure(lm=lm)
    logger.info(f"DSPy configured with model '{model}' at {ollama_url}")
