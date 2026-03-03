#!/usr/bin/env bash
# Quick start in paper trading mode
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BOT_DIR"

# Activate venv if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Load .env if it exists
if [ -f "config/.env" ]; then
    set -a
    source config/.env
    set +a
fi

echo "Starting Spike ARB Bot in PAPER mode..."
python -m src.cli run --mode paper "$@"
