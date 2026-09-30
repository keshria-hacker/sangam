#!/bin/bash
# Quality checks for Sangam — run before commit
# Usage: ./scripts/quality.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

BACKEND="mainfiles/backend"
FRONTEND="mainfiles/frontend"

echo "🔍 Running quality checks..."

# ─── Backend ───────────────────────────────────────
echo ""
echo "▶ Backend: Ruff lint"
if command -v uv &> /dev/null; then
    uv run ruff check "$BACKEND" --output-format=github
    uv run ruff format --check "$BACKEND" --output-format=github
    uv run mypy "$BACKEND" --show-error-codes
    uv run bandit -r "$BACKEND" -ll --exit-on-error
else
    python -m ruff check "$BACKEND" --output-format=github
    python -m ruff format --check "$BACKEND" --output-format=github
    python -m mypy "$BACKEND" --show-error-codes
    python -m bandit -r "$BACKEND" -ll --exit-on-error
fi

# ─── Frontend ─────────────────────────────────────
echo ""
echo "▶ Frontend: syntax checks"
find "$FRONTEND/js" -name "*.js" -print0 | xargs -0 -n1 node --check

# ─── Tests ───────────────────────────────────────────
echo ""
echo "▶ Backend tests"
python -m pytest tests/ -q

echo ""
echo "✅ All quality checks passed!"
