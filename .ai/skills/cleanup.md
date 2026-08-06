# RAGbase Cleanup Skill

Periodic code quality audit. Run after a large feature lands, before a release commit, or when the codebase feels cluttered. The goal is reduction — less code is better code.

---

## When to Run

- After a large feature addition (new ingestor, new query mode, new UI panel)
- Before a major commit or release tag
- When you notice repeated patterns across 2+ files
- When a module has grown past ~300 lines

---

## What to Look For

### Dead Code

**Python:**
```bash
# Unused imports
ruff check . --select F401

# Find functions defined but never called (manual grep)
grep -rn "^def " . --include="*.py" | grep -v test
```

Check each function — is it called anywhere? Is it part of a public interface that might be called externally? If neither, delete it.

**TypeScript:**
```bash
# TypeScript compiler will flag unused locals if strict
cd frontend && npx tsc --noEmit
```

Look for:
- Imports that are listed but not used in the file
- Props defined in an interface but never accessed in the component
- `const foo = ...` where `foo` is never referenced

**Commented-out code:**
```python
# result = old_reranker(chunks)   ← delete this
# model = llava  ← delete this
```
Commented-out code is not documentation. If it was removed for a reason, trust the reason. If it might come back, use git — not inline comments.

---

### Repetitive Logic

Same pattern in 2+ places → extract to a shared function.

**Python example — repeated Ollama call pattern:**
```python
# If you see this in multiple files:
response = client.generate(model=get_model("text_cleanup"), prompt=prompt, system=system)
return response.response.strip()

# Extract to utils/ollama_client.py
def generate_text(task: str, prompt: str, system: str | None = None) -> str:
    response = client.generate(model=get_model(task), prompt=prompt, system=system)
    return response.response.strip()
```

**TypeScript example — repeated fetch pattern:**
```tsx
// If you see the same fetch + error handling in multiple hooks,
// extract to lib/api.ts as a typed helper
```

Similar API endpoint calls with the same shape: abstract into a shared function in `lib/api.ts`.

Duplicate TypeScript type definitions: consolidate into a single `types.ts` or colocate with the hook that owns them.

---

### Over-Complex Logic

**Functions over ~50 lines** — a strong signal that the function is doing two things. Split at natural seams:

```python
# Before: one 80-line extract() that does detection + extraction + cleanup
# After:
def _detect_type(doc) -> str: ...         # ~10 lines
def _extract_typed(doc) -> str: ...       # ~30 lines
def _extract_handwritten(doc) -> str: ... # ~30 lines
def extract(doc) -> str:                  # ~10 lines, dispatches
    ...
```

**Deeply nested if/else** — flatten with early returns:

```python
# Before
if condition_a:
    if condition_b:
        if condition_c:
            do_thing()

# After
if not condition_a:
    return
if not condition_b:
    return
if not condition_c:
    return
do_thing()
```

**Too many parameters (4+)** — consider a dataclass or TypedDict:

```python
# Before
def store_chunk(text, source, user_id, page_no, chunk_idx, embedding, metadata):

# After
@dataclass
class ChunkData:
    text: str
    source: str
    user_id: str
    page_no: int
    chunk_idx: int
    embedding: list[float]
    metadata: dict

def store_chunk(chunk: ChunkData): ...
```

**Complex one-liners** — break them out if they require a comment to understand:

```python
# If you need a comment to explain a one-liner, the one-liner is too complex
scores = [s for s, c in zip(raw_scores, chunks) if s >= threshold and c.strip()]

# Clearer:
filtered = [
    (score, chunk)
    for score, chunk in zip(raw_scores, chunks)
    if score >= threshold and chunk.strip()
]
scores = [s for s, _ in filtered]
```

---

### Missing Comments (add these)

After a cleanup pass, check for:
- Functions with non-obvious behavior and no docstring
- Magic numbers with no explanation:
  ```python
  timeout=30      # needs: concurrent graph thread + queue worker both write here
  threshold=0.7   # needs: cosine distance above this → source is off-topic
  ```
- Complex regex with no explanation of what it matches
- Concurrency guards with no explanation of what race they prevent

Read `.ai/skills/commenting.md` for comment style rules.

---

## After Cleanup

Always run in this order:

```bash
# 1. Python lint + format
source .venv/bin/activate && ruff format . && ruff check . --fix

# 2. TypeScript type check
cd frontend && npx tsc --noEmit && cd ..

# 3. Smoke test — verify the app still starts
bash scripts/start.sh
```

If the app fails to start after cleanup, the cleanup broke something. Investigate before committing.

---

## What NOT to Touch During Cleanup

- `data/` — protected, never edit
- `docs/CODEBASE_EXPLAINED.md` — generated, never edit manually
- `scripts/metrics.*` — protected
- `frontend/.next/` — generated build artifacts
- The `QueryRewriter` class in `retrieval/pipeline.py` — kept intentionally (ml/ scripts use it even though forward() doesn't call it)
