# Transformers — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: check pyproject.toml (pinned `transformers>=4.30.0`; RAGbase runs on a much newer release — see `uv.lock`), used for BGE-Reranker-v2-m3 in `retrieval/reranker.py`
> Re-fetch when version changes or docs feel stale

---

## Model & Tokenizer Loading (AutoClass API)

The AutoClass API automatically infers the correct architecture/framework from the model weights or config and is the recommended way to load models and preprocessors.

```python
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

model_name = "BAAI/bge-reranker-v2-m3"

tokenizer = AutoTokenizer.from_pretrained(model_name)

model = AutoModelForSequenceClassification.from_pretrained(
    model_name,
    torch_dtype=torch.float32,   # or dtype="auto" to infer from checkpoint
    # device_map="auto",         # automatic multi-device dispatch
)
```

### `AutoTokenizer.from_pretrained()` key params

| Param | Type | Notes |
|-------|------|-------|
| `pretrained_model_name_or_path` | str | Hub model ID or local path |
| `cache_dir` | str | Custom cache directory (default `~/.cache/huggingface/hub/`) |
| `force_download` | bool | Re-download even if cached |
| `revision` | str | Git branch/tag/commit, default `"main"` |
| `trust_remote_code` | bool | Allow custom tokenizer code from the Hub |

### `AutoModelForSequenceClassification.from_pretrained()` key params

| Param | Type | Notes |
|-------|------|-------|
| `pretrained_model_name_or_path` | str | Hub model ID or local path |
| `torch_dtype` / `dtype` | `torch.dtype` \| `"auto"` | Newer docs favor the `dtype=` alias; `torch_dtype=` still accepted |
| `device_map` | str \| dict | `"auto"` dispatches weights across available devices automatically (big-model inference) |
| `num_labels` | int | Classification head size when initializing from a base checkpoint |
| `cache_dir` / `force_download` | | Same as tokenizer |

---

## Device Placement

```python
def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")

device = get_device()
model = model.to(device)
model.eval()   # disable dropout, set batch norm to eval mode
```

`device_map="auto"` is the library's own recommended way to place large models across devices automatically; explicit `.to(device)` remains valid for single-device inference and is what the manual-control examples in the official docs use for classification models.

---

## Tokenization

```python
inputs = tokenizer(
    [[query, candidate]],       # list of [text_a, text_b] pairs for cross-encoder-style inputs
    padding=True,                # or "longest" / "max_length"
    truncation=True,
    max_length=512,
    return_tensors="pt",
)
# inputs: {"input_ids": Tensor, "attention_mask": Tensor}
inputs = {k: v.to(device) for k, v in inputs.items()}
# or, in one step:
inputs = tokenizer([[query, candidate]], padding=True, truncation=True, max_length=512,
                    return_tensors="pt").to(model.device)
```

`padding=True` pads to the longest sequence in the batch; `padding="max_length"` pads every sequence to `max_length`. Combine with `truncation=True` for a rectangular tensor output regardless of input length.

---

## Forward Pass / Inference

```python
with torch.no_grad():           # disable gradient computation for inference
    outputs = model(**inputs)

outputs.logits                  # Tensor[batch_size, num_labels]
outputs.loss                    # None (no labels provided)
outputs.hidden_states            # None unless output_hidden_states=True
```

For standard classification heads with `num_labels > 1`, the documented pattern applies softmax and argmax:

```python
predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
predicted_class = torch.argmax(predictions, dim=-1)
```

**BGE-Reranker-v2-m3 is a single-logit cross-encoder**, not a multi-class classifier — it does not follow the softmax pattern above:

```python
scores = outputs.logits.squeeze(-1).float().tolist()   # list[float], one score per pair
```

---

## Batched Cross-Encoder Reranking Pattern

```python
def rerank(query: str, candidates: list[str]) -> list[float]:
    pairs = [[query, c] for c in candidates]

    inputs = tokenizer(
        pairs, padding=True, truncation=True, max_length=512, return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        outputs = model(**inputs)

    return outputs.logits.squeeze(-1).float().tolist()
```

---
## RAGbase-Specific Notes

- **Always use `float32` on MPS** — `bfloat16` causes NaN in BGE-Reranker forward passes; RAGbase pins `torch_dtype=torch.float32` explicitly rather than using `dtype="auto"`.
- RAGbase places the model with an explicit `get_device()` → `.to(device)` call rather than `device_map="auto"`, since it's a single model on a single machine (no multi-GPU dispatch needed).
- BGE-Reranker-v2-m3 outputs a **single logit per pair** (not a 2-class softmax) — access via `outputs.logits.squeeze(-1).float().tolist()`.
- **Score interpretation**: raw logits, unbounded, approximate range −10 to +8. Higher = more relevant. Do NOT softmax — use raw logits directly for ranking. RAGbase threshold: `RERANKER_MIN_SCORE = -8.0` (drops chunks below this).

```python
RERANKER_MIN_SCORE = -8.0
chunks_with_scores = list(zip(chunks, scores))
filtered = [(c, s) for c, s in chunks_with_scores if s >= RERANKER_MIN_SCORE]
ranked = sorted(filtered, key=lambda x: x[1], reverse=True)
```

- **Batched forward pass with fallback**: RAGbase does all pairs in one batched forward pass, then falls back to a per-item loop if the batch call raises, and falls back further to original order (score 1.0) if the model fails to load at all:

```python
try:
    scores = rerank_batch(query, candidates)
except Exception:
    scores = [rerank_single(query, c) for c in candidates]
```

- **Model warmup on startup** (`main.py` lifespan) — avoids cold-start latency on first real request:

```python
dummy = tokenizer([["warmup query", "warmup document"]], return_tensors="pt",
                   padding=True, truncation=True).to(device)
with torch.no_grad():
    _ = model(**dummy)
```

- Memory footprint: BGE-Reranker-v2-m3 (float32) is ~560 MB, loaded once on startup and kept in memory for the process lifetime. Loaded fresh from HuggingFace each run — no local fine-tuned checkpoint is currently used, even though `config/paths.py::RERANKER_MODEL_PATH` (`models/reranker_model.pt`) exists as a path for one.
- **huggingface-hub version gotcha**: `uv run` / `uv sync` can upgrade `huggingface-hub` past 1.0, which breaks `transformers`. Fix: `uv pip install "huggingface-hub<1.0"`. Always invoke Python directly rather than via `uv run`:

```bash
python3 -m uvicorn main:app ...    # correct
uv run uvicorn main:app ...        # may silently break transformers
```
