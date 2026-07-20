#!/bin/bash

echo "=== Starting RAGbase ==="

# 1. Check Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop and try again."
    exit 1
fi

# 2. Start Docker services (ChromaDB + Redis)
echo "Starting Docker services..."
docker compose up -d
echo "Docker services started"

# 3. Activate venv and start backend
echo "Starting backend..."
source .venv/bin/activate
python3 -m uvicorn main:app --port 8001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"

# 4. Start frontend
echo "Starting frontend..."
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..
echo "Frontend started (PID $FRONTEND_PID)"

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

# 6. Wait and clean up on exit
trap "echo ''; echo 'Stopping RAGbase...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; docker compose stop; echo 'Stopped.'; exit" INT TERM
wait