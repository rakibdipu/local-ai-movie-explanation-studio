#!/usr/bin/env bash
# ==============================================================================
# Local AI Movie Explanation Studio - Launcher Script
# ==============================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check FFmpeg & FFprobe
if ! command -v ffmpeg &> /dev/null; then
    if [ -f "$HOME/.local/bin/ffmpeg" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "Error: ffmpeg is required. Please install ffmpeg or add to PATH."
        exit 1
    fi
fi

if ! command -v ffprobe &> /dev/null; then
    if [ -f "$HOME/.local/bin/ffprobe" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

# Setup or activate virtual environment
if [ ! -d ".venv" ]; then
    echo "Initializing virtual environment (.venv)..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    if [ -f "requirements.txt" ]; then
        .venv/bin/pip install -r requirements.txt
    fi
fi

# Ensure input and output directories exist
mkdir -p input output projects temp

# Execute application
exec .venv/bin/python3 main.py "$@"
