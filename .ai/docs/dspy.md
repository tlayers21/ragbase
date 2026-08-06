# DSPy — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 3.2.1 (per pyproject.toml: dspy>=2.0.0)
> Re-fetch when version changes or docs feel stale

---

## LM Configuration

```python
import dspy

lm = dspy.LM(
    model="ollama/qwen3",          # "llm_provider/llm_name" form, resolved via LiteLLM
    api_base="http://localhost:11434",
    max_tokens=4096,
    temperature=0.0,
    cache=True,                    # default True — caches identical calls
)
dspy.configure(lm=lm)
```

**`dspy.LM` parameters:**
- `model` (str, required) — `"llm_provider/llm_name"`, e.g. `"ollama/qwen3"`, `"openai/gpt-4o"`
- `model_type` (`"chat" | "text" | "responses"`) — defaults to `"chat"`
- `temperature` (float | None)
- `max_tokens` (int | None)
- `cache` (bool) — defaults to `True`
- `callbacks` (list[BaseCallback] | None)
- `num_retries` (int) — defaults to 3, exponential backoff on transient failures
- `provider` (Provider | None) — inferred from `model` if omitted
- `rollout_id` — differentiates cache entries for otherwise-identical requests (only affects generation when `temperature != 0`)

### Per-Module LM Override

```python
# Recursively set LM on every Predict instance in a module tree
program = dspy.Predict("question -> answer")
program.set_lm(lm)

# Or assign directly to a single predictor's .lm attribute
fast_lm = dspy.LM(model="ollama/qwen2.5:3b", api_base="http://localhost:11434")

class MyModule(dspy.Module):
    def __init__(self):
        self.cleaner = dspy.Predict(TextCleanup)
        self.cleaner.lm = fast_lm    # assign directly to .lm attribute
```

`Module.get_lm()` retrieves the LM if all predictors in the module agree on a single one; raises `ValueError` on a mix — useful as a sanity check before fine-tuning/saving.

**Avoid** `with dspy.context(lm=...)` in concurrent FastAPI handlers — it's not thread-safe. Assign `.lm` on the predictor instance (or call `set_lm()`) instead.

---

## Defining Signatures

```python
class BasicQA(dspy.Signature):
    """Answer questions with short factoid answers."""

    question: str = dspy.InputField()
    answer: str = dspy.OutputField(desc="often between 1 and 5 words")
```

- Docstring → system/task instruction sent to the LM
- `InputField(desc=...)` / `OutputField(desc=...)` → per-field guidance
- Type annotations → used for validation and schema

**String shorthand** (for simple cases):
```python
summarize = dspy.Predict("document -> summary")
rewrite = dspy.ChainOfThought("question -> rewritten_question")
```

---

## Predict

```python
dspy.Predict(signature: str | type[Signature], callbacks: list[BaseCallback] | None = None, **config)
```

Initializes a module that maps inputs to outputs via the LM according to `signature`. `**config` are default LM kwargs (temperature, max_tokens, rollout_id, etc.) that can be overridden per-call via a `config=` dict:

```python
predict = dspy.Predict("q -> a", rollout_id=1, temperature=1.0)
result = predict(q="What is 1 + 52?", config={"rollout_id": 2, "temperature": 1.0})
print(result.a)     # field name matches OutputField name
```

**Key methods:**
- `forward(**kwargs)` / `__call__(**kwargs)` — run prediction, returns `Prediction`
- `aforward(**kwargs)` — async version
- `batch(examples)` — parallel processing of multiple `dspy.Example` instances
- `reset()` — clear traces, demos, and LM assignment
- `dump_state()` / `load_state()` — serialize/restore
- `inspect_history(n=1)` — show recent LM calls for debugging

---

## ChainOfThought

```python
dspy.ChainOfThought(
    signature: str | type[Signature],
    rationale_field: FieldInfo | None = None,
    rationale_field_type: type = str,
    **config,
)
```

Injects a `reasoning` output field before the actual outputs, asking the model to think step by step before answering. Costs more tokens but improves reliability on complex tasks.

```python
cot = dspy.ChainOfThought(signature)
result = cot(context=["..."], question="What is X?")
print(result.reasoning)  # intermediate reasoning trace
print(result.answer)     # final answer
```

---

## Module Definition

```python
class RAGPipeline(dspy.Module):
    def __init__(self):
        self.answerer = dspy.Predict(RAGAnswerer)
        self.cleaner = dspy.Predict(TextCleanup)
        self.cleaner.lm = dspy.LM(
            model="ollama/qwen2.5:3b",
            api_base="http://localhost:11434",
        )

    def forward(self, question: str, context: list[str]) -> dspy.Prediction:
        cleaned = [self.cleaner(raw_text=c).cleaned_text for c in context]
        return self.answerer(context=cleaned, question=question)
```

---

## Signatures Used in RAGbase

| Signature | Module | LM | Location |
|-----------|--------|----|----------|
| `RAGAnswerer` | `Predict` | qwen3 | `retrieval/pipeline.py` |
| `TextCleanup` | `Predict` | qwen2.5:3b | `retrieval/pipeline.py` |
| `TranscriptionRefinement` | `Predict` | qwen2.5:3b | `retrieval/pipeline.py` |
| `QueryRewriter` | `Predict` | qwen3 | `retrieval/pipeline.py` — **defined but NOT called in `forward()`** |

All four current signatures use `dspy.Predict` — **no `dspy.ChainOfThought` is currently in use** anywhere in RAGbase (a prior version of this doc incorrectly showed `RAGAnswerer` on `ChainOfThought`; corrected per `.ai/instructions.md`).

`QueryRewriter` is kept because `ml/eval.py` and `ml/collect_pairs.py` reference `pipeline.rewriter` directly. Do not remove it.

---

## RAGbase-Specific Notes

- RAGbase configures the global LM once in `main.py` lifespan (`configure_dspy()`), defaulting to `qwen3`.
- `TextCleanup` and `TranscriptionRefinement` are routed to `qwen2.5:3b` via direct `.lm` assignment on the predictor instance, while the global default LM stays `qwen3`.
- **No `api_key=""`** — omit the argument entirely in DSPy 3.x with Ollama; passing an empty string can cause auth errors.
- **`qwen3` + `dspy.Predict`** can produce `AdapterParseError` — the thinking model's `<think>` blocks can break the output parser. If this happens for a given signature, switch that signature to `dspy.ChainOfThought`. `qwen2.5:3b` is non-thinking and stays on `dspy.Predict`.
- **`with dspy.context(lm=...)`** is thread-unsafe in concurrent FastAPI handlers — use `.lm` assignment (or `set_lm()`) on the predictor/module instance instead.
- **DSPy is synchronous** — RAGbase does not use DSPy for streaming generation. Streaming tokens come from `utils/ollama_client.py::generate_stream()` directly, not through a DSPy call.
- All DSPy signatures in RAGbase live **only** in `retrieval/pipeline.py`.
