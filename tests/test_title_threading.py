"""POST /title must not generate on the event loop.

useChat fires this concurrently with the first /query/stream of every new chat, so a
blocking call here froze the answer the user was already watching until qwen2.5:3b
finished. Asserted behaviorally: a bare in-loop call starves everything else, while
asyncio.to_thread lets other tasks keep running.
"""

import asyncio
import time

import api.title as title

BLOCK_SECONDS = 0.3


async def test_generation_does_not_block_the_event_loop(monkeypatch):
    monkeypatch.setattr(title, "_generate", lambda prompt: time.sleep(BLOCK_SECONDS) or "a title")

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    tick_task = asyncio.create_task(ticker())
    try:
        result = await title.generate_title(title.TitleRequest(message="hello there"))
    finally:
        tick_task.cancel()

    assert result["title"] == "a title"
    # ~30 ticks if the sleep ran off-loop; 0-1 if it ran on it.
    assert ticks > 5, f"event loop was blocked during title generation (ticks={ticks})"


async def test_title_is_normalized_and_truncated(monkeypatch):
    monkeypatch.setattr(title, "_generate", lambda prompt: "  a very " + "long " * 40 + "title  ")
    result = await title.generate_title(title.TitleRequest(message="hi"))
    assert len(result["title"]) <= 60
