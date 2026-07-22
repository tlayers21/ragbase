#!/bin/bash

echo "=== Starting RAGbase ==="

# 0. Check for updates
echo "Checking for updates..."
LATEST=$(curl -s https://api.github.com/repos/tlayers21/ragbase/commits/main \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'][:7])" 2>/dev/null)
LOCAL=$(git rev-parse --short HEAD)

if [ -n "$LATEST" ] && [ "$LATEST" != "$LOCAL" ]; then
    echo "Update available ($LOCAL → $LATEST), pulling..."
    git pull origin main
    # Reinstall dependencies in case pyproject.toml changed
    source .venv/bin/activate
    uv pip install -e . --quiet
    cd frontend && npm install --silent && cd ..
else
    echo "Already up to date ($LOCAL)"
fi

# 1. Activate venv and start backend
echo "Starting backend..."
source .venv/bin/activate
python3 -m uvicorn main:app --port 8001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"

# 2. Build frontend if changed, then start
FRONTEND_HASH=$(find frontend/src frontend/app frontend/components frontend/lib frontend/hooks -type f 2>/dev/null | sort | xargs md5 2>/dev/null | md5)
LAST_HASH_FILE=".frontend_build_hash"

if [ ! -f "$LAST_HASH_FILE" ] || [ "$FRONTEND_HASH" != "$(cat $LAST_HASH_FILE)" ]; then
    echo "Building frontend..."
    cd frontend && npm run build && cd ..
    echo "$FRONTEND_HASH" > "$LAST_HASH_FILE"
else
    echo "Frontend unchanged, skipping build"
fi

echo "Starting frontend..."
cd frontend && npm start &
FRONTEND_PID=$!
cd ..

# 3. Wait for frontend to be ready then open browser
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

# 4. Wait and clean up on exit
trap "echo ''; echo 'Stopping RAGbase...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'; exit" INT TERM
wait