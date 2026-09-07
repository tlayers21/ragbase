"""`fuse()` was extracted out of `search()` so the eval harness could call it directly.

These pin the behaviour that extraction had to preserve.

Pool size matters here in a way it does not in production. RRF divides by `RRF_K + rank`,
so with k=60 a three document pool spreads its scores over 1/61..1/63 and the whole
lexical arm is worth less than one adjacent vector gap. Any test asserting that BM25
moved something therefore needs a pool of realistic size; `TOP_K_CANDIDATES` is 20.
"""

from retrieval.search import fuse

DOCS = [
    "reciprocal rank fusion combines two ranked lists",
    "the mitochondria is the powerhouse of the cell",
    "rank fusion is a retrieval technique",
]

# Vector order is the list order. Docs 0 and 1 lead on vector distance but carry none of
# the query terms; doc 2 is the lexical match sitting behind them; the tail all carry one
# term each, which is what pushes 0 and 1 to the bottom of the BM25 ranking.
LEXICAL_POOL = [
    "the mitochondria is the powerhouse of the cell",
    "a balanced tree keeps its leaves at the same depth",
    "rank fusion is a retrieval technique",
    "retrieval latency budgets for a serving tier",
    "rank ordering in a tournament bracket",
    "fusion cooking borrows from two traditions",
    "retrieval practice is a study method",
    "rank correlation between two graders",
    "fusion welding joins two metal edges",
    "retrieval of a satellite from low orbit",
]


def test_fuse_returns_a_permutation_of_every_candidate_index():
    """Fusion reorders the candidate pool and never adds to or drops from it."""
    assert sorted(fuse("rank fusion", DOCS)) == [0, 1, 2]


def test_lexical_match_is_promoted_over_vector_order():
    """Doc 2 trails on vector distance; BM25 agreement pulls it to the front."""
    order = fuse("rank fusion retrieval", LEXICAL_POOL)
    assert order[0] == 2


def test_lexical_arm_cannot_overturn_a_large_vector_gap():
    """The weighted arm is a tiebreaker: a lexical hit last on vector distance stays back.

    This is the trade BM25_WEIGHT buys. At equal weight the lexical arm reordered the
    head of the pool on paraphrased questions, which is where it scored worst.
    """
    pool = LEXICAL_POOL[:1] + LEXICAL_POOL[3:] + [LEXICAL_POOL[2]]
    order = fuse("rank fusion retrieval", pool)
    assert order[0] != len(pool) - 1


def test_ties_fall_back_to_vector_order():
    """With no lexical signal at all, RRF leaves Chroma's distance order intact."""
    assert fuse("zzzz", DOCS) == [0, 1, 2]


def test_single_candidate():
    assert fuse("anything", ["only one doc"]) == [0]
