# OpenAI Whisper (openai-whisper 20250625) — RAGbase Reference

> Fetched via Context7 — 2026-08-06
> Version: 20250625 (date-versioned package)
> Re-fetch when version changes or docs feel stale

## Installation

```bash
pip install openai-whisper
# Requires ffmpeg:
brew install ffmpeg       # macOS
```

---

## Model Sizes

| Name | Parameters | English-only variant | Multilingual | VRAM | Speed vs large |
|------|-----------|---------------------|--------------|------|----------------|
| `tiny` | 39M | `tiny.en` | `tiny` | ~1GB | ~10x |
| `base` | 74M | `base.en` | `base` | ~1GB | ~7x |
| `small` | 244M | `small.en` | `small` | ~2GB | ~4x |
| `medium` | 769M | `medium.en` | `medium` | ~5GB | ~2x |
| `large` | 1550M | — | `large` | ~10GB | 1x (baseline) |
| `turbo` | 809M | — | `turbo` | ~6GB | ~8x |

`turbo` does not support translation tasks. For non-English → English translation, use `medium` or `large`.

---

## Loading a Model

```python
import whisper

model = whisper.load_model("base")                   # CPU (default device resolution)
model = whisper.load_model("base", device="mps")     # Apple Silicon
model = whisper.load_model("base", device="cuda")    # NVIDIA GPU
model = whisper.load_model("base", download_root="/path/to/cache")
model = whisper.load_model("base", in_memory=True)   # don't write cache to disk
```

`load_model()` signature:

```python
def load_model(
    name: str,
    device: Optional[Union[str, torch.device]] = None,
    download_root: str = None,
    in_memory: bool = False,
) -> Whisper:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if download_root is None:
        default = os.path.join(os.path.expanduser("~"), ".cache")
        download_root = os.path.join(os.getenv("XDG_CACHE_HOME", default), "whisper")
```

Note: the library's own default device resolution only checks CUDA, falling back to CPU — it does not auto-detect MPS. Callers on Apple Silicon must pass `device="mps"` explicitly.

---

## `model.transcribe()`

```python
result = model.transcribe(
    audio,                              # str path or numpy array
    verbose=False,                      # False = suppress per-segment output
    fp16=False,                         # see "Critical: fp16" below
    language=None,                      # auto-detect; or "en", "ja", "zh", etc.
    task="transcribe",                  # "transcribe" or "translate" (to English)
    temperature=0.0,                    # 0.0 = greedy (deterministic)
    best_of=5,                          # candidates at non-zero temperature
    beam_size=5,                        # beam search size (None = greedy)
    patience=None,                      # beam search patience
    compression_ratio_threshold=2.4,    # flag hallucination if ratio > this
    logprob_threshold=-1.0,             # flag low-confidence if avg logprob < this
    no_speech_threshold=0.6,            # silence detection threshold
    condition_on_previous_text=True,    # use previous segment as context
    initial_prompt=None,                # str to prime decoding
    word_timestamps=False,              # include word-level timestamps
    suppress_tokens="-1",               # token IDs to suppress
    suppress_blank=True,                # suppress blank outputs
)
```

The CLI's `--fp16` flag defaults to `True` (accepts `"True"`/`"False"` strings via `str2bool`); the Python API's `fp16` kwarg on `transcribe()` mirrors this and also defaults to `True`. `transcribe()` forces fp32 automatically on CPU regardless of the flag.

---

## Result Format

```python
result = {
    "text": "Full transcription as a single string with leading space.",
    "segments": [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,          # seconds
            "end": 4.2,            # seconds
            "text": " First segment text.",
            "tokens": [50364, ...],
            "temperature": 0.0,
            "avg_logprob": -0.28,
            "compression_ratio": 1.53,
            "no_speech_prob": 0.009,
        },
        # ...
    ],
    "language": "en",
}
```

---

## Critical: `fp16=False`

```python
result = model.transcribe(audio_path, fp16=False)
```

Whisper's fp16 inference path has known issues on MPS; forcing `fp16=False` sidesteps them on any device (`transcribe()` also silently forces fp32 on CPU regardless of the flag, but MPS does not get that auto-correction).

---

## Supported Audio Formats

Whisper shells out to ffmpeg internally and accepts: `.mp3`, `.wav`, `.flac`, `.ogg`, `.m4a`, `.mp4`, `.mkv`, `.webm`, `.avi`, `.mov`. For video files, ffmpeg extracts the audio track automatically.

---

## Low-Level API

```python
import whisper

model = whisper.load_model("turbo")

# load audio and pad/trim it to fit 30 seconds
audio = whisper.load_audio("audio.mp3")
audio = whisper.pad_or_trim(audio)

# make log-Mel spectrogram and move to the same device as the model
mel = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels).to(model.device)

# detect the spoken language
_, probs = model.detect_language(mel)
print(f"Detected language: {max(probs, key=probs.get)}")

# decode the audio
options = whisper.DecodingOptions(fp16=False, language="en")
result = whisper.decode(model, mel, options)
print(result.text)
```

---

## RAGbase-Specific Notes

- `ingestion/helpers.py::transcribe()` loads Whisper `"base"` (not `"small"` — verify against current code if this drifts), with `device="mps"` when available, falling back to CPU.
- `fp16=False` is always passed to `.transcribe()` regardless of device — this is a deliberate RAGbase convention working around Whisper's known MPS fp16 issues, not the library default.
- RAGbase uses only the high-level `model.transcribe()` API — the low-level `load_audio`/`pad_or_trim`/`log_mel_spectrogram`/`decode` functions are not used.
- RAGbase reads only `result["text"].strip()` from the result dict — segments/language are not consumed.

**RAGbase device detection pattern:**

```python
import torch

def get_whisper_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
```

**RAGbase `transcribe()` pattern** (`ingestion/helpers.py`):

```python
def transcribe(audio_path: str) -> str:
    import torch
    import whisper

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = whisper.load_model("base", device=device)
    result = model.transcribe(audio_path, fp16=False, verbose=False)
    return result["text"].strip()
```

Check `ingestion/helpers.py` for whether the model is cached at module level to avoid reloading on every file.
