# RAGbase

> Local AI knowledge base — chat with your notes, PDFs, and videos.
> Runs entirely on your machine, no cloud APIs required.

![RAGbase screenshot](docs/screenshot.png)

## What it does

RAGbase ingests your documents — notes, PDFs (typed or handwritten), images,
videos, and YouTube links — and lets you chat with all of them at once. Answers
are grounded in your own content with source citations, so you can see exactly
where every claim came from. Everything runs locally through Ollama: your
documents and questions never leave your machine.

## Features

- PDF ingestion (typed and handwritten via VLM transcription)
- Image, video, YouTube, and plain text ingestion
- Hybrid BM25 + vector search with cross-encoder reranking
- Knowledge graph for cross-document concept linking
- Streaming answers with source citations
- Multi-turn chat with context window management
- Dark/light mode, PDF preview, drag-and-drop ingestion

## Requirements

- [Ollama](https://ollama.ai) — local model inference
- Python 3.11+
- Node.js 18+
- Mac (Apple Silicon recommended) or Linux
- Windows via WSL2 should work but is untested

## Quick Start

```bash
git clone https://github.com/tlayers21/ragbase
cd ragbase
bash scripts/install.sh
bash scripts/start.sh
```

## How it works

A FastAPI backend orchestrates ingestion and retrieval. Documents are chunked
and embedded into ChromaDB (embedded, in-process — no server to run), a SQLite
knowledge graph links concepts across documents, and a Next.js frontend
provides the chat UI. All AI — generation, embeddings, vision, reranking —
runs locally through Ollama. No Docker, no internet required after setup.

## Model stack

| Task | Model |
|------|-------|
| Answer generation, query rewriting | qwen3 |
| Fact check, contradiction, summarize, text cleanup, entity extraction | qwen2.5:3b |
| Vision (handwriting, diagrams, images) | qwen2.5vl |
| Embeddings | bge-m3 |
| Reranking | BAAI/bge-reranker-v2-m3 |
| OCR (standalone images) | PaddleOCR |
| OCR (typed PDFs) | RapidOCR via Docling |

## Privacy

RAGbase sends anonymous usage telemetry by default: query latency, source
counts, and a random device ID (e.g. `dev_a3f9b2c1`) that cannot be linked to
you. Your queries, documents, and personal data are **never** sent — they never
leave your machine. You can disable telemetry entirely with the toggle in
Settings.

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
├── utils/         ChromaDB client, Ollama client, cache, telemetry
├── frontend/      Next.js app (TypeScript, Tailwind)
├── scripts/       install.sh, start.sh, reset_all.sh, status.sh
└── data/          Local data: ChromaDB, cache, source files (gitignored)
```

## License

MIT
