#!/bin/bash
# First-time setup for RAGbase. Run from the project root: bash scripts/install.sh
set -e

echo "=== RAGbase Setup ==="

# 1. OS check
OS="$(uname -s)"
if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
    echo "ERROR: Unsupported OS '$OS'. RAGbase supports macOS and Linux."
    echo "On Windows, use WSL2 and run this script inside your WSL2 distro."
    exit 1
fi
echo "OS: $OS"

# 2. Prerequisite checks
MISSING=0

if ! command -v ollama > /dev/null 2>&1; then
    echo "MISSING: Ollama — install from https://ollama.ai"
    MISSING=1
else
    echo "Found Ollama: $(ollama --version 2>/dev/null | head -1)"
fi

if ! command -v python3 > /dev/null 2>&1; then
    echo "MISSING: Python 3.11+ — install from https://python.org"
    MISSING=1
else
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
    if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
        echo "MISSING: Python 3.11+ (found $PY_MAJOR.$PY_MINOR) — install from https://python.org"
        MISSING=1
    else
        echo "Found Python $PY_MAJOR.$PY_MINOR"
    fi
fi

if ! command -v node > /dev/null 2>&1; then
    echo "MISSING: Node.js 18+ — install from https://nodejs.org"
    MISSING=1
else
    NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [[ "$NODE_MAJOR" -lt 18 ]]; then
        echo "MISSING: Node.js 18+ (found v$NODE_MAJOR) — install from https://nodejs.org"
        MISSING=1
    else
        echo "Found Node.js $(node --version)"
    fi
fi

if [[ "$MISSING" -eq 1 ]]; then
    echo ""
    echo "Install the missing prerequisites above, then re-run: bash scripts/install.sh"
    exit 1
fi

# 3. Pull required Ollama models
# 3. Pull required Ollama models
echo ""
echo "Checking Ollama models..."
for model in qwen3 qwen2.5:3b qwen2.5vl bge-m3; do
    if ollama list | grep -q "^$model"; then
        echo "$model already installed, skipping"
    else
        echo "Pulling $model..."
        ollama pull "$model"
    fi
done

# 4. Python environment
echo ""
echo "Setting up Python environment..."
if ! command -v uv > /dev/null 2>&1; then
    echo "Installing uv..."
    pip install uv --break-system-packages
fi
uv venv .venv --clear
source .venv/bin/activate
uv pip install -e .
# Pin huggingface-hub below 1.0 to prevent transformers breakage
uv pip install "huggingface-hub<1.0"

# 5. Frontend
echo ""
echo "Installing frontend dependencies..."
cd frontend && npm install && cd ..

# 6. Required directories
mkdir -p data/sources data/chromadb logs

echo ""
echo "=== Setup complete ==="
echo "Run: bash scripts/start.sh"
