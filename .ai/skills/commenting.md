# RAGbase Commenting Skill

A comment must justify its existence by explaining something the code cannot: **why**,
never **what**. A well-named function needs no comment. An unusual threshold, a race
workaround, or a library quirk earns one.

**The test:** if the comment would still be true after you deleted the code and wrote a
different implementation, it's probably explaining *why* and belongs. If it just narrates
the line beneath it, delete it or rename something instead.

---

## What complexity actually warrants a comment

Comment when a reader who knows Python/TypeScript well would still stop and ask
"why is it done *this* way?" Concretely, in this codebase that means:

| Warrants a comment | Example from the codebase |
|---|---|
| A magic number whose value was chosen, not derived | `RERANKER_MIN_SCORE = -8.0`, `timeout=30`, `PASTE_TEXT_THRESHOLD = 5000` |
| A library quirk or version workaround | Whisper's `fp16=False` on MPS; ollama-python's shifting embedding response shape |
| A concurrency or ordering guard | the 100ms abort grace period in `useChat`; `Vary: Origin` in `api/sources.py` |
| Deliberately *not* doing the obvious thing | generation using `generate_stream()` instead of DSPy because `Predict` can't stream |
| A lossy or approximate tradeoff being accepted knowingly | `_strip_latex()` also mangling code blocks; the `chars/4` token estimate |
| Control flow that looks wrong but isn't | `reader.cancel()` resolving `read()` with `done: true` instead of rejecting |
| A cross-file invariant | `_sse_token` ↔ `consumeQueryStream` must change together |

**Does not warrant a comment:** anything a good name already says. Loop mechanics.
Standard idioms. Restating a type hint.

---

## Before / after, from this codebase

**Bad — narrates the code:**
```python
# Split the text into chunks
chunks = chunk_text(text)
# Store the chunks
stored = self.store(chunks, source_name, extra_meta)
```
**Good — the same lines, commented only where there's a real "why":**
```python
chunks = chunk_text(text)
stored = self.store(chunks, source_name, extra_meta)
```
Nothing here is surprising. The names carry it. Zero comments is correct.

---

**Bad — restates the call:**
```python
# Set the journal mode to WAL
conn.execute("PRAGMA journal_mode=WAL")
```
**Good — explains the choice:**
```python
conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
```

---

**Bad — describes what, not why:**
```python
# Only take the first 20 candidates
fetch_n = min(TOP_K_CANDIDATES, collection.count())
```
**Good:**
```python
fetch_n = min(TOP_K_CANDIDATES, collection.count())  # Chroma errors if n > collection size
```

---

**Bad — a comment covering for a vague name:**
```python
# the pool that bm25 rescopes over, not the whole corpus
d = docs
```
**Good — rename instead of commenting:**
```python
vector_candidates = docs
```

---

**Good — a genuine cross-file invariant that no name can express:**
```python
# BM25 runs over the vector candidates only (not the full corpus) — cheap
# keyword re-scoring of an already-relevant pool
tokenized = [doc.lower().split() for doc in docs]
```

---

**Good — a bug that will silently come back if the reasoning is lost:**
```tsx
// Strip only the SSE line framing — never trim the payload. Model tokens are
// frequently pure whitespace (" ") or carry a trailing space, and trimming the
// frame silently drops them, rendering "12 multiplied by8 equals96".
const line = frame.replace(/^\n+/, "").replace(/\r$/, "");
```

---

## Python: section headers

Use above a block that shifts concern — never on every block.

```python
# -- Graph build worker -----------------------------------------------------
```

- Format: `# -- Name ---...` — two hyphens, space, name, hyphens padding toward col 100.
  Regular hyphens only, never em dashes.
- One blank line above; none between the header and the code it introduces.
- Reference style: `ingestion/queue.py`, `utils/ollama_client.py`.

## Python: inline comments

```python
timeout=30                          # graph thread and queue worker both write this DB
model.transcribe(path, fp16=False)  # fp16 path has known MPS issues
RERANKER_MIN_SCORE = -8.0           # empirically tuned - below this, chunks add noise
```

- Two spaces before `#` (ruff format enforces this).
- Capitalize unless the first word is an identifier that's genuinely lowercase.
- No trailing period. No em dashes.

## Python: docstrings

Every public function gets one. **Default to a single line.** The name plus type hints
usually carry the contract:

```python
def has_graph(user_id: str) -> bool:
    """Return True if the user has at least one node in their knowledge graph."""
```

Expand to multiple lines **only** when the function encodes something a caller would
otherwise get wrong — a non-obvious contract, a failure mode, a hard-won gotcha. The
codebase does this deliberately in a handful of places (`rerank()`,
`search_summaries()`, `_sse_token()`, `enqueue_graph_build()`), and those are the right
calls. Do not pad an obvious function into a paragraph to look thorough.

```python
def rerank(question: str, docs: list[str], metas: list[dict], top_k: int = MAX_FINAL_RESULTS):
    """
    Rerank retrieved chunks using BGE-Reranker-v2-m3 cross-encoder.

    Scores each (question, chunk) pair and returns the top_k results sorted by
    relevance descending. Uses pure top-k ranking — raw cross-encoder scores are
    not calibrated to a fixed cutoff, only relative ordering is meaningful.

    Falls back to original order if loading fails.
    """
```

## TypeScript / TSX

```tsx
// pdfjs worker URL must match the installed version exactly — check
// node_modules/pdfjs-dist/package.json
pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/.../pdf.worker.min.mjs`;

// memoized to give Document a stable options reference; a new object each render
// is an infinite reload loop
const pdfOptions = useMemo(() => ({ cMapUrl: "/cmaps/" }), []);
```

- `//`, not `/* */` (except JSDoc on exported types/functions).
- Blank line above a standalone comment block; none between comment and code.
- **Always explain a non-obvious hook dependency or memoization reason** — those are
  exactly the lines a future reader will "clean up" and break.

```tsx
useEffect(() => { loadSources(); }, [apiUrl]);  // re-fetch when API URL changes in settings
```

Exported types earn JSDoc when a field's lifecycle isn't obvious:

```ts
/** Client-side object URL for image thumbnails only — not persisted across reloads. */
previewUrl?: string;
```

---

## Never comment these

```python
x = x + 1
chunks = []
return result
if not chunks:
    return []
```
```tsx
const [isOpen, setIsOpen] = useState(false);
return <div>{children}</div>;
```

If you're about to comment a line like these, rename something instead.
