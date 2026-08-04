#!/usr/bin/env bash
# Deploy the code from your dev machine to a remote server (e.g. a Raspberry Pi) in one command.
#
#   ./deploy.sh            push code + restart the service
#   ./deploy.sh --build    rebuild the frontend first (vite build), then push
#   ./deploy.sh --deps     after pushing, update dependencies (pip install) on the server
#   ./deploy.sh --dry      show what would change (rsync --dry-run), without pushing
#
# Set the target via env (SSH host and optional key):
#   DEPLOY_TARGET=user@your-server DEPLOY_KEY=~/.ssh/id_rsa ./deploy.sh
#
# IMPORTANT: never overwrites the live config/config.json, .env or runtime/ on the server
# (live settings, keys, state). Those are copied once during the initial setup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/hl-copier/"
PI="${DEPLOY_TARGET:-user@your-server}"
DST="~/hl-copier/"
KEY="${DEPLOY_KEY:-$HOME/.ssh/id_rsa}"
SSH="ssh -i $KEY"

BUILD=0 DEPS=0 DRYRUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) BUILD=1; shift ;;
    --deps)  DEPS=1; shift ;;
    --dry)   DRYRUN="--dry-run -v"; shift ;;
    *) echo "unknown flag: $1"; exit 1 ;;
  esac
done

if [[ "$BUILD" == "1" ]]; then
  echo "🔨 building the dashboard (v2)…"
  ( cd "$ROOT/ui-prototype" && VITE_API=live ./node_modules/.bin/vite build --base=/v2/ --outDir "$ROOT/hl-copier/web/v2" --emptyOutDir )
fi

echo "📤 pushing code to $PI (live config/.env/runtime are NOT touched)…"
rsync -az --delete $DRYRUN \
  --exclude '.venv' \
  --exclude 'web/node_modules' \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.env' \
  --exclude 'config/config.json' \
  --exclude 'runtime/' \
  -e "$SSH" "$SRC" "$PI:$DST"

if [[ -n "$DRYRUN" ]]; then echo "(dry-run — nothing pushed, service untouched)"; exit 0; fi

if [[ "$DEPS" == "1" ]]; then
  echo "📦 updating dependencies on the server…"
  $SSH "$PI" 'cd ~/hl-copier && ./.venv/bin/pip install -q -r requirements.txt'
fi

echo "♻️  restarting the service on the server…"
$SSH "$PI" 'export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart hl-copier.service && echo "ok"'

echo "✅ done. Check: http://your-server:8787 (or Telegram /status)"
