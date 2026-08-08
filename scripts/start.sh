#!/bin/bash
# Start RAGbase: update check, backend, frontend, browser.
# For a tight dev loop, skip this and run the two processes directly (see §11 of
# .ai/instructions.md) — this script pulls from git and does a production build.
cd "$(dirname "$0")/.."

echo "=== Starting RAGbase ==="

# 0. Clear ports before starting
lsof -ti :3000 | xargs kill -9 2>/dev/null || true
lsof -ti :8001 | xargs kill -9 2>/dev/null || true

# 1. Create the directories the app writes into. Each of these is also created
#    lazily at runtime (chromadb by PersistentClient, sources by _save_source_file,
#    logs by config/logging.py at import), but making them up front means a
#    permissions problem surfaces here instead of mid-ingest.
mkdir -p data/sources data/chromadb logs

# 2. Check for updates
echo "Checking for updates..."
LATEST=$(.venv/bin/python3 -c "import urllib.request,json; data=json.loads(urllib.request.urlopen('https://api.github.com/repos/tlayers21/ragbase/commits/main').read()); print(data['sha'][:7])" 2>/dev/null)
LOCAL=$(git rev-parse --short HEAD)

if [ -n "$LATEST" ] && [ "$LATEST" != "$LOCAL" ]; then
    echo "Update available ($LOCAL → $LATEST), pulling..."
    git pull origin main
    uv pip install -e . --python .venv/bin/python3 --quiet 2>/dev/null || true
    (cd frontend && npm install --silent)
else
    echo "Already up to date ($LOCAL)"
fi

# 3. Start backend using venv Python directly.
#    Bare `uvicorn` resolves to system Python and won't see the venv's packages.
echo "Starting backend..."
.venv/bin/python3 -m uvicorn main:app --port 8001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"

# Registered immediately after the first process exists, not at the end of the
# script — the build and the readiness wait below can take minutes, and a Ctrl+C
# in that window used to leave the backend running.
cleanup() {
    echo ""
    echo "Stopping RAGbase..."
    kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    # `npm start` spawns next-server as a child; killing the npm wrapper alone
    # leaves it holding port 3000.
    pkill -f "next-server" 2>/dev/null || true
    echo "Stopped."
    exit 0
}
trap cleanup INT TERM

# 4. Build frontend if changed, then start.
#    md5 on macOS, md5sum on Linux — install.sh supports both.
hash_files() {
    if command -v md5sum > /dev/null 2>&1; then
        md5sum | awk '{print $1}'
    else
        md5
    fi
}

# Every directory holding frontend source, plus the config files that change build
# output. Miss one and a real change ships against a stale production build —
# frontend/types was the gap that motivated listing these explicitly.
FRONTEND_HASH=$(
    {
        find frontend/app frontend/components frontend/lib frontend/hooks frontend/types \
             frontend/public -type f 2>/dev/null | sort | xargs cat 2>/dev/null
        cat frontend/package.json frontend/next.config.ts frontend/tsconfig.json \
            frontend/postcss.config.mjs 2>/dev/null
    } | hash_files
)
LAST_HASH_FILE=".frontend_build_hash"

if [ ! -f "$LAST_HASH_FILE" ] || [ "$FRONTEND_HASH" != "$(cat $LAST_HASH_FILE)" ]; then
    echo "Building frontend..."
    (cd frontend && npm run build)
    echo "$FRONTEND_HASH" > "$LAST_HASH_FILE"
else
    echo "Frontend unchanged, skipping build"
fi

echo "Starting frontend..."
# Parenthesised subshell, not `cd frontend && npm start &`: backgrounding an
# AND-list leaves the parent shell's cwd unchanged, so the `cd ..` that used to
# follow it walked the script out of the project root.
(cd frontend && npm start) &
FRONTEND_PID=$!

# 5. Wait for frontend to be ready then open browser
echo "Waiting for frontend to be ready..."
until curl -s http://localhost:3000 > /dev/null 2>&1; do
    sleep 1
done

echo ""
echo "=== RAGbase is running ==="
echo "Backend:  http://localhost:8001"
echo "Frontend: http://localhost:3000"
echo ""

# Open browser
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:3000
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open http://localhost:3000 2>/dev/null || true
fi

echo "Press Ctrl+C to stop all services"
wait
