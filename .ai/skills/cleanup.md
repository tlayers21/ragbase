# RAGbase Cleanup Skill

Quality pass with **no behavior change**. The goal is reduction — less code is better
code. If a change alters what the app does, it isn't cleanup; stop and treat it as a
feature or a bug fix.

Run after a large feature lands, before a release commit, or when a module has grown
past ~300 lines or a pattern has appeared in 2+ files.

---

## Files to match

When you're unsure what "clean" looks like here, read these first — they are the house
style at its best:

| File | Why it's the reference |
|---|---|
| `ingestion/queue.py` | Section headers, small single-purpose functions, atomic writes, clear public/private split |
| `utils/cache.py` | Tight module docstring, every failure path degrades instead of raising, comments only where a *why* exists |
| `retrieval/search.py` | Pure helper functions (`_rrf`, `_rank_indices`, `_build_filter`) split out of the main flow |
| `frontend/lib/api.ts` | One shared SSE parser instead of three; every call typed and centralized |
| `frontend/hooks/useIngestion.ts` | Complex async state kept readable with named helpers (`hasActiveJobs`, `pollInterval`) |

---

## RAGbase-specific patterns to watch for

These are the duplications and drifts that actually recur in this codebase:

**Hardcoded model names.** Any string literal `"qwen3"` / `"qwen2.5:3b"` / `"bge-m3"`
outside `config/models.py` is a bug.
```bash
grep -rn '"qwen\|"bge-m3' --include="*.py" . | grep -v config/models.py
```

**Missing `model=` on a fast task.** `generate_stream()` defaults to qwen3, so a
forgotten argument silently runs the slow thinking model. Audit every call site:
```bash
grep -rn "generate_stream(" --include="*.py" .
```
Only `ml/generate_eval.py` should legitimately omit `model=`.

**Magic numbers outside `config/settings.py`.** Thresholds, timeouts, limits and batch
sizes belong there with a comment saying why that value.

**`fetch()` in a frontend component or hook.** All calls belong in `lib/api.ts`.
```bash
grep -rn "fetch(" frontend/components frontend/hooks
```

**Duplicated SSE / streaming logic.** There is exactly one parser
(`consumeQueryStream`) and one token framer (`_sse_token`). If a second appears,
collapse it — and remember the two are a matched pair across the stack.

**Repeated ChromaDB filter construction.** `{"$and": [...]}` assembly should go through
a helper (`search.py::_build_filter`), not be rebuilt inline.

**Per-endpoint duplication in `api/`.** `/query/stream` and `/query/with_attachments`
share the retrieve → rerank → build-context → stream shape. New endpoints should reuse
`RAGPipeline.search_candidates()` / `rerank_candidates()` / `build_answer_prompt()`
rather than re-implementing the sequence.

**Ingestor subclasses doing more than `extract_text()`.** Chunking, storing,
summarizing and graph enqueueing all live in `BaseIngestor`. If a subclass reimplements
any of it, push it up.

**`sqlite3.connect()` without `timeout=30`.**
```bash
grep -rn "sqlite3.connect(" --include="*.py" . | grep -v "timeout=30"
```

**Non-atomic JSON writes.** Persisted JSON must be temp-file + `os.replace()`.

---

## Generic checks

**Dead code**
```bash
ruff check . --select F401                  # unused imports
cd frontend && npx tsc --noEmit             # unused locals under strict
```
Commented-out code is not documentation — delete it and trust git.

**Over-complex logic** — functions past ~50 lines usually do two things; split at the
natural seam (`pdf.py` does this well: `_is_handwritten` / `_extract_handwritten` /
`_extract_typed` / `_describe_images`). Flatten nested `if` with early returns. Break up
a one-liner that needs a comment to parse. Consider a dataclass past ~4 parameters.

**Missing comments** — after reducing, add the *why* back where a magic number, a
concurrency guard, or a library workaround is now bare. See `.ai/skills/commenting.md`.

---

## Do not touch during cleanup

| Thing | Why |
|---|---|
| `data/`, `frontend/.next/`, `scripts/metrics.*` | Protected — see `master.md` |
| `docs/CODEBASE_EXPLAINED.md` | Owner-curated; only rewrite when explicitly asked |
| `QueryRewriter` in `retrieval/pipeline.py` | Looks dead — `forward()` never calls it — but `ml/eval.py` and `ml/collect_pairs.py` call `pipeline.rewriter` directly |
| `utils/cache.py` | Live on both `/query` and `/query/stream`. The linear cosine scan looks inefficient but is correct at personal scale — don't "optimize" it into an index without a measured need. |
| `config/paths.py::RERANKER_MODEL_PATH` | Never loaded, but `reset_all.sh` deliberately cleans that path |
| `vision_diagram` / `query_rewrite` keys in `config/models.py` | Unreferenced task keys kept so routing can diverge later |
| The response-shape branches in `utils/ollama_client.py` | They look redundant; they exist because ollama-python has changed its embedding response type across versions |
| The 100ms delay in `useChat.sendMessage()` | Looks like a hack; prevents a real reader-teardown crash |

The pattern: **before deleting something that looks unused, grep for it across `ml/`,
`scripts/` and the frontend.** Several things here are reachable only from outside the
server process.

---

## After cleanup

```bash
source .venv/bin/activate && ruff format . && ruff check . --fix
cd frontend && npx tsc --noEmit && cd ..
npm --prefix frontend run build      # if you touched dynamic imports, PDF, or theming
```

Then actually exercise the app — a clean type-check proves nothing about runtime.
Use `.ai/skills/frontend-testing.md` to drive ingestion + a query end to end.
