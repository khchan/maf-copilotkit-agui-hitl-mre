#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"

uv run uvicorn hitl_mre.app:create_app --factory --host 127.0.0.1 --port 8098 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

until curl -sf http://127.0.0.1:8098/health; do sleep 0.5; done

cd "$ROOT/frontend"
npm install --silent
npm run dev
