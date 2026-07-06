#!/usr/bin/env bash
# One-command launcher for the Templates / document-generation demo.
# Runs the backend (:8077) + frontend (:5188) on isolated ports with a scratch
# database, so it never collides with any other copy of the app you have running.
#
#   Without an API key  -> AI edit + Fidelity use deterministic MOCK responses
#                          (everything is clickable and works, just canned).
#   With an OpenRouter key -> real streaming AI edits + real vision QA:
#       OPENROUTER_API_KEY=sk-or-... ./demo/run-demo.sh
#
# Then open  http://localhost:5188  (use "localhost", NOT 127.0.0.1 — CORS).
# Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Node 22 is required for pnpm here.
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 22 >/dev/null 2>&1 || true

DATA_DIR="$ROOT/demo/.demo-data"
mkdir -p "$DATA_DIR"

# If no OpenRouter key is provided, force every AI leg to its offline mock so the
# whole app works with zero setup. If a key IS set, use the real providers.
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo ">> No OPENROUTER_API_KEY set — using MOCK AI providers (deterministic, offline)."
  export OCR_DEFAULT_ENGINE=mock STRUCTURING_PROVIDER=mock DECISION_PROVIDER=mock \
         MAPPING_PROVIDER=mock QA_VISION_PROVIDER=mock AGENT_AUTHORING_PROVIDER=mock
else
  echo ">> OPENROUTER_API_KEY detected — using REAL AI providers."
fi
export DATA_DIR CORS_ORIGINS='["http://localhost:5188"]'

trap 'kill 0' EXIT
( cd backend && uv run --no-sync uvicorn app.main:app --port 8077 --host 127.0.0.1 ) &
VITE_API_BASE_URL="http://localhost:8077" pnpm vite --port 5188 --host 127.0.0.1 &

sleep 3
echo ""
echo "============================================================"
echo "  Demo is up.  Open:  http://localhost:5188"
echo "  (use localhost, not 127.0.0.1)      Ctrl+C to stop both."
echo "  Test documents are in  demo/"
echo "============================================================"
wait
