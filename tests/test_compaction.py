"""Conversation compaction: the history budget and the /compact batching.

Crossing a model's context window does not shave the overflow off the end - Ollama
truncates the prompt down to roughly num_ctx/2 and keeps only `num_keep` (4) leading
tokens, which destroys the instruction sitting at the head of the prompt. Measured
2026-08-20: an 18,149-token compaction prompt came back as a 20-token echo of the
last message. These tests hold the two defences in place: history is budgeted before
it reaches a prompt, and /compact batches rather than sending one oversized call.
"""

import api.compact as compact
from config.settings import COMPACT_MAX_INPUT_TOKENS, HISTORY_TOKEN_BUDGET
from retrieval.pipeline import format_history


def test_history_is_capped_by_the_token_budget():
    huge = [{"role": "user", "content": "x" * 40_000} for _ in range(20)]
    assert len(format_history(huge)) // 4 <= HISTORY_TOKEN_BUDGET


def test_history_keeps_the_newest_messages_when_it_overflows():
    msgs = [{"role": "user", "content": f"MARK{i} " + "x" * 20_000} for i in range(40)]
    out = format_history(msgs)
    assert "MARK39" in out
    assert "MARK0" not in out


def test_history_preserves_document_order():
    msgs = [{"role": "user", "content": f"MARK{i}"} for i in range(4)]
    out = format_history(msgs)
    assert [line.split(": ")[1] for line in out.splitlines()] == [
        "MARK0",
        "MARK1",
        "MARK2",
        "MARK3",
    ]


def test_a_summary_survives_even_when_it_is_the_oldest_message():
    """The summary is the only record of what it replaced, so age must not evict it."""
    msgs = [{"role": "system", "content": "EARLIER SUMMARY TEXT"}]
    msgs += [{"role": "user", "content": f"m{i} " + "x" * 20_000} for i in range(10)]
    out = format_history(msgs)
    assert "EARLIER SUMMARY TEXT" in out


def test_a_summary_is_not_labelled_as_the_assistant():
    out = format_history([{"role": "system", "content": "recap"}])
    assert out.startswith("Earlier conversation summary:")


def test_empty_messages_are_dropped():
    assert format_history([{"role": "user", "content": "   "}]) == ""


# -- /compact ------------------------------------------------------------------
def _record(monkeypatch):
    """Patch the blocking completion and return the list of prompts it was given."""
    prompts = []

    def fake(prompt, model):
        prompts.append(prompt)
        return f"summary of {len(prompt)} chars"

    monkeypatch.setattr(compact, "_complete", fake)
    return prompts


def test_a_small_conversation_is_one_call(monkeypatch):
    prompts = _record(monkeypatch)
    lines = ["USER: hello", "ASSISTANT: hi"]
    compact._compact(lines, "fake-model")
    assert len(prompts) == 1


def test_an_oversized_conversation_is_batched_and_reduced(monkeypatch):
    prompts = _record(monkeypatch)
    lines = ["USER: " + "x" * 40_000 for _ in range(6)]
    compact._compact(lines, "fake-model")
    assert len(prompts) > 2, "oversized input must map over batches, not go in one call"


def test_no_single_call_exceeds_the_compaction_budget(monkeypatch):
    prompts = _record(monkeypatch)
    lines = ["USER: " + "x" * 40_000 for _ in range(12)]
    compact._compact(lines, "fake-model")
    oversized = [p for p in prompts if len(p) // 4 > COMPACT_MAX_INPUT_TOKENS]
    assert not oversized, f"{len(oversized)} call(s) would be truncated by Ollama"


def test_every_batch_keeps_its_instruction(monkeypatch):
    prompts = _record(monkeypatch)
    lines = ["USER: " + "x" * 40_000 for _ in range(6)]
    compact._compact(lines, "fake-model")
    assert all(
        p.startswith(("Summarize this conversation", "Combine these summaries")) for p in prompts
    )


def test_a_prior_summary_is_carried_into_the_next_compaction():
    """api/compact.py used to filter role != 'system', dropping every earlier summary."""
    rendered = compact._render({"role": "system", "content": "the earlier summary"})
    assert "the earlier summary" in rendered
    assert rendered.startswith("EARLIER SUMMARY:")


def test_a_line_larger_than_the_budget_is_truncated_not_sent_whole():
    batches = compact._batch(["x" * 200_000, "short"], 1000)
    assert all(batches), "a batch must never be empty"
    assert all(compact._estimate_tokens("\n".join(b)) <= 1000 for b in batches)
