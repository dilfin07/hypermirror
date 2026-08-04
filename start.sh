#!/usr/bin/env bash
# Start all project services with one command.
#
#   ./start.sh              run the bot (API + UI) at http://127.0.0.1:8787
#   ./start.sh --build      rebuild the dashboard first, then run
#   ./start.sh --dev        + Vite dev server on :5173 (for live UI editing)
#   ./start.sh --port 9000  run the bot on a different port
#
# You do NOT need to start the MCP server (hl-copier-mcp) — an AI agent launches it over stdio.
# WARNING: the bot trades on a REAL Binance account. close/panic/start-live move real money.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT="$ROOT/hl-copier"
UI="$ROOT/ui-prototype"
PY="$BOT/.venv/bin/python"

PORT=8787
BUILD=0
DEV=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1; shift ;;
    --dev)   DEV=1; shift ;;
    --port)  PORT="$2"; shift 2 ;;
    *) echo "unknown flag: $1"; exit 1 ;;
  esac
done

# --- environment checks ---
if [[ ! -x "$PY" ]]; then
  echo "❌ no venv: $PY"
  echo "   create it: cd hl-copier && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
if [[ ! -f "$BOT/.env" ]]; then
  echo "⚠️  no $BOT/.env — Binance/Telegram keys are not set (the bot starts but won't trade)"
fi

# --- build the dashboard on request ---
if [[ "$BUILD" == "1" ]]; then
  echo "🔨 building the dashboard…"
  ( cd "$UI" && VITE_API=live ./node_modules/.bin/vite build --base=/v2/ --outDir "$BOT/web/v2" --emptyOutDir )
fi

# --- dev frontend (optional), stopped together with the script ---
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if [[ "$DEV" == "1" ]]; then
  echo "🎨 Vite dev server → http://127.0.0.1:5173"
  ( cd "$UI" && npm run dev ) &
  PIDS+=($!)
fi

# --- the bot (API + static UI) in the foreground ---
# not exec, so the trap can stop the dev frontend on Ctrl+C
echo "🤖 bot → http://127.0.0.1:$PORT   (Ctrl+C to stop)"
cd "$BOT"
"$PY" tools/serve.py --port "$PORT"
