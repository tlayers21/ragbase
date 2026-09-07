"""Metric arithmetic on fixed rankings.

Both metrics are pure functions over (source, chunk_index) keys, so these tests need no
ChromaDB, no Ollama and no corpus. If these are wrong, every number the harness prints is
wrong, which is why they are pinned to hand-computed values rather than to whatever the
code currently returns.
"""

import pytest

from config.paths import QUERY_SET_EXAMPLE_PATH, QUERY_SET_PATH
from metrics.run import first_hit_rank, gold_keys, load, mrr, recall_at_5

RANKED = [("a", 0), ("a", 1), ("b", 0), ("b", 1), ("c", 0), ("c", 1), ("d", 0)]


# -- recall@5 -----------------------------------------------------------------
def test_gold_at_rank_one():
    assert recall_at_5({("a", 0)}, RANKED) == 1.0


def test_gold_at_rank_five():
    assert recall_at_5({("c", 0)}, RANKED) == 1.0


def test_gold_at_rank_six_is_outside_the_window():
    """recall@5 stops at 5. MRR does not, which is the point of keeping both."""
    assert recall_at_5({("c", 1)}, RANKED) == 0.0
    assert mrr({("c", 1)}, RANKED) == pytest.approx(1 / 6)


def test_gold_never_retrieved():
    assert recall_at_5({("z", 9)}, RANKED) == 0.0
    assert mrr({("z", 9)}, RANKED) == 0.0


def test_two_gold_chunks_partially_retrieved():
    """One of two required chunks inside the window is half credit, not a hit or a miss."""
    assert recall_at_5({("a", 0), ("c", 1)}, RANKED) == 0.5


def test_empty_gold_scores_zero_rather_than_dividing_by_zero():
    assert recall_at_5(set(), RANKED) == 0.0


# -- MRR ----------------------------------------------------------------------
def test_mrr_uses_the_first_hit_not_the_best_one():
    """Two gold chunks at ranks 2 and 5 give 1/2, never 1/5 and never their sum."""
    assert mrr({("a", 1), ("c", 0)}, RANKED) == pytest.approx(0.5)


def test_first_hit_rank_reports_none_when_absent():
    assert first_hit_rank({("a", 1)}, RANKED) == 2
    assert first_hit_rank({("z", 9)}, RANKED) is None


# -- Query set ----------------------------------------------------------------
def test_gold_keys_parses_pairs():
    entry = {"question": "q", "gold": [["notes", 3], ["notes", 4]], "verified": True}
    assert gold_keys(entry) == {("notes", 3), ("notes", 4)}


def test_load_rejects_an_entry_with_no_gold(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('[{"question": "q", "verified": true}]')
    with pytest.raises(ValueError, match="gold"):
        load(path)


def test_load_rejects_a_malformed_gold_pair(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('[{"question": "q", "gold": [["only_source"]], "verified": true}]')
    with pytest.raises(ValueError, match=r"\[source, index\]"):
        load(path)


def test_example_query_set_loads():
    """The tracked template is what `--init` copies, so it has to satisfy load()."""
    entries = load(QUERY_SET_EXAMPLE_PATH)
    assert entries
    for entry in entries:
        assert gold_keys(entry)


@pytest.mark.skipif(not QUERY_SET_PATH.exists(), reason="query set is gitignored")
def test_local_query_set_loads():
    """The real file has to parse, or a run fails after the corpus is already built."""
    entries = load()
    assert entries
    for entry in entries:
        assert gold_keys(entry)


def test_load_says_how_to_start_a_set_when_none_exists(tmp_path):
    with pytest.raises(FileNotFoundError, match="--init"):
        load(tmp_path / "query_set.json")
