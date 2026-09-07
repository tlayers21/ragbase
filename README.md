# RAGbase

> Local AI knowledge base - chat with your notes, PDFs, and videos.
> Runs entirely on your machine, no cloud APIs required.

![RAGbase screenshot](docs/screenshot.png)

## What it does

RAGbase ingests your documents - notes, PDFs (typed or handwritten), Word and
PowerPoint files, spreadsheets, e-books, images, videos, and YouTube links - and
lets you chat with all of them at once. Answers are grounded in your own content
with source citations, so you can see exactly where every claim came from.
Everything runs locally through Ollama: your documents and questions never leave
your machine.

## Features

- PDF ingestion (typed and handwritten via VLM transcription)
- Word, PowerPoint, Excel, OpenDocument, RTF, CSV and EPUB ingestion
- Image, video, YouTube, and plain text ingestion
- Hybrid keyword + semantic search, so exact terms like error codes still match
- Knowledge graph for cross-document concept linking
- Streaming answers with source citations, and a relevance floor you can tune
- "Explain in depth" - a whole-document walkthrough of any source, on demand
- Fact checking and contradiction detection -- ask RAGbase to grade a document
  against the model's general knowledge, or against everything else you have
  ingested, and read the findings chunk by chunk
- Direct chat - deselect every source to use it as a plain local chat client
- Multi-turn chat with context window management
- Clipboard paste - images and long text automatically become attachments
- Dark/light mode, PDF preview, drag-and-drop ingestion

## Requirements

- Mac (Apple Silicon recommended) or Linux
- Windows via WSL2 should work but is untested
- **[Ollama](https://ollama.ai/download)** - local model inference engine
- **Python 3.13+** - [python.org](https://www.python.org/downloads/)
- **Node.js 18+** - [nodejs.org](https://nodejs.org/)
- **ffmpeg** - decodes audio for video and YouTube ingestion
- **poppler** - rasterises pages for scanned and handwritten PDFs

`install.sh` checks for all of these and stops if any is missing. For the last two:

```bash
brew install ffmpeg poppler # Mac
sudo apt install ffmpeg poppler-utils # Debian/Ubuntu
```

## Setup

### 1. Install Ollama

Download and install Ollama from [ollama.ai/download](https://ollama.ai/download).

On Mac, drag it to Applications and launch it. You should see the Ollama icon in your menu bar.

On Linux:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Install Python 3.13+

Check if you already have it:
```bash
python3 --version
```

If not, download from [python.org](https://www.python.org/downloads/) or on Mac via Homebrew:
```bash
brew install python@3.13
```

### 3. Install Node.js 18+

Check if you already have it:
```bash
node --version
```

If not, download from [nodejs.org](https://nodejs.org/) or on Mac via Homebrew:
```bash
brew install node
```

### 4. Clone and install RAGbase

```bash
git clone https://github.com/tlayers21/ragbase
cd ragbase
bash scripts/install.sh
```

`install.sh` will:
- Check all prerequisites are installed
- Pull all required Ollama models (~14GB total, one-time download)
- Set up the Python virtual environment and install dependencies
- Install frontend dependencies and build the production frontend

This takes 20-40 minutes on first run depending on your internet speed - mostly
waiting for model downloads.

### 5. Start RAGbase

```bash
bash scripts/start.sh
```

This starts the backend and frontend, then opens your browser to `localhost:3000`.
On subsequent runs `start.sh` checks for updates automatically and only rebuilds
the frontend if something changed, so the *scripts* return fast. The app itself
still shows a loading screen for 15-20 seconds on every launch while it loads
models into memory - this is normal, not a hang.

## Updating

```bash
git pull origin main
bash scripts/start.sh
```

`start.sh` handles pulling updates and rebuilding automatically on each launch.

## How it works

A FastAPI backend orchestrates ingestion and retrieval. Documents are chunked
and embedded into ChromaDB (embedded, in-process - no server to run), a SQLite
knowledge graph links concepts across documents, and a Next.js frontend
provides the chat UI. All AI - generation, embeddings, vision, reranking -
runs locally through Ollama. No Docker, no internet required after setup.

## Model stack

| Task | Model | Size |
|------|-------|------|
| Answer generation | `qwen3` | 5.2 GB |
| Summaries, titles, entity extraction, text cleanup, fact checking, contradiction detection | `qwen2.5:3b` | 1.9 GB |
| Vision - handwriting, diagrams, images | `qwen2.5vl` | 6.0 GB |
| Embeddings | `bge-m3` | 1.2 GB |
| Reranking | `BAAI/bge-reranker-v2-m3` | ~2 GB |
| Audio transcription | Whisper base | ~150 MB |
| OCR (standalone images) | PaddleOCR | small |
| OCR (scanned PDF fallback) | RapidOCR via Docling | small |

Typed PDFs and office formats use no OCR and no model at all - they go through
`anydoc`, a pure-Rust text converter, which is why they finish in seconds.

**Total model footprint: ~17GB** - ~14GB of Ollama models pulled by `install.sh`, plus
the reranker (~2GB) and Whisper (~150MB), which download on first use.

## Hardware

Apple Silicon (M1/M2/M3/M4) is strongly recommended - all models run on the
MPS GPU which is significantly faster than CPU. Intel Mac and Linux with an
Nvidia GPU also work well. CPU-only will work but responses will be slow
(30-120 seconds per query depending on hardware).

Minimum recommended: 16GB RAM. 24GB+ for comfortable use with all models loaded.

## Privacy

**RAGbase sends nothing anywhere.** Your queries, documents, and personal data
never leave your machine.

There is an optional telemetry hook in the code, which the author uses to collect
query latency and source counts from their own machines. It needs a collection
endpoint set in a local `.env` file, which no clone has, so it is inert: nothing
is sent and no request is made. **Settings -> Send anonymous usage telemetry** is
a second switch over the same thing.

## Resetting

To wipe all ingested data and start fresh:
```bash
bash scripts/reset_all.sh
```

This clears ChromaDB, the knowledge graph, the semantic cache, all source files,
and chat history. Models are not affected.

## Directory structure

```
ragbase/
├── main.py        FastAPI entry point and startup lifecycle
├── config/        Settings, model routing, paths, logging
├── ingestion/     PDF/image/video/YouTube/text ingestors + job queue
├── retrieval/     Hybrid search, reranker, knowledge graph, DSPy pipeline
├── analysis/      Fact checking and contradiction detection
├── api/           FastAPI routers (ingest, query, documents, settings, ...)
├── ml/            Eval and fine-tuning scripts
├── metrics/       Offline retrieval eval harness (recall@5, MRR)
├── utils/         ChromaDB client, Ollama client, cache, telemetry
├── frontend/      Next.js app (TypeScript, Tailwind)
├── scripts/       install.sh, start.sh, reset_all.sh, status.sh
└── data/          Local data: ChromaDB, cache, source files (gitignored)
```

## License

MIT