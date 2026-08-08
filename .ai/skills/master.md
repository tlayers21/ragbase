# RAGbase Master Skill

RAGbase is a **local-first** AI knowledge base: ingest notes/PDFs/images/video/YouTube,
chat with all of it, get grounded answers with citations. FastAPI + embedded ChromaDB +
SQLite + DSPy + Next.js, with every model running locally through Ollama on an M3 Mac.
**No cloud APIs, no API keys, no `.env`, no Docker.**

## Orient in 60 seconds

| Fact | Value |
|---|---|
| Backend | `localhost:8001` (FastAPI, `python3 -m uvicorn main:app --port 8001`) |
| Frontend | `localhost:3000` (Next.js 16 App Router) |
| Ollama | `localhost:11434` |
| Answer model | `qwen3` (thinking model, but thinking is **off** — `ANSWER_THINKING_ENABLED`) |
| Fast model | `qwen2.5:3b` (everything high-volume) |
| Vector store | ChromaDB, **embedded in-process**, `data/chromadb/` |
| Graph + cache | SQLite, WAL, `data/knowledge_graph.db` + `data/cache.db` |
| Config | `config/settings.py` — hardcoded, no env vars |
| Model routing | `config/models.py::get_model(task)` — the only place model names exist |

**The one thing that trips everyone up:** ingestion is two-phase. A source is
**queryable at status `"ingested"`**; `"done"` only means the knowledge graph also
finished. Never block on `"done"`.

## Always do first

1. Read `.ai/instructions.md` — canonical context: repo map, conventions, model stack,
   ingestion/query walkthroughs, exact API signatures, gotchas, architecture rationale.
2. If the task involves understanding existing code, read `docs/CODEBASE_EXPLAINED.md`.

## Load the skill that matches the task

| The task is... | Read |
|---|---|
| Editing anything under `api/`, `ingestion/`, `retrieval/`, `analysis/`, `utils/`, `config/`, `ml/`, or `main.py` | `.ai/skills/backend.md` |
| Editing anything under `frontend/` — component, hook, `lib/`, styling, types | `.ai/skills/frontend.md` |
| Verifying a UI change actually works in a browser, or reproducing a UI bug (ingest / prompt / citations / sources modal) | `.ai/skills/frontend-testing.md` |
| Writing or reviewing comments and docstrings in either language | `.ai/skills/commenting.md` |
| Removing dead code, de-duplicating, tightening an existing implementation with no behavior change | `.ai/skills/cleanup.md` |
| Editing anything in `scripts/`, or adding a dependency, model, port, process or `data/` path that a script must know about | `.ai/skills/update-scripts.md` |
| Editing `README.md` | `.ai/skills/update-readme.md` |
| Editing `.ai/instructions.md` | `.ai/skills/update-instructions.md` |
| Regenerating `docs/CODEBASE_EXPLAINED.md` | `.ai/skills/explain-codebase.md` |
| Refreshing cached library docs in `.ai/docs/`, or hitting an unfamiliar library API | `.ai/skills/update-docs.md` |

Load more than one when the task spans them — a new endpoint consumed by a new
component needs `backend.md` **and** `frontend.md` **and** an `instructions.md` update.

## Always do after changes

| Changed | Run |
|---|---|
| Any `.py` | `source .venv/bin/activate && ruff format . && ruff check . --fix` |
| Any `.ts`/`.tsx` | `cd frontend && npx tsc --noEmit` |
| Dynamic imports, PDF rendering, or theming | also `cd frontend && npm run build` |
| Added/changed/removed an endpoint | update §7 of `.ai/instructions.md` |
| Added a gotcha worth remembering | add it to §8 of `.ai/instructions.md` |

## Never edit autonomously

| Path | Why it's protected |
|---|---|
| `data/` | Live user state — ChromaDB collections, the knowledge graph, the cache, the ingestion queue. Editing it corrupts real data and is not recoverable from git (it's gitignored). Use `scripts/reset_all.sh` to clear it deliberately. |
| `data/user_id.txt`, `data/device_id.txt` | Generated once on first launch and referenced by every ChromaDB collection name and graph table name. Changing either orphans the user's entire corpus. |
| `docs/CODEBASE_EXPLAINED.md` | A long-form narrative document the owner curates. Regenerating it wholesale discards their edits — only rewrite when explicitly asked, following `explain-codebase.md`. |
| `scripts/metrics.*` | Contains the private Pi IP and was deliberately scrubbed from git history. Editing risks re-committing it. |
| `frontend/.next/` | Build output. Never hand-edit; it is regenerated. |

## Project-specific hard rules

- Model names appear **only** in `config/models.py`. Everywhere else: `get_model(task)`.
- `generate_stream()` defaults to **qwen3** — a fast task that omits `model=` silently
  runs on the slow model.
- All Ollama traffic goes through `utils/ollama_client.py` (exceptions: DSPy's own
  transport, and `api/compact.py` which needs one blocking completion).
- All frontend API calls go through `frontend/lib/api.ts`. Never `fetch()` in a component.
- Never send `user_id` from the frontend — the backend reads it from disk.
- Atomic writes (temp file + `os.replace`) for every persisted JSON file.
- `sqlite3.connect(..., timeout=30)` everywhere.

## MCP config note

If you add an MCP server, update **both** `.vscode/mcp.json` and `.claude/mcp.json`.

## Library docs

Cached docs live in `.ai/docs/` — **read those before fetching anything**. Refresh via
Context7 only on a version upgrade or when the cache doesn't answer the question; see
`.ai/skills/update-docs.md` for the exact two-step procedure.

`chromadb` · `fastapi` · `dspy` · `ollama` · `docling` · `transformers` · `pymupdf` ·
`whisper` · `react-pdf` · `nextjs` · `react-markdown` · `katex`
