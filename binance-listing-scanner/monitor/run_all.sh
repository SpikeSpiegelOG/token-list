#!/usr/bin/env bash
# Start the full local stack: DB init, watchers in background, dashboard in fg.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m monitor.db
python -m monitor.load_insiders || true

# Background workers
python -m monitor.announcement_watcher >> data/announcement.log 2>&1 &
ANN_PID=$!
python -m monitor.wallet_watcher        >> data/wallet.log       2>&1 &
WAL_PID=$!
if [ -n "${TG_API_ID:-}" ]; then
  python -m monitor.tg_scraper          >> data/tg.log           2>&1 &
  TG_PID=$!
fi

trap "kill $ANN_PID $WAL_PID ${TG_PID:-} 2>/dev/null || true" EXIT

echo "Watchers running. Dashboard at http://localhost:8000"
exec uvicorn monitor.dashboard:app --host 127.0.0.1 --port 8000
