#!/bin/bash

echo "=== Starting RAGbase ==="

# 1. Activate venv and start backend
echo "Starting backend..."
source .venv/bin/activate
python3 -m uvicorn main:app --port 8001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"

# 2. Start frontend
echo "Starting frontend..."
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..
echo "Frontend started (PID $FRONTEND_PID)"

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
