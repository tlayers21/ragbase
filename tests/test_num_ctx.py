"""The per-model context window.

Omit `num_ctx` and Ollama silently applies a 4096 default, then truncates anything
longer without erroring - so a caller that forgets it doesn't fail, it just quietly
answers from part of its prompt. Nothing surfaces that, which is why it went
unnoticed on the main query path for as long as it did.

`generate_stream` therefore defaults the window from the model rather than trusting
call sites to pass it. These tests hold that default in place, and hold `warm()` to
requesting the *same* window - a runner is configured for one num_ctx, so warming at
one size and querying at another reloads several GB with a user waiting, which is
the exact cold-start cost warmup exists to remove.
"""

import config.models as models
import utils.ollama_client as oc
from config.settings import NUM_CTX_FAST, NUM_CTX_STANDARD, NUM_CTX_VISION


class _RecordingClient:
    """Stand-in for the Ollama client that records kwargs instead of calling out."""

    def __init__(self):
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        # Shape depends on the call, as the real client's does: an iterator of
        # frames when streaming, one response object when not.
        if kwargs.get("stream"):
            return iter([])
        return {"message": {"content": ""}}

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"response": ""}

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        return {"embeddings": [[0.0]]}


def _recording(monkeypatch) -> _RecordingClient:
    """Patch the client where it is *used*, per the isolation rule in testing.md."""
    fake = _RecordingClient()
    monkeypatch.setattr(oc, "client", fake)
    return fake


def test_generate_stream_defaults_the_models_window(monkeypatch):
    """A caller that passes no options still gets its model's window."""
    fake = _recording(monkeypatch)

    list(oc.generate_stream("hello", model=models.MODEL_STANDARD))
    list(oc.generate_stream("hello", model=models.MODEL_FAST))

    assert fake.calls[0]["options"] == {"num_ctx": NUM_CTX_STANDARD}
    assert fake.calls[1]["options"] == {"num_ctx": NUM_CTX_FAST}


def test_explicit_options_win(monkeypatch):
    """An explicit window is never overridden by the default."""
    fake = _recording(monkeypatch)

    list(oc.generate_stream("hello", model=models.MODEL_STANDARD, options={"num_ctx": 2048}))

    assert fake.calls[0]["options"] == {"num_ctx": 2048}


def test_warm_requests_the_same_window_as_generation(monkeypatch):
    """Warmup must load the runner the query path will actually use.

    The regression this guards is silent and expensive: warm at Ollama's default,
    query at NUM_CTX_STANDARD, and the first question pays a full multi-GB reload
    of a model that was already resident.
    """
    fake = _recording(monkeypatch)

    oc.warm("answer")
    list(oc.generate_stream("hello", model=models.get_model("answer")))

    warm_call, query_call = fake.calls
    assert warm_call["options"] == query_call["options"]
    assert warm_call["options"] == {"num_ctx": NUM_CTX_STANDARD}


def test_vision_uses_the_vision_window(monkeypatch):
    """Vision keeps its own smaller window - it is the one model that can't coexist."""
    fake = _recording(monkeypatch)
    monkeypatch.setattr(oc.base64, "b64encode", lambda _: b"")
    monkeypatch.setattr("builtins.open", lambda *a, **k: __import__("io").BytesIO(b""))

    oc.vision("/nonexistent.png", "describe", task="vision_simple")

    assert fake.calls[0]["options"] == {"num_ctx": NUM_CTX_VISION}


def test_embedding_model_sends_no_window():
    """bge-m3 is a BERT encoder - there is no generative KV cache to size.

    None rather than a number on purpose: sending a num_ctx for it would be
    meaningless config that a reader would then have to reason about.
    """
    assert models.get_num_ctx(models.MODEL_EMBED) is None
    assert oc.ctx_options(models.MODEL_EMBED) is None


def test_unknown_model_degrades_instead_of_raising():
    """ml/ scripts can name a model directly; a missing entry must not break them."""
    assert models.get_num_ctx("some-model-we-have-never-heard-of") is None


# -- DSPy ----------------------------------------------------------------------
# DSPy reaches Ollama through LiteLLM, not utils/ollama_client, so it inherits
# neither the shared socket timeout nor the model's window unless both are passed
# explicitly. Three call sites did neither, which ran qwen2.5:3b at Ollama's 4096
# default while every generate_stream path loaded it at 16,384 - two windows for one
# model, so an ingest tore the runner down and reloaded it on every alternation.
def test_make_lm_carries_the_models_window():
    from retrieval.pipeline import make_lm

    assert make_lm(models.MODEL_STANDARD).kwargs["num_ctx"] == NUM_CTX_STANDARD
    assert make_lm(models.MODEL_FAST).kwargs["num_ctx"] == NUM_CTX_FAST


def test_make_lm_carries_the_shared_timeout():
    from config.settings import OLLAMA_TIMEOUT_SECONDS
    from retrieval.pipeline import make_lm

    assert make_lm(models.MODEL_FAST).kwargs["timeout"] == OLLAMA_TIMEOUT_SECONDS


def test_no_call_site_builds_a_bare_dspy_lm():
    """Every dspy.LM must come from make_lm, or it silently runs at Ollama's 4096."""
    import pathlib

    offenders = []
    for path in pathlib.Path(".").rglob("*.py"):
        parts = path.parts
        if ".venv" in parts or "tests" in parts:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "dspy.LM(" in line and path.as_posix() != "retrieval/pipeline.py":
                offenders.append(f"{path}:{i}")
    assert not offenders, f"bare dspy.LM outside make_lm: {offenders}"
