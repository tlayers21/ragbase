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

# 2. Delete all ChromaDB collections
echo "Clearing ChromaDB collections..."
python3 -c "
import chromadb
client = chromadb.HttpClient(host='localhost', port=8000)
deleted = []
for name in ['user_test_user', 'user_test_user_summaries', 'knowledge']:
    try:
        client.delete_collection(name)
        deleted.append(name)
    except Exception:
        pass
for col in client.list_collections():
    try:
        client.delete_collection(col.name)
        deleted.append(col.name)
    except Exception:
        pass
print(f'Deleted collections: {deleted}')
print(f'Remaining: {[c.name for c in client.list_collections()]}')
"

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

# 4. Flush Redis semantic cache
echo "Flushing Redis cache..."
redis-cli FLUSHALL 2>/dev/null && echo "Redis flushed" || echo "Redis not running or unavailable — skipping"

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

# 8. Confirm clean state
echo "Confirming clean state..."
python3 -c "
import chromadb
client = chromadb.HttpClient(host='localhost', port=8000)
cols = client.list_collections()
print(f'ChromaDB collections remaining: {[c.name for c in cols]}')
assert len(cols) == 0, 'Collections not fully cleared!'
print('All clear!')
"

echo "=== Reset complete ==="