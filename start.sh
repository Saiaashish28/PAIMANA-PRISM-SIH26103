#!/usr/bin/env bash
# PAIMANA PRISM - one-command start for macOS / Linux:  ./start.sh   (Ctrl+C stops both servers)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv"
PY="$VENV/bin/python"

[ -x "$PY" ] || { echo "Creating Python environment in backend/.venv ..."; python3 -m venv "$VENV"; }
if [ ! -f "$VENV/.installed" ] || [ "$ROOT/backend/requirements.txt" -nt "$VENV/.installed" ]; then
  echo "Installing backend packages ..."
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -r "$ROOT/backend/requirements.txt"
  touch "$VENV/.installed"
fi
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install)

if command -v lsof >/dev/null && lsof -ti tcp:8000 -sTCP:LISTEN >/dev/null; then
  echo "Stopping old process on port 8000"; kill $(lsof -ti tcp:8000 -sTCP:LISTEN) || true
fi

MODEL="${PRISM_OLLAMA_MODEL:-qwen2.5:3b}"
if command -v ollama >/dev/null; then
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null || { echo "Starting Ollama ..."; (ollama serve >/dev/null 2>&1 &); sleep 3; }
  ollama list | grep -q "$MODEL" || { echo "Downloading LLM model $MODEL (~2 GB, one time) ..."; ollama pull "$MODEL"; }
  echo "Local LLM: $MODEL (Ollama)"
else
  echo "Optional: install Ollama from https://ollama.com/download for LLM-written assistant answers."
fi

(cd "$ROOT/backend" && "$PY" -m uvicorn prism.api.main:app --port 8000) &
API=$!
(cd "$ROOT/frontend" && npm run dev) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null' EXIT INT TERM
echo "API: http://localhost:8000/docs   Dashboard: http://localhost:5173 (first start trains the models ~2 min)"
wait
