#!/usr/bin/env bash
# Start in live trading mode — USE WITH CAUTION
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BOT_DIR"

# Safety check
echo "WARNING: You are about to start the bot in LIVE mode."
echo "This will place REAL trades with REAL money."
read -p "Are you sure? (type 'yes' to confirm): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Load .env
if [ -f "config/.env" ]; then
    set -a
    source config/.env
    set +a
fi

echo "Starting Spike ARB Bot in LIVE mode..."
python -m src.cli run --mode live "$@"
