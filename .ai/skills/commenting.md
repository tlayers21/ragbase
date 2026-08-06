# RAGbase Commenting Skill

The goal is comments that justify their existence — explaining *why*, never *what*. A well-named function needs no comment. An unusual threshold, a race-condition workaround, or a non-obvious library quirk earns one.

---

## Python: Section Headers

Use a section header above non-obvious blocks to signal a shift in concern. Never use them for every block — only where a reader would stop and wonder "what's going on here?"

```python
# -- Graph build worker -----------------------------------------------------
graph_thread = threading.Thread(target=_run_graph_queue, daemon=True)
graph_thread.start()
```

**Rules:**
- Format: `# -- Section name ----...` — two hyphens, a space, the name, then hyphens padding out to (approximately) the 100-char line length. Regular hyphens only, never em dashes `—`.
- One blank line above the header, none between the header and the code it introduces
- Style reference: `ingestion/queue.py` (see e.g. `# -- Worker ----...`, `# -- Public API ----...`)

---

## Python: Inline Comments

```python
timeout=30 # Concurrent graph thread and queue worker both write to this DB
score = outputs.logits.squeeze(-1).float() # Logits are unbounded; do not softmax
model.transcribe(audio_path, fp16=False) # fp16 path has known MPS issues
collection.query(where={"$and": [...]}) # Multi-field filter requires explicit $and
RERANKER_MIN_SCORE = -8.0 # Empirically tuned - below this, chunks add noise
```

**Rules:**
- One space before `#`: `code # comment` — actually just one space before the `#`
- Capitalize first letter in the comment unless it's referencing a parameter or something that should be lowercase
- No period at end of inline comments
- No em dash (—)
- Explain *why*, not *what* — the code already says what

**Deserves a comment:**
- Non-obvious threshold or timeout value (why this number?)
- A library workaround or known gotcha being handled
- Race condition or concurrency guard
- Surprising control flow (why is this returning early here?)
- Non-obvious math or bit operation

**Does NOT deserve a comment:**
```python
result = pipeline.forward(question, chunks) # Run the pipeline   ← NO
return result # Return the result  ← NO
user_id = get_user_id() # Get user id        ← NO
```

---

## Python: Docstrings

Use a one-line docstring on public functions when the function name alone doesn't fully capture the contract:

```python
def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches of EMBED_BATCH_SIZE to avoid OOM on large inputs."""
    ...
```

Skip the docstring if the name + type hints are self-documenting:

```python
def get_user_id() -> str:
    ...  # no docstring needed
```

Never write multi-paragraph or multi-line docstrings. One sentence max.

---

## TypeScript / TSX: Inline Comments

```tsx
// pdfjs worker URL must match exact installed version — check node_modules/pdfjs-dist/package.json
pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/.../pdf.worker.min.mjs`

// options must be memoized — new object reference on every render triggers infinite reload loop
const pdfOptions = useMemo(() => ({}), [])

// abort any in-flight stream before starting a new one; 100ms lets the previous reader tear down
await abortAndWait()
```

**Rules:**
- Use `//` comments, not `/* */` (except for JSDoc on exported functions)
- Same principle: *why*, not *what*
- One blank line above a standalone comment block, not between comment and code

**Hook dependency arrays** — always explain a non-obvious dependency choice:

```tsx
useEffect(() => {
  loadSources()
}, [apiUrl])  // re-fetch when user changes API URL in settings
```

**useCallback / useMemo** — comment when the memoization reason isn't obvious:

```tsx
// memoized to give Document a stable options reference; new object = reload loop
const pdfOptions = useMemo(() => ({ cMapUrl: '/cmaps/' }), [])
```

---

## What Never Gets a Comment

```python
x = x + 1
chunks = []
logger.info(f"Processing {source}")
return result
if not chunks:
    return []
```

```tsx
const [isOpen, setIsOpen] = useState(false)
return <div>{children}</div>
onClick={() => setIsOpen(true)}
```

If you're writing a comment on a line like these, stop and ask whether the variable or function could be renamed to make the comment unnecessary instead.
