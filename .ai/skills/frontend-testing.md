# RAGbase Frontend E2E Testing Skill

How to actually exercise the running frontend (ingest, prompt, view sources) instead of just
reading code or hitting the API with curl. Use this whenever asked to "test the frontend",
verify a UI change works, or reproduce a UI bug report.

## Browser driver

Always use headless Playwright for this. Do not use the `claude-in-chrome` skill/tools and do
not suggest installing/connecting the Chrome extension — this project's testing flow is
Playwright-only, regardless of whether the extension is available in a given session.

```bash
mkdir -p <scratchpad>/pw && cd <scratchpad>/pw
npm init -y >/dev/null 2>&1
npm install playwright@<version matching what `npx playwright --version` reports> --silent
```
Chromium is usually already cached at `~/Library/Caches/ms-playwright/` on this machine, so
`npm install playwright` (no `npx playwright install`) is normally enough — check the cache dir
first before triggering a fresh browser download.

Write throwaway `.js` driver scripts in that scratchpad dir (one per flow, not one giant
script) and run them with `node <script>.js`. Take `page.screenshot({ fullPage: true })` at each
meaningful step and `Read` the PNG back to verify visually — don't just trust "no error thrown".
Always attach `console` and `pageerror` listeners and print them at the end of every script; a
clean UI can still be silently throwing.

## Starting the stack

Don't use `scripts/start.sh` for iterative testing — it does a GitHub update check + `git pull`
+ production build, which is slow and can touch the working tree. Instead:

```bash
source .venv/bin/activate
nohup python3 -m uvicorn main:app --port 8001 > /tmp/ragbase_backend.log 2>&1 & disown
cd frontend && nohup npm run dev > /tmp/ragbase_frontend.log 2>&1 & disown
```
Then poll `curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/health` and the same for
`:3000` until both return 200. Check `/tmp/ragbase_backend.log` for startup errors (reranker
load, DSPy config, etc.) — the backend logs `RAGbase ready` before the reranker/model warmup
finishes, so give it a few extra seconds before firing RAG queries.

Real fixture files live in `data/training_data/` (PDFs + one PNG) — use these for ingestion
tests instead of synthetic files; they exercise the real Docling/OCR/vision paths.

## Known DOM gotchas when scripting interactions

- **Two `<input type="file">` elements exist on the page**: one for chat attachments (has an
  `accept=` filter for images/pdf/text) and one for the Sources-panel ingest dropzone (no
  `accept` filter). Target the ingest one explicitly — don't use `.first()` — or you'll attach
  the file to the chat message instead of ingesting it:
  ```js
  const ingestInput = page.locator('input[type="file"]').nth(1); // no accept= attr
  await ingestInput.setInputFiles(path);
  ```
- **Modals (chunk-citation modal, Sources preview modal) don't close on `Escape`** — click the
  visible `×` button instead, or they'll block subsequent clicks with a `bg-black/40` overlay
  and every later `locator.click()` will time out waiting for the overlay to go away.
- **Image ingestion is slow** — it runs Qwen2.5-VL vision + PaddleOCR fusion, easily 60–120s for
  a single image on CPU/MPS. Poll `GET /ingest/status` (via curl, faster than polling the DOM)
  rather than looping `page.waitForTimeout` inside one long-running Playwright script; the job
  reaching `"waiting_for_graph"`/`"building_graph"` means Phase 1 is done and it's already
  queryable even though the Ingest panel still shows a spinner for the graph step.
- **RAG vs direct mode**: toggle via the source-filter chip (bottom-left of the chat input, e.g.
  "All sources" / "0/1 selected"). Deselecting every source switches to direct mode
  automatically — there's no separate direct-mode toggle.
- **Streamed answer footer** (`qwen3 · RAG` vs `qwen3 · direct`) is the reliable way to assert
  which mode actually ran, rather than inferring from the source-filter UI state alone.

## Test matrix to run

1. Ingest a PDF (queue shows progress → Ready/done, source becomes selectable without reload).
2. Ingest an image (slow — see gotcha above).
3. RAG prompt against an ingested source: expect `[STAGE]` progress text (e.g. "Reranking
   chunks…"), a streamed answer, and a "Sources used (N)" button.
4. Click "Sources used" → chunk modal opens with real chunk text and match scores.
5. Direct mode: deselect all sources, ask something not in the corpus, confirm `· direct` tag
   and no citations.
6. Combination: ingest a second source while a chat session is open, confirm it becomes
   queryable in the same session without a page reload.
7. Sources modal: thumbnails lazy-load per card, click into a PDF (react-pdf) and an image
   preview, confirm both render.

## Regression checks (bugs this process found — all fixed 2026-08-07)

Re-verify these specifically; each was a real bug caught only by driving the UI.

- **Citation match percentages must be 0-100.** They were rendering as "-399% match"
  because a raw BGE-reranker logit (~-10..+8) was multiplied by 100. Now normalized by
  `lib/utils.ts::relevancePercent` (sigmoid). Assert every `N% match` is in range.
  Note the values are legitimately *low* (1-5%) on a weakly-matching corpus.
- **Whitespace must survive streaming.** Ask something numeric and check for
  run-together text like `"by8 equals96"`. Caused by `frame.trim()` in
  `consumeQueryStream` eating whitespace-only tokens.
- **Markdown structure must survive streaming.** Ask for bullet points and assert
  `page.locator('li').count() > 0`. Newline tokens used to be destroyed by the SSE
  frame delimiter, collapsing every list onto one line. Backend now JSON-encodes tokens
  (`api/query.py::_sse_token`); the two sides must change together.
- **Image preview must not show "Preview unavailable."** Open the Sources modal, let the
  thumbnail grid load (so the `<img>` requests fire), *then* click into the image
  preview — that ordering is what triggered it. The cause was HTTP cache poisoning: the
  plain `<img src>` sent no `Origin`, so its cached response had no
  `Access-Control-Allow-Origin`, and the browser reused that entry for the CORS
  `fetch()`, which failed with a misleading "blocked by CORS policy". Fixed by
  `Vary: Origin` in `api/sources.py` plus `crossOrigin="anonymous"` on the `<img>` tags.
  A console assertion is the reliable check — the error only appears there.

## Still open (not bugs in the UI, but they shape what you'll see)

- **The semantic cache is live on `/query/stream`.** Asking a paraphrase of an earlier
  question skips retrieval, so the stage sequence jumps straight from
  `retrieving_sources` to `generating` — that is expected, not a bug. Use a novel
  question when you want to exercise the full pipeline, or delete `data/cache.db*`.
- **Source-filtered queries never hit the cache**, by design.
