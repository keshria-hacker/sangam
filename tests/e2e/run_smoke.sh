#!/usr/bin/env bash
# Smoke test runner (Phase 8, rule 4) — REQUIRED GATE.
#
# Starts the backend with a FRESH temp SQLite DB + the mock LLM provider,
# serves the frontend statically, runs the Playwright smoke spec, then
# tears everything down. Exit code = spec exit code.
#
# Usage: ./tests/e2e/run_smoke.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$HOME/workspace/.venvs/sangam-full/bin/python"
BACKEND_PORT="${E2E_BACKEND_PORT:-8001}"
FRONTEND_PORT="${E2E_FRONTEND_PORT:-5500}"

TMPDIR_WORK="$(mktemp -d /tmp/sangam-smoke-XXXXXX)"
DB_PATH="$TMPDIR_WORK/smoke.db"

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -rf "$TMPDIR_WORK"
}
trap cleanup EXIT

# Clear the broken proxy env vars that poison httpx in this environment.
for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy NO_PROXY no_proxy; do
  unset "$v" 2>/dev/null || true
done
export SANGAM_MOCK_PROVIDER=1
export TEST_MODE=1
export MASTER_KEY=testkey123456789012345678901234567890
export DATABASE_URL="sqlite+aiosqlite:///$DB_PATH"

cd "$REPO/mainfiles"
"$VENV" -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
  >"$TMPDIR_WORK/backend.log" 2>&1 &
BACKEND_PID=$!

cd "$REPO/mainfiles/frontend"
# No-cache headers: the smoke test iterates on frontend files.
"$VENV" -c "
from http.server import HTTPServer, SimpleHTTPRequestHandler
class H(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', $FRONTEND_PORT), H).serve_forever()
" >/dev/null 2>&1 &
FRONTEND_PID=$!

echo "Waiting for backend on :$BACKEND_PORT ..."
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
  if [ "$i" -eq 60 ]; then echo "backend failed to start"; tail -30 "$TMPDIR_WORK/backend.log"; exit 1; fi
done

echo "Waiting for frontend on :$FRONTEND_PORT ..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1; then break; fi
  sleep 1
done

cd "$REPO"
export E2E_FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
export E2E_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
npx playwright test tests/e2e/smoke.spec.ts --reporter=list
