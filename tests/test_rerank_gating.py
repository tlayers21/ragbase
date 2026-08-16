"""Stage 5 gating: the absolute floor and the relative gap.

A chunk dropped here is dropped from the prompt and the sources panel together, so the
thresholds decide both what the user sees cited and what the model is allowed to read.
rerank() itself is patched out - loading BGE-Reranker-v2-m3 is not what these test.
"""

import pytest

import retrieval.pipeline as pipeline


@pytest.fixture
def gate(monkeypatch):
    """Run rerank_candidates over a chosen score list, bypassing the cross-encoder."""

    def _run(scores, min_score=-2.0, max_gap=5.0):
        docs = [f"doc{i}" for i in range(len(scores))]
        metas = [{"source": f"src{i}"} for i in range(len(scores))]

        # rerank() contracts to return descending by score; rerank_candidates relies on
        # scores[0] being the best, so the fake must honour that.
        ordered = sorted(zip(docs, metas, scores), key=lambda t: t[2], reverse=True)
        monkeypatch.setattr(
            pipeline,
            "rerank",
            lambda question, docs, metas: (
                [d for d, _, _ in ordered],
                [m for _, m, _ in ordered],
                [s for _, _, s in ordered],
            ),
        )
        # The floor is read through the runtime getter now, not an imported
        # constant, so that the settings slider applies without a restart.
        monkeypatch.setattr(pipeline, "get_reranker_min_score", lambda: min_score)
        monkeypatch.setattr(pipeline, "RERANKER_MAX_SCORE_GAP", max_gap)

        obj = pipeline.RAGPipeline.__new__(pipeline.RAGPipeline)
        return obj.rerank_candidates("q", docs, metas)

    return _run


def test_floor_keeps_above_and_drops_below(gate):
    _, _, scores = gate([-1.5, -2.5])
    assert scores == [-1.5]


def test_floor_is_inclusive(gate):
    _, _, scores = gate([-2.0])
    assert scores == [-2.0]


def test_everything_below_the_floor_yields_empty_context(gate):
    """The empty-retrieval path: no chunks, so the LLM answers from its own knowledge."""
    docs, metas, scores = gate([-3.0, -4.0])
    assert (docs, metas, scores) == ([], [], [])


def test_gap_drops_stragglers_that_clear_the_floor(gate):
    """One strong hit plus weak padding: every chunk clears the floor, only the leader
    is on topic. floor becomes max(-2.0, 6.0 - 5.0) = 1.0."""
    _, _, scores = gate([6.0, 5.5, 0.0, -1.0])
    assert scores == [6.0, 5.5]


def test_floor_wins_when_it_is_the_stricter_of_the_two(gate):
    """With a low leader the gap is slack, so the absolute floor is what bites."""
    _, _, scores = gate([-1.0, -1.8, -2.5])
    assert scores == [-1.0, -1.8]


def test_empty_input_short_circuits(monkeypatch):
    called = []
    monkeypatch.setattr(pipeline, "rerank", lambda *a, **k: called.append(1))
    obj = pipeline.RAGPipeline.__new__(pipeline.RAGPipeline)

    assert obj.rerank_candidates("q", [], []) == ([], [], [])
    assert not called


def test_configured_floor_is_minus_two():
    """The shipped default, not the patched one - guards the settings.py change itself."""
    from config.settings import RERANKER_MIN_SCORE

    assert RERANKER_MIN_SCORE == -2.0


def test_bottom_of_scale_bypasses_the_relative_gap(gate):
    """The settings slider at 0% means "show me everything".

    The gap cutoff would otherwise still drop the stragglers - the same input as
    test_gap_drops_stragglers_that_clear_the_floor keeps only two chunks under the
    default floor, and must keep all four here.
    """
    from config.settings import RELEVANCE_SCALE_MIN

    _, _, scores = gate([6.0, 5.5, 0.0, -1.0], min_score=RELEVANCE_SCALE_MIN)
    assert scores == [6.0, 5.5, 0.0, -1.0]


def test_gap_still_applies_just_above_the_bottom_of_the_scale(gate):
    """The bypass is the floor sitting *at* the bottom, not merely being permissive."""
    _, _, scores = gate([6.0, 5.5, 0.0, -1.0], min_score=-9.9)
    assert scores == [6.0, 5.5]


def test_runtime_getter_is_what_the_filter_reads():
    """A change made through the settings endpoint has to reach the next query with
    no restart, which only holds while this is a call and not an imported constant."""
    from config.runtime import get_reranker_min_score

    assert pipeline.get_reranker_min_score is get_reranker_min_score
