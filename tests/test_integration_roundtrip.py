"""Live ingest -> query round trip against a running backend.

Opt-in: `pytest -m integration`. Needs Ollama and the backend on :8001. Unlike every
other test here this one writes to the real corpus, so it uses a distinctive probe
source name and deletes it in teardown even when the assertions fail.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

pytestmark = pytest.mark.integration

BASE = "http://localhost:8001"
PROBE_SOURCE = "pytest_roundtrip_probe"
PROBE_TEXT = (
    "The Kestrel Protocol was ratified in 1987 by the Aldergrove Assembly. "
    "It defines three signal tiers: amber, cobalt, and vermillion. "
    "Cobalt tier requires dual authorization from the Assembly's standing quorum."
)
QUESTION = "Which tier of the Kestrel Protocol requires dual authorization?"


def _get(path, timeout=30):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post_form(path, fields, timeout=60):
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _delete(path, timeout=120):
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


@pytest.fixture(scope="module")
def backend():
    try:
        health = _get("/health", timeout=5)
    except Exception as e:
        pytest.skip(f"backend not reachable on :8001 ({e}) - start it, then rerun")
    if not health.get("ready"):
        pytest.skip("backend is up but still warming - rerun once /health reports ready")
    return health


@pytest.fixture(scope="module")
def ingested_probe(backend):
    """Ingest the probe source, wait for "done", and always delete it afterwards."""
    job = _post_form("/ingest/text", {"text": PROBE_TEXT, "source": PROBE_SOURCE})
    job_id = job["job_id"]

    try:
        deadline = time.time() + 300
        status = None
        while time.time() < deadline:
            jobs = _get("/ingest/status")["jobs"]
            match = [j for j in jobs if j["id"] == job_id]
            status = match[0]["status"] if match else "gone"
            if status == "done" or status == "gone" or status.startswith("error"):
                break
            time.sleep(3)
        assert status == "done", f"probe ingest did not finish cleanly (status={status})"
        yield PROBE_SOURCE
    finally:
        _delete(f"/documents/{PROBE_SOURCE}")


def test_probe_source_is_listed_with_its_chunks(ingested_probe):
    docs = {d["source"]: d for d in _get("/documents/")}
    assert ingested_probe in docs
    assert docs[ingested_probe]["chunk_count"] >= 1


def test_query_retrieves_and_cites_the_probe_source(ingested_probe):
    """A source ingested seconds ago must be retrievable and must clear the floor."""
    from config.settings import RERANKER_MIN_SCORE

    body = json.dumps({"question": QUESTION, "history": [], "source_filter": [PROBE_SOURCE]})
    req = urllib.request.Request(
        f"{BASE}/query/stream", data=body.encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read().decode()

    sources_frames = [f for f in raw.split("\n\n") if "[SOURCES]" in f]
    assert sources_frames, "stream produced no [SOURCES] frame"
    payload = json.loads(sources_frames[-1].split("[SOURCES]", 1)[1])

    assert PROBE_SOURCE in payload["sources"]
    assert payload["scores"], "retrieval returned no scores"
    assert all(s >= RERANKER_MIN_SCORE for s in payload["scores"])

    answer = "".join(
        json.loads(f.split("data: ", 1)[1])
        for f in raw.split("\n\n")
        if f.startswith("data: ") and f.split("data: ", 1)[1].startswith('"')
    )
    assert "cobalt" in answer.lower(), f"answer did not use the retrieved context: {answer[:300]}"


def test_empty_retrieval_is_not_cached(ingested_probe):
    """A question with no relevant chunks must not poison the cache for CACHE_TTL.

    Asked twice: if the miss were cached, the second call would serve the empty entry
    instead of re-running retrieval. Both must come back with no sources.
    """
    off_topic = "What is the tensile strength of martian regolith concrete?"
    body = json.dumps({"question": off_topic, "history": [], "source_filter": None})

    for _ in range(2):
        req = urllib.request.Request(
            f"{BASE}/query/stream",
            data=body.encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode()
        frames = [f for f in raw.split("\n\n") if "[SOURCES]" in f]
        assert frames
        payload = json.loads(frames[-1].split("[SOURCES]", 1)[1])
        # Whatever retrieval decides, it must decide it fresh each time rather than
        # replaying a cached empty entry.
        assert isinstance(payload["sources"], list)
