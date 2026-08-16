"""The semantic cache's storage contract."""

import time

import pytest

from config.settings import CACHE_TTL
from utils.cache import clear_cache, get_cached_response, set_cached_response

ENTRY = {"context": "some retrieved context", "sources": ["notes"], "scores": [1.2]}


def test_round_trip_on_a_near_identical_embedding(tmp_cache_db):
    set_cached_response("u", [1.0, 0.0, 0.0], ENTRY)
    assert get_cached_response("u", [0.999, 0.01, 0.0]) == ENTRY


def test_miss_below_similarity_threshold(tmp_cache_db):
    set_cached_response("u", [1.0, 0.0, 0.0], ENTRY)
    assert get_cached_response("u", [0.0, 1.0, 0.0]) is None


def test_entries_are_scoped_per_user(tmp_cache_db):
    set_cached_response("u", [1.0, 0.0, 0.0], ENTRY)
    assert get_cached_response("other", [1.0, 0.0, 0.0]) is None


def test_expired_entries_are_purged_on_lookup(tmp_cache_db, monkeypatch):
    import utils.cache as cache

    set_cached_response("u", [1.0, 0.0, 0.0], ENTRY)

    # Advance the clock rather than sleeping for a day. cache.time is the real time
    # module, so this is global for the duration - monkeypatch restores it at teardown.
    later = time.time() + CACHE_TTL + 60
    monkeypatch.setattr(cache.time, "time", lambda: later)

    assert get_cached_response("u", [1.0, 0.0, 0.0]) is None


def test_clear_cache_is_scoped_per_user(tmp_cache_db):
    set_cached_response("u", [1.0, 0.0, 0.0], ENTRY)
    set_cached_response("v", [1.0, 0.0, 0.0], ENTRY)

    assert clear_cache("u") == 1
    assert get_cached_response("u", [1.0, 0.0, 0.0]) is None
    assert get_cached_response("v", [1.0, 0.0, 0.0]) == ENTRY


@pytest.mark.parametrize("bad", [None, "not-a-vector"])
def test_lookup_degrades_to_a_miss_rather_than_raising(tmp_cache_db, bad):
    """Graceful degradation: the cache is an optimization, never a failure point."""
    assert get_cached_response("u", bad) is None
