# RAGbase Update-Docs Skill

Skill for refreshing the cached library documentation in `.ai/docs/`.

---

## When to Update

- A library version has been upgraded in `pyproject.toml` or `frontend/package.json`
- You hit a bug that suggests the cached docs are wrong or outdated
- It has been more than 3 months since the file's "last updated" date
- A new library has been added to the project that isn't in `.ai/docs/` yet
- A full 12-file refresh was last done on 2026-08-06 (all files below) — that's the baseline for the "3 months" rule above.

---

## How to Update

1. **Identify the changed library** — check `pyproject.toml` or `frontend/package.json` for the new version.

2. **Fetch fresh docs** — use Context7 MCP:
   - Context7 is an MCP server configured in `.claude/mcp.json`. It activates automatically in interactive Claude Code sessions (CLI, desktop app, IDE extensions) — **not** in API sessions.
   - In an interactive session, start your prompt with "use context7" to trigger MCP tool calls against Context7's library index.
   - Two-step call pattern: `mcp__context7__resolve-library-id` first to get a Context7-compatible library ID (often resolves to a `/websites/{slug}` doc source rather than the library's own GitHub org — e.g. DSPy resolved to `/websites/dspy_ai`, ChromaDB to `/websites/cookbook_chromadb_dev`), then `mcp__context7__query-docs` with that ID. Each `query-docs` call should cover exactly one topic — issue several scoped calls (client setup, one per major API area) rather than one broad query; broad queries return thin, unfocused results.
   - Request only the APIs actually used in RAGbase — not full library docs
   - Target 500–1000 lines max per file
   - In practice (2026-08-06 refresh), Context7 was available and returned useful results for all 12 libraries — no WebFetch fallback was needed. Keep the fallback below as a contingency, not the expected path:
   - If Context7 MCP is unavailable (API session) or returns nothing useful for a query after rephrasing, fall back to WebFetch from the library's official docs site — the source URL is listed in each `.ai/docs/` file header.

3. **Overwrite the existing file** — replace `.ai/docs/{library}.md` entirely.

4. **Add the standard header** at the top of the file:

   ```markdown
   # {Library} {version} — RAGbase Reference
   > Fetched via Context7 — {YYYY-MM-DD}
   > Version: {version from pyproject.toml or package.json}
   ```

   This is the actual convention in use (matches the `## File Header Template` below) — don't use a `# {Library} Docs Cache` title or a `last updated:` prefix inside the date line.

5. **Check for deprecated APIs** — search the codebase for any patterns flagged as deprecated in the new docs:

   ```bash
   # Example: if new ChromaDB docs say collection.add() signature changed
   grep -rn "collection\.add(" . --include="*.py"
   ```

   If deprecated APIs are found, flag them explicitly in your response. Do not silently update docs without reporting what changed.

6. **Note what changed** — in your response, state:
   - Which file was updated
   - Why (version bump, stale, bug hit)
   - Any deprecated APIs found and where

---

## File Header Template

```markdown
# {Library Name} {version} — RAGbase Reference

> Fetched via Context7 — {YYYY-MM-DD}
> Version: {exact version}

{fresh official API reference content, ~500-1000 lines, scoped to what RAGbase
actually uses}

---

## RAGbase-Specific Notes

{any project-specific usage notes, gotchas, or conventions that were already
in the file before this refresh — preserve these verbatim/lightly reworded,
never drop them, never invent new ones}
```

Every cached doc file is now structured as: official content first, then a
`---` divider, then a `## RAGbase-Specific Notes` section. When refreshing an
existing file, read it first and carry its RAGbase-specific notes forward
into that section rather than overwriting them.

---

## Library → File Mapping

| Library | File | Where to find version |
|---------|------|-----------------------|
| ChromaDB | `.ai/docs/chromadb.md` | `pyproject.toml` |
| FastAPI | `.ai/docs/fastapi.md` | `pyproject.toml` |
| DSPy | `.ai/docs/dspy.md` | `pyproject.toml` |
| Ollama | `.ai/docs/ollama.md` | `pyproject.toml` |
| Docling | `.ai/docs/docling.md` | `pyproject.toml` |
| Transformers | `.ai/docs/transformers.md` | `pyproject.toml` |
| PyMuPDF | `.ai/docs/pymupdf.md` | `pyproject.toml` |
| Whisper | `.ai/docs/whisper.md` | `pyproject.toml` |
| react-pdf | `.ai/docs/react-pdf.md` | `frontend/package.json` |
| Next.js | `.ai/docs/nextjs.md` | `frontend/package.json` |
| react-markdown | `.ai/docs/react-markdown.md` | `frontend/package.json` |
| KaTeX | `.ai/docs/katex.md` | `frontend/package.json` |

---

## Adding a New Library

When a new library is added to the project:

1. Fetch its docs via Context7.
2. Create `.ai/docs/{library-name}.md` with the standard header.
3. Add a row to the library table in `.ai/skills/master.md`.
4. Add the skill table row in this file above.
5. The new file is tracked by git like the rest of `.ai/docs/` — include it in the commit.

---

## Notable Drift Found in the 2026-08-06 Refresh

These are cases where the previously cached docs turned out to be wrong or
stale, not just outdated — worth knowing since it shows the kind of drift
that accumulates between refreshes:

- **DSPy** — old cache claimed `RAGAnswerer` used `dspy.ChainOfThought`.
  Actually all four current signatures (`RAGAnswerer`, `TextCleanup`,
  `TranscriptionRefinement`, `QueryRewriter`) use `dspy.Predict` per
  `.ai/instructions.md`. Corrected.
- **Docling** — the cautionary tale, wrong three times in a row. (1) Old notes said
  RAGbase configured RapidOCR explicitly. (2) The 2026-08-06 refresh "corrected" that
  to "EasyOCR is Docling's default," reading the official docs but not the code.
  (3) The 2026-08-07 audit **ran it** and found both wrong: the installed version's
  `PdfPipelineOptions().ocr_options.kind` is `"auto"`, which resolves to whichever
  engine is installed — RapidOCR here, because `easyocr` isn't installed at all. So
  the original claim was accidentally right, for a reason nobody had established.
  `ingestion/pdf.py` now pins `ocr_options=RapidOcrOptions()` and `rapidocr` is a
  declared dependency, so the behavior no longer depends on what happens to be present.

  **Lesson: for any claim about *this* codebase, run the code — don't read the official
  docs and don't carry the previous note forward.** One `python3 -c` against the
  installed package would have settled this on the first pass.
- **Whisper** — old cache's example used `whisper.load_model("small")`,
  contradicting `.ai/instructions.md`'s statement that RAGbase loads
  `"base"`. Corrected to `"base"`. Also: Whisper's own `load_model()` device
  resolution only checks CUDA→CPU and never auto-detects MPS — this is
  exactly why `ingestion/helpers.py::transcribe()` has its own
  device-detection wrapper.
- **KaTeX** — old cache said the `output` option defaults to `'html'`; the
  real default is `'htmlAndMathml'`. Corrected.
- **react-markdown** — v10's custom `code` component no longer receives an
  `inline` prop; inline vs. fenced must now be inferred from a `language-*`
  className on children. The old cached example was stale for v10. Corrected.

None of the 12 libraries needed a WebFetch fallback — Context7 resolved and
answered queries for all of them (see the "In practice" note above).

### Which libraries drift most

Ranked by how often the cache has been wrong, so you know where to look hardest:

1. **Docling** — worst offender, twice over. Both the default-OCR-engine claim *and*
   the assertion that RAGbase configured RapidOCR were wrong. Its API surface
   (`PdfFormatOption`, `PdfPipelineOptions`, `doc.texts` vs `doc.pages`) also moves
   between minor versions. **Always verify Docling claims against both the docs and
   `ingestion/pdf.py`.**
2. **react-markdown** — v10 removed the `inline` prop from custom `code` components.
   Major-version renders of the component API change silently.
3. **DSPy** — pre-3.x examples dominate training data and the web; `Predict` vs
   `ChainOfThought` and `dspy.LM(...)` construction are both commonly stale.
4. **Whisper** — examples vary the model size freely, and `load_model()` still has no
   MPS auto-detection, which surprises people every time.
5. **KaTeX** — small but persistent option-default errors (`output` defaults to
   `'htmlAndMathml'`, not `'html'`).

ChromaDB, FastAPI, Ollama, PyMuPDF, transformers, react-pdf and Next.js have been
comparatively stable, but Next.js 16 is new enough that training data skews old — check
`frontend/node_modules/next/dist/docs/` rather than trusting recall.

### The standing lesson

A cached file's `## RAGbase-Specific Notes` section makes claims **about this codebase**,
not about the library. Those decay independently of the library version and have been
wrong more often than the official content. **Re-verify every RAGbase-specific claim
against the actual source during a refresh — never carry one forward as fact.**

---

## Important

**`.ai/docs/` is committed to git** — all 12 files are tracked (`git ls-files .ai/docs/`
confirms it; there is no `.gitignore` entry for them). An earlier version of this skill
claimed the opposite. That means a refresh is a real repo change and shows up in diffs —
regenerate deliberately, not casually, and mention it when you do.
