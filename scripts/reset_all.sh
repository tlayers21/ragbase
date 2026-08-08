#!/bin/bash
# Wipe every piece of RAGbase runtime state, keeping identity and config.
# Run from anywhere: bash scripts/reset_all.sh
set -e

# Every path below is relative, and several are `rm -rf`. Anchor to the project
# root so running this from another directory can't delete the wrong tree.
cd "$(dirname "$0")/.."

echo "=== RAGbase Full Reset ==="

# 0. Kill all RAGbase-related processes
# Must cover everything scripts/start.sh starts, plus the dev-loop equivalents
# from §11 of .ai/instructions.md (`python3 -m uvicorn`, `npm run dev`).
echo "Stopping all RAGbase processes..."
pkill -f "npm run dev" 2>/dev/null || true
pkill -f "npm start" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
pkill -f "uvicorn main:app" 2>/dev/null || true
lsof -ti :8001 | xargs kill -9 2>/dev/null || true
lsof -ti :3000 | xargs kill -9 2>/dev/null || true
echo "All processes stopped"

# 1. Clear embedded ChromaDB storage (both user_{id} and user_{id}_summaries live here)
echo "Clearing ChromaDB data..."
rm -rf data/chromadb && mkdir -p data/chromadb
echo "ChromaDB data cleared"

# 2. Clear knowledge graph. The -shm/-wal companions matter: both SQLite DBs run
#    in WAL mode, so deleting only the .db leaves committed data in the -wal file
#    that SQLite would replay into the "fresh" database on next open.
echo "Clearing knowledge graph..."
rm -f data/knowledge_graph.db data/knowledge_graph.db-shm data/knowledge_graph.db-wal
echo "Knowledge graph cleared"

# 3. Clear semantic cache
echo "Clearing semantic cache..."
rm -f data/cache.db data/cache.db-shm data/cache.db-wal
echo "Semantic cache cleared"

# 4. Clear local state files
echo "Clearing local state files..."
echo '[]' > data/queue_status.json
# Handwritten/scanned PDFs checkpoint per page to data/{source}_progress.json so a
# killed job resumes. Left behind, a re-ingest of the same source silently resumes
# from a stale offset instead of starting at page 1.
rm -f data/*_progress.json
rm -f data/eval_set.json
rm -f data/training_pairs.json
rm -f models/reranker_model.pt
rm -rf models/finetuned_embeddings
rm -f logs/*.log
echo "Local state cleared"

# 5. Clear stored source files (the originals served by GET /sources/{source}/file)
echo "Clearing stored source files..."
rm -rf data/sources/
mkdir -p data/sources/
echo "Source files cleared"

# 6. Signal the frontend to clear chat history on next load.
#    Chat sessions live in localStorage, never on the backend, so this flag is the
#    only way a backend reset can reach them. GET /sessions/should_reset consumes it.
touch data/reset_sessions_flag
echo "Session reset flag created — frontend will clear chat history on next startup"

echo ""
echo "=== Reset complete ==="
echo "Preserved: data/user_id.txt, data/device_id.txt (identity — deleting either"
echo "           orphans every ChromaDB collection and graph table)"
echo "           data/settings.json (telemetry + display name)"
echo "           data/training_data/ (your batch-ingest corpus)"
