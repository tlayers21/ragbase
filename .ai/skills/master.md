# RAGbase Master Skill

You are working on RAGbase — a local AI knowledge base built with FastAPI, ChromaDB
(embedded), SQLite, DSPy, and Next.js. All AI inference runs locally via Ollama.

## Always do first

1. Read `.ai/instructions.md` — this is the canonical project context (directory structure,
   conventions, model stack, API endpoints, gotchas). `.github/copilot-instructions.md` is
   just a pointer to it.
2. If `docs/CODEBASE_EXPLAINED.md` exists and the task involves understanding
   existing code — read it.

## Load additional skills based on the task

| If the task involves... | Read this skill |
|------------------------|-----------------|
| Updating README.md | `.ai/skills/update-readme.md` |
| Updating `.ai/instructions.md` | `.ai/skills/update-instructions.md` |
| Generating CODEBASE_EXPLAINED.md | `.ai/skills/explain-codebase.md` |
| Frontend work | `.ai/skills/frontend.md` |
| Backend/Python work | `.ai/skills/backend.md` |

## Always do after changes

- Python changed → `source .venv/bin/activate && ruff format . && ruff check . --fix`
- TypeScript changed → `cd frontend && npx tsc --noEmit && cd ..`
- New endpoint → update the API Endpoints section of `.ai/instructions.md`

## Never edit autonomously

- `data/`, `docs/CODEBASE_EXPLAINED.md`, `scripts/metrics.*`
- `frontend/.next/`, `data/user_id.txt`, `data/device_id.txt`

## MCP config note
If you add a new MCP server, update both `.vscode/mcp.json` AND
`.claude/mcp.json` to keep them in sync.

## Using Context7 for live library docs
When working with any library in this project, prefix your prompt with
"use context7" to get accurate current documentation rather than relying
on training data. For libraries used frequently, cached docs are in
`.ai/docs/` — read those first before fetching via Context7.

| Library | Cached docs | Re-fetch when |
|---------|-------------|---------------|
| ChromaDB | `.ai/docs/chromadb.md` | Version upgrade |
| FastAPI | `.ai/docs/fastapi.md` | Version upgrade |
| DSPy | `.ai/docs/dspy.md` | Version upgrade |
| Ollama | `.ai/docs/ollama.md` | Version upgrade |
| Docling | `.ai/docs/docling.md` | Version upgrade |
| Transformers | `.ai/docs/transformers.md` | Version upgrade |
| PyMuPDF | `.ai/docs/pymupdf.md` | Version upgrade |
| Whisper | `.ai/docs/whisper.md` | Version upgrade |
| react-pdf | `.ai/docs/react-pdf.md` | Version upgrade |
| Next.js | `.ai/docs/nextjs.md` | Version upgrade — this project pins a Next.js version with breaking changes from typical training data; also read `frontend/AGENTS.md` |
| react-markdown | `.ai/docs/react-markdown.md` | Version upgrade |
| KaTeX | `.ai/docs/katex.md` | Version upgrade |
