#!/bin/bash
# First-time setup for RAGbase. Run from anywhere: bash scripts/install.sh
#
#   --dry-run   Run every check and report what would be installed, changing
#               nothing. Use this to audit the script — a plain run rebuilds the
#               venv from scratch (`uv venv --clear`).
set -e

cd "$(dirname "$0")/.."

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        *) echo "Unknown option '$arg' (supported: --dry-run)"; exit 2 ;;
    esac
done

# Echo the command instead of running it when auditing.
run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  [dry-run] would run: $*"
    else
        "$@"
    fi
}

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== RAGbase Setup (dry run — nothing will be changed) ==="
else
    echo "=== RAGbase Setup ==="
fi

# 1. OS check
OS="$(uname -s)"
if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
    echo "ERROR: Unsupported OS '$OS'. RAGbase supports macOS and Linux."
    echo "On Windows, use WSL2 and run this script inside your WSL2 distro."
    exit 1
fi
echo "OS: $OS"

if [[ "$OS" == "Darwin" ]]; then
    PKG_HINT="brew install"
    FFMPEG_PKG="ffmpeg"
    POPPLER_PKG="poppler"
else
    PKG_HINT="sudo apt install"
    FFMPEG_PKG="ffmpeg"
    POPPLER_PKG="poppler-utils"
fi

# 2. Prerequisite checks
MISSING=0

if ! command -v ollama > /dev/null 2>&1; then
    echo "MISSING: Ollama — install from https://ollama.ai"
    MISSING=1
else
    echo "Found Ollama: $(ollama --version 2>/dev/null | head -1)"
fi

if ! command -v python3 > /dev/null 2>&1; then
    echo "MISSING: Python 3.13+ — install from https://python.org"
    MISSING=1
else
    # Must stay in step with requires-python in pyproject.toml.
    PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
    PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
    if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 13 ) ]]; then
        echo "MISSING: Python 3.13+ (found $PY_MAJOR.$PY_MINOR) — install from https://python.org"
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

# ffmpeg: openai-whisper shells out to the ffmpeg CLI to decode audio ("Requires
# the ffmpeg CLI in PATH" — whisper/audio.py), and yt-dlp uses it to extract audio
# from downloaded YouTube video. Without it, every video and YouTube ingest fails
# at extract_text() with a confusing subprocess error.
if ! command -v ffmpeg > /dev/null 2>&1; then
    echo "MISSING: ffmpeg (video + YouTube ingestion) — $PKG_HINT $FFMPEG_PKG"
    MISSING=1
else
    echo "Found ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"
fi

# poppler: pdf2image.convert_from_path() shells out to pdftoppm to rasterise pages.
# That is the scanned/handwritten PDF path — the primary route for any PDF without
# a text layer — so this is not optional for a PDF knowledge base.
if ! command -v pdftoppm > /dev/null 2>&1; then
    echo "MISSING: poppler (scanned/handwritten PDF ingestion) — $PKG_HINT $POPPLER_PKG"
    MISSING=1
else
    echo "Found poppler: $(pdftoppm -v 2>&1 | head -1)"
fi

if [[ "$MISSING" -eq 1 ]]; then
    echo ""
    echo "Install the missing prerequisites above, then re-run: bash scripts/install.sh"
    exit 1
fi

# 3. Pull required Ollama models
# One entry per distinct model name in config/models.py. Adding a MODEL_* constant
# there without adding it here means the first call to that task 404s at runtime.
echo ""
echo "Checking Ollama models..."
for model in qwen3 qwen2.5:3b qwen2.5vl bge-m3; do
    if ollama list | grep -q "^$model"; then
        echo "$model already installed, skipping"
    else
        echo "Pulling $model..."
        run ollama pull "$model"
    fi
done

# 4. Python environment
echo ""
echo "Setting up Python environment..."
if ! command -v uv > /dev/null 2>&1; then
    echo "Installing uv..."
    run pip install uv --break-system-packages
fi
run uv venv .venv --clear
run uv pip install -e . --python .venv/bin/python3
# Pin huggingface-hub below 1.0 to prevent transformers breakage. pyproject.toml
# pins it too, but a stray `uv sync` can still move it — see §8 of .ai/instructions.md.
run uv pip install "huggingface-hub<1.0" --python .venv/bin/python3

# 5. Verify the extractors import.
# anydoc ships prebuilt abi3 wheels for macOS (x86_64/arm64) and Linux
# (manylinux + musllinux, x86_64/aarch64), so no Rust toolchain is needed — but a
# platform without a wheel would fall back to an sdist build and fail here rather
# than silently at first ingest.
echo ""
echo "Verifying document extractors..."
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] would import anydoc and docling and convert a test CSV"
else
    .venv/bin/python3 -c "import anydoc; print('  anydoc OK —', len(anydoc.to_markdown_bytes(b'a,b\n1,2', 'csv')), 'chars from a test CSV')"
    .venv/bin/python3 -c "import docling; print('  docling OK')"
fi

# 6. Frontend
echo ""
echo "Installing frontend dependencies..."
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] would run: npm install && npm run build (in frontend/)"
else
    (cd frontend && npm install && npm run build)
fi

# 7. Required directories
run mkdir -p data/sources data/chromadb logs

echo ""
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== Dry run complete — nothing was changed ==="
    echo "Re-run without --dry-run to install."
    exit 0
fi

echo "=== Setup complete ==="
echo ""
echo "Start RAGbase:   bash scripts/start.sh"
echo "  Backend  -> http://localhost:8001"
echo "  Frontend -> http://localhost:3000"
echo ""
echo "Other scripts:"
echo "  bash scripts/status.sh      queue status + ingestion log tail"
echo "  bash scripts/reset_all.sh   wipe all data (keeps identity + settings)"
