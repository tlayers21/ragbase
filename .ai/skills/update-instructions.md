# RAGbase Update-Instructions Skill

`.ai/instructions.md` is the canonical project context — every agent session reads it
first. `.github/copilot-instructions.md` is a one-line pointer to it and must never grow
content.

Its promise is at the top of the file: **every statement was verified against the
source.** An unverified addition breaks that promise for every future session, which is
worse than no entry at all.

## Triggers — be specific

| Change | Section |
|---|---|
| File or directory added/removed/renamed | §2 Repository Map |
| Endpoint added, removed, or its request/response shape changed | §7 API Reference |
| SSE event type added, or the wire format changed | §7 SSE wire format |
| Model added/swapped, or a `get_model` task key added | §4 Model Stack |
| A new rule someone must follow (not a one-off) | §3 Coding Conventions |
| A trap that cost someone debugging time | §8 Known Gotchas |
| A deliberate design choice with a real tradeoff | §10 Architecture Decisions |
| Ingestion phase/status behavior changed | §5 |
| A retrieval stage, threshold, or ordering changed | §6 |
| A new frontend hook, or a changed state pattern | §9 |

**Not triggers:** internal refactors with no behavior change, a renamed local variable,
a fixed typo, or anything a future session wouldn't need to know.

## Good vs bad entries

**Bad — vague, unactionable:**
> - **Caching** — the app has a cache that can cause stale results.

**Good — specific, verified, tells you what to do:**
> - **Source-filtered queries bypass the semantic cache in both directions.** Cached
>   context was built under a different filter, so reusing it would surface chunks from
>   sources the user deliberately deselected.

---

**Bad — restates the obvious:**
> - **Logging** — use logging instead of print.

**Good — prescriptive, names the exact call:**
> **Logging** — every module starts with `logger = setup_logging(__name__)`. Never
> `print()`. Never `logging.getLogger()` directly.

---

**Bad — describes what, not why, so it can't be reasoned about:**
> - **Graph queue** — graph builds use a separate queue.

**Good — the reasoning survives, so a future change can be evaluated:**
> **Sequential graph queue** — parallel builds all hammer the same local qwen2.5:3b,
> which is a single process. Concurrency made it slower, not faster.

---

**Bad — states a conclusion without the mechanism, so it can't be re-verified:**
> OCR for typed PDFs uses RapidOCR.

**Good — names the mechanism and the failure mode it prevents:**
> **Docling's default `ocr_options.kind` is `"auto"`**, which silently resolves to
> whichever OCR engine is installed — so the engine could change out from under you on a
> dependency bump. `pdf.py` pins `ocr_options=RapidOcrOptions()` and `rapidocr` is a
> declared dependency. Keep both in sync.

## Format rules

- Match surrounding style: same heading levels, table shapes, code-fence style.
- §7 uses aligned plain text, not Markdown tables — keep the columns lined up.
- §8 gotchas are grouped by area (SSE, cache, ingestion, storage, frontend,
  environment). Put a new one in its group; add a group only if genuinely new.
- Gotcha format: a **bold lead** stating the trap, then the mechanism, then what to do.
  If it needs more than ~4 lines, it's probably two gotchas.
- Prefer exact numbers and real identifiers over prose.

## Never remove a gotcha

They exist because someone got burned. If the behavior changed, **rewrite the entry to
describe the new behavior** — don't delete it. If a trap was genuinely eliminated by a
fix, say so and describe the invariant that must hold to keep it fixed (e.g. "`_sse_token`
and `consumeQueryStream` must change together").

## After editing

1. Re-verify each statement you touched against the actual source file.
2. §4 model table matches `config/models.py` exactly.
3. §7 matches the routers in `api/*.py` — method, path, and parameter names.
4. `.github/copilot-instructions.md` still contains only the pointer.
5. Update the "verified against the source on YYYY-MM-DD" date at the top **only** if
   you actually re-verified broadly, not for a one-line edit.
