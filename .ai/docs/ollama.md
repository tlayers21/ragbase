# Ollama Python Client — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: latest (check pyproject.toml for pinned version, `ollama>=0.1.0`)
> Re-fetch when version changes or docs feel stale

---

## Installation

```bash
pip install ollama
```

Ollama application must be running locally (`ollama serve` or the desktop app).

---

## Client Initialization

```python
from ollama import Client, AsyncClient

# Synchronous client
client = Client(
    host="http://localhost:11434",
    headers={"x-some-header": "value"},   # optional extra headers
)

# Async client
async_client = AsyncClient(host="http://localhost:11434")
```

Module-level functions (`ollama.generate()`, `ollama.chat()`, etc.) are also available and use a default client against `http://localhost:11434`.

---

## generate()

```python
def generate(
    model: str,
    prompt: str = '',
    suffix: str = '',
    system: str = '',
    template: str = '',
    context: list[int] = None,
    stream: bool = False,
    think: bool | str = None,
    logprobs: bool = None,
    top_logprobs: int = None,
    raw: bool = None,
    format: str | dict = None,
    images: list[str | bytes] = None,
    options: Options | dict = None,
    keep_alive: float | str = None,
) -> GenerateResponse | Iterator[GenerateResponse]
```

```python
# Non-streaming
response = client.generate(model="qwen3", prompt="Explain photosynthesis briefly.")
print(response.response)

# Streaming
for chunk in client.generate(model="qwen3", prompt="...", stream=True):
    print(chunk.response, end="", flush=True)
```

`think` accepts `True`/`False` or a level string (`'low' | 'medium' | 'high'`) on models that support thinking mode (e.g. qwen3).

---

## Options (generation parameters)

```python
from ollama import Options

# Typed object
options = Options(
    temperature=0.7,
    top_k=50,
    top_p=0.9,
    num_predict=256,   # -1 = unlimited
    seed=42,
    num_ctx=8192,       # context window size
    num_gpu=999,        # GPU layers
    num_thread=8,        # CPU threads
    stop=["###"],
    repeat_penalty=1.1,
)

# Or a plain dict — both are accepted everywhere `options` is a parameter
response = client.generate(model="qwen3", prompt="Hello", options={"temperature": 0.7, "num_ctx": 8192})
```

| Key | Type | Notes |
|-----|------|-------|
| `num_ctx` | int | Context window size (model-specific default) |
| `temperature` | float | 0.0 = deterministic |
| `top_p` | float | Nucleus sampling threshold |
| `top_k` | int | Top-K sampling |
| `num_predict` | int | Max tokens to generate (-1 = unlimited) |
| `repeat_penalty` | float | Penalize repetition |
| `seed` | int | Reproducibility |
| `num_gpu` | int | GPU layers offloaded |
| `num_thread` | int | CPU threads |
| `stop` | list[str] | Stop sequences |

---

## chat()

```python
def chat(
    model: str = '',
    messages: list[dict] | None = None,
    *,
    tools: list = None,
    stream: bool = False,
    think: bool | str = None,
    logprobs: bool = None,
    top_logprobs: int = None,
    format: str | dict = None,
    options: dict | Options = None,
    keep_alive: float | str = None,
) -> ChatResponse | Iterator[ChatResponse]
```

```python
messages = [{"role": "user", "content": "What is Python?"}]
response = client.chat(model="qwen3", messages=messages)
print(response.message.content)

# Multi-turn — append prior assistant turns back into messages
messages.append(response.message)
messages.append({"role": "user", "content": "follow-up"})
response = client.chat(model="qwen3", messages=messages)
```

### Tool calling

Python functions with Google-style docstrings can be passed directly as `tools=[fn]`; Ollama auto-generates the JSON schema. `response.message.tool_calls` holds any calls the model made — call them yourself and feed results back as `{"role": "tool", ...}` messages.

---

## embed()

