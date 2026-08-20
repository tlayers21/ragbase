"""The relevance floor is clamped where it is stored, not only where it arrives.

The clamp used to live in the HTTP handler alone, so a hand-edited or corrupt
data/settings.json could put the floor below RELEVANCE_SCALE_MIN - which silently
takes the "show me everything" branch in rerank_candidates() and disables the
relative gap cutoff along with it.
"""

import pytest

import config.runtime as runtime
from config.settings import RELEVANCE_SCALE_MAX, RELEVANCE_SCALE_MIN, RERANKER_MIN_SCORE


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Keep every write off the real data/settings.json."""
    monkeypatch.setattr(runtime, "SETTINGS_JSON_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(runtime, "_settings", dict(runtime._settings))
    return tmp_path


def test_the_setter_clamps_below_the_scale(isolated_settings):
    runtime.set_reranker_min_score(-999.0)
    assert runtime.get_reranker_min_score() == RELEVANCE_SCALE_MIN


def test_the_setter_clamps_above_the_scale(isolated_settings):
    runtime.set_reranker_min_score(999.0)
    assert runtime.get_reranker_min_score() == RELEVANCE_SCALE_MAX


def test_a_value_inside_the_scale_is_kept(isolated_settings):
    runtime.set_reranker_min_score(-2.0)
    assert runtime.get_reranker_min_score() == -2.0


def test_a_corrupt_stored_value_is_clamped_on_read(isolated_settings):
    """The file is user-editable, so the getter cannot trust what it finds."""
    runtime._settings["reranker_min_score"] = -10_000.0
    assert runtime.get_reranker_min_score() == RELEVANCE_SCALE_MIN


def test_the_default_is_the_shipped_floor(isolated_settings):
    runtime._settings.pop("reranker_min_score", None)
    assert runtime.get_reranker_min_score() == RERANKER_MIN_SCORE
