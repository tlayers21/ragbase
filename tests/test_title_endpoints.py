"""Both title endpoints, which share an implementation but not their tuning.

`POST /title` names a chat session; `POST /ingest/generate_title` names an ingested
document. They ask for different word counts, read different amounts of the input, and
only one clips its output - the clip must not spread to the ingest path, where a source
name is separately slugified and capped at 100.
"""

import asyncio

import pytest

import api.ingest as ingest
import api.title as title


def _capture(monkeypatch, reply="a generated title"):
    """Patch the blocking call and return the prompts it was handed."""
    prompts = []

    def fake(prompt: str) -> str:
        prompts.append(prompt)
        return reply

    monkeypatch.setattr(title, "_generate", fake)
    return prompts


def test_chat_title_asks_for_three_to_six_words(monkeypatch):
    prompts = _capture(monkeypatch)
    asyncio.run(title.generate_title(title.TitleRequest(message="hello there")))
    assert "3-6 word" in prompts[0]
    assert "conversation" in prompts[0]


def test_document_title_asks_for_two_to_five_words(monkeypatch):
    prompts = _capture(monkeypatch)
    asyncio.run(ingest.generate_title(text="some ingested prose"))
    assert "2-5 word" in prompts[0]


def test_chat_title_reads_at_most_200_chars(monkeypatch):
    prompts = _capture(monkeypatch)
    asyncio.run(title.generate_title(title.TitleRequest(message="Z" * 5000)))
    assert prompts[0].count("Z") == 200


def test_document_title_reads_at_most_500_chars(monkeypatch):
    prompts = _capture(monkeypatch)
    asyncio.run(ingest.generate_title(text="Z" * 5000))
    assert prompts[0].count("Z") == 500


def test_chat_title_is_clipped_to_60_chars(monkeypatch):
    _capture(monkeypatch, reply="word " * 100)
    out = asyncio.run(title.generate_title(title.TitleRequest(message="hi")))
    assert len(out["title"]) <= 60


def test_document_title_is_not_clipped(monkeypatch):
    """Source names are slugified and capped at 100 downstream - clipping here truncates them."""
    _capture(monkeypatch, reply="word " * 100)
    out = asyncio.run(ingest.generate_title(text="prose"))
    assert len(out["title"]) > 60


def test_both_normalize_a_run_together_title(monkeypatch):
    _capture(monkeypatch, reply="gradient-descent-explained")
    assert asyncio.run(title.generate_title(title.TitleRequest(message="hi")))["title"] == (
        "gradient descent explained"
    )
    assert asyncio.run(ingest.generate_title(text="p"))["title"] == "gradient descent explained"


def test_a_model_failure_is_a_500_not_an_empty_title(monkeypatch):
    """A dead model must not look like a model that returned nothing.

    Both endpoints swallowed the exception and returned {"title": ""} with a 200, which
    made a genuine failure indistinguishable from a legitimately empty result - so a
    caller had no way to tell "keep your fallback name" from "the title model is down".
    """
    from fastapi import HTTPException

    def boom(prompt):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(title, "_generate", boom)

    for call in (
        lambda: title.generate_title(title.TitleRequest(message="hi")),
        lambda: ingest.generate_title(text="prose"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        assert exc.value.status_code == 500
        assert "ollama down" in str(exc.value.detail), "the reason must reach the caller"


def test_a_legitimately_empty_title_is_still_a_success(monkeypatch):
    """The other half of the distinction: nothing generated is a real answer, not an error."""
    _capture(monkeypatch, reply="   ")
    assert asyncio.run(title.generate_title(title.TitleRequest(message="hi")))["title"] == ""
    assert asyncio.run(ingest.generate_title(text="prose"))["title"] == ""


def test_the_failure_reaches_the_wire_as_a_500(monkeypatch):
    """Asserting the exception is not enough - the caller sees the HTTP response.

    Mounted on a bare app rather than main.app so the offline suite still starts no
    queue worker and touches no Ollama.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    def boom(prompt):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(title, "_generate", boom)

    app = FastAPI()
    app.include_router(title.router)
    app.include_router(ingest.router)
    client = TestClient(app, raise_server_exceptions=False)

    for res in (
        client.post("/title", json={"message": "hi"}),
        client.post("/ingest/generate_title", data={"text": "prose"}),
    ):
        assert res.status_code == 500, res.text
        assert "Title generation failed" in res.json()["detail"]
        assert "title" not in res.json(), "a failure must not carry a title field at all"