```python
# Single text
response = client.embed(model="bge-m3", input="text to embed")
embedding = response.embeddings[0]     # list[float]

# Batch
response = client.embed(model="bge-m3", input=["text 1", "text 2"])
embeddings = response.embeddings       # list[list[float]]
```

---

## Vision (multimodal generate)

The `images` parameter accepts base64 strings, raw bytes, file paths, or `Image` objects — no manual base64 handling required if you pass a path:

```python
from ollama import Image

# File path — auto-loaded and encoded
response = client.generate(model="qwen2.5vl", prompt="Describe this image", images=["./photo.jpg"])

# Explicit Image object
response = client.generate(model="qwen2.5vl", prompt="Describe", images=[Image(value="./photo.jpg")])

# Base64 string (also supported)
response = client.generate(model="qwen2.5vl", prompt="Describe", images=[image_b64])
```

---

## Error Handling

```python
from ollama import ResponseError, RequestError

try:
    response = client.generate(model="qwen3", prompt="...")
except ResponseError as e:
    # e.status_code, e.error — e.g. auto-pull on 404
    if e.status_code == 404:
        client.pull("qwen3")
except RequestError:
    # malformed request, e.g. missing model
    ...
```

`ConnectionError` is raised for network-level failures (Ollama not running).

---

## Model Management

```python
client.list()             # list local models
client.show("qwen3")      # ShowResponse — parameters, modelfile, template, capabilities
client.pull("qwen3")      # pull from ollama.com, streamable
client.push(...)          # push to a registry
client.create(...)        # create a model from a Modelfile
client.copy(source, name) # copy a model under a new name
client.delete("qwen3")    # delete local model
client.ps()               # models currently loaded in memory
```

---

## keep_alive

Pass `keep_alive` (seconds or duration string, e.g. `"5m"`) to `generate()`/`chat()` to control how long a model stays loaded in memory after the call. `0` unloads immediately; `-1` keeps it loaded indefinitely.

---
## RAGbase-Specific Notes

- A module-level `Client` lives in `utils/ollama_client.py`, reading `OLLAMA_URL` from `config/settings.py`.
- RAGbase uses `generate()`, not `chat()` — conversation history is manually formatted into the prompt string rather than passed as a message list.
- `generate_stream()` in `utils/ollama_client.py` wraps the streaming `chat()` pattern (not `generate()` — history/system prompt are passed as a `messages` list) and defaults to `get_model("answer")` (qwen3) whenever the caller omits `model=`. In practice only `ml/generate_eval.py` currently relies on that default; every other call site passes `model=` explicitly.
- `embed()`/`embed_batch()` use `ollama.embed(model=..., input=...)`, not the deprecated `ollama.embeddings(model=..., prompt=...)`.
- `embed()` / `embed_batch()` wrap the client's `embed()` call; batches are chunked by `EMBED_BATCH_SIZE=64` from `config/settings.py`. Response-shape handling is tolerant across ollama-python versions.
- `vision()` in `utils/ollama_client.py` and `describe_image()` in `ingestion/helpers.py` wrap the vision `generate()` call; vision calls always set `options={"num_ctx": 8192}` (`OLLAMA_VISION_NUM_CTX`).

### Models Used in RAGbase

| Model | Task | `get_model()` key | Notes |
|-------|------|-------------------|-------|
| `qwen3` | answer, query_rewrite | `"answer"` | Thinking model — verbose by default; also the fallback for any `generate_stream()` call that omits `model=` |
| `qwen2.5:3b` | fact_check, contradiction, summarize, text_cleanup, title, entity_extraction | via `get_model(...)` | Non-thinking, fast |
| `qwen2.5vl` | vision_handwrite, vision_diagram, vision_simple | `"vision_*"` | Requires `num_ctx=8192` |
| `bge-m3` | embeddings | `"embed"` | 1024-dim output |

Always route through `get_model(task)` in `config/models.py`. Never hardcode model name strings.
