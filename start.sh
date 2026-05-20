#!/bin/bash
# Start the Audiobook Generator server

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for venv
if [ -d "venv" ]; then
    echo "Using virtual environment..."
    PYTHON="venv/bin/python"
else
    echo "Using system Python (create venv for isolation: python3 -m venv venv)"
    PYTHON="python3"
fi

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "WARNING: ffmpeg not found. Install it for audio encoding:"
    echo "  Ubuntu/Debian: sudo apt install ffmpeg"
    echo "  macOS: brew install ffmpeg"
    echo ""
fi

# Default settings
HOST="${AUDIOBOOK_HOST:-0.0.0.0}"
PORT="${AUDIOBOOK_PORT:-8123}"
ROOT="${AUDIOBOOK_ROOT:-$SCRIPT_DIR}"

echo "Starting Audiobook Generator..."
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Root: $ROOT"
echo ""
echo "Open http://localhost:$PORT in your browser"
echo "Press Ctrl+C to stop"
echo ""

exec "$PYTHON" monitor_server.py \
    --host "$HOST" \
    --port "$PORT" \
    --root "$ROOT"
