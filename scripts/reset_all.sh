#!/bin/bash
set -e

echo "=== RAGbase Full Reset ==="

# 0. Kill all RAGbase-related processes
echo "Stopping all RAGbase processes..."
pkill -f "npm run dev" 2>/dev/null || true
pkill -f "npm start" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
lsof -i :8001 | awk 'NR>1 {print $2}' | xargs kill -9 2>/dev/null || true
lsof -i :3000 | awk 'NR>1 {print $2}' | xargs kill -9 2>/dev/null || true
echo "All processes stopped"

# 1. Clear embedded ChromaDB storage
echo "Clearing ChromaDB data..."
rm -rf data/chromadb && mkdir -p data/chromadb
echo "ChromaDB data cleared"

# 2. Clear knowledge graph (delete the SQLite file entirely for a clean slate)
echo "Clearing knowledge graph..."
python3 -c "
import os
from config.paths import KNOWLEDGE_GRAPH_DB_PATH
db = str(KNOWLEDGE_GRAPH_DB_PATH)
for suffix in ['', '-shm', '-wal']:
    p = db + suffix
    if os.path.exists(p):
        os.remove(p)
        print(f'Deleted {p}')
print('Knowledge graph cleared')
"

# 3. Clear semantic cache
echo "Clearing semantic cache..."
rm -f data/cache.db data/cache.db-shm data/cache.db-wal
echo "Semantic cache cleared"

# 4. Clear local state files
echo "Clearing local state files..."
echo '[]' > data/queue_status.json
rm -f data/eval_set.json
rm -f data/training_pairs.json
rm -f models/reranker_model.pt
rm -f logs/*.log

# 5. Clear stored source files
echo "Clearing stored source files..."
rm -rf data/sources/
mkdir -p data/sources/
echo "Source files cleared"

# 6. Signal the frontend to clear chat history on next load
touch data/reset_sessions_flag
echo "Session reset flag created — frontend will clear chat history on next startup"

echo "=== Reset complete ==="