#!/usr/bin/env bash
# run.sh — Universal launcher for radd-stream on Linux / macOS / VPS / Replit
# Usage: bash run.sh [command] [args]
# Examples:
#   bash run.sh sync
#   bash run.sh fetch "https://multimovies.garden/movie/pathaan-2023/"
#   bash run.sh stats

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FF_DIR="$SCRIPT_DIR/Fast_Fetch"

# Detect python3
PYTHON="$(command -v python3 || command -v python)"
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found. Install with: sudo apt install python3"
    exit 1

PY_VER=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
if [ "$PY_VER" -lt 3 ]; then
    echo "ERROR: Python 3+ required. Found: $($PYTHON --version)"
    exit 1
fi

echo "[radd-stream] Using Python: $($PYTHON --version)"
echo "[radd-stream] Database: $FF_DIR/fast_fetch.db"
echo ""

# Run fast_fetch with all passed arguments
exec "$PYTHON" "$FF_DIR/fast_fetch.py" "$@"
