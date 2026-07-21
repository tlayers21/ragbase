#!/bin/bash
set -e

echo "=== RAGbase Full Reset ==="

# 0. Kill any running frontend dev server
echo "Stopping frontend dev server if running..."
pkill -f "npm run dev" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true

# 1. Kill any running server
echo "Stopping server if running..."
lsof -i :8001 | awk 'NR>1 {print $2}' | xargs kill -9 2>/dev/null || true

# 2. Clear embedded ChromaDB storage
echo "Clearing ChromaDB data..."
rm -rf data/chromadb && mkdir -p data/chromadb
echo "ChromaDB data cleared"

# 3. Clear knowledge graph (delete the SQLite file entirely for a clean slate)
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

# 4. Clear semantic cache
echo "Clearing semantic cache..."
rm -f data/cache.db data/cache.db-shm data/cache.db-wal
echo "Semantic cache cleared"

# 5. Clear local state files
echo "Clearing local state files..."
echo '[]' > data/queue_status.json
rm -f data/eval_set.json
rm -f data/training_pairs.json
rm -f models/reranker_model.pt
rm -f logs/*.log

# 6. Clear stored source files
echo "Clearing stored source files..."
rm -rf data/sources/
mkdir -p data/sources/
echo "Source files cleared"

# 7. Signal the frontend to clear chat history on next load
touch data/reset_sessions_flag
echo "Session reset flag created — frontend will clear chat history on next startup"

echo "=== Reset complete ==="
