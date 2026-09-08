#!/bin/bash
# Quality checks for Sangam — run before commit
# Usage: ./scripts/quality.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "🔍 Running quality checks..."

# ─── Backend ──────────────────────────────────────────────
echo ""
echo "▶ Backend: Ruff lint"
cd backend
if command -v uv &> /dev/null; then
    uv run ruff check . --output-format=github
    uv run ruff format --check . --output-format=github
    uv run mypy . --strict --show-error-codes
    uv run bandit -r . -ll --exit-on-error
else
    python -m ruff check . --output-format=github
    python -m ruff format --check . --output-format=github
    python -m mypy . --strict --show-error-codes
    python -m bandit -r . -ll --exit-on-error
fi

# ─── Frontend ─────────────────────────────────────────────
echo ""
echo "▶ Frontend: ESLint + Prettier"
cd ../frontend
if [ -f "package.json" ]; then
    npx eslint js/ --ext .js --format=github
    npx prettier --check "js/**/*.js" "css/**/*.css" "*.html"
else
    echo "  ⚠️  No package.json found, skipping frontend checks"
    echo "  Run: npm init -y && npm install -D eslint prettier eslint-plugin-jsdoc"
fi

# ─── Dead Code (Optional) ─────────────────────────────────
echo ""
echo "▶ Dead code check (vulture)"
cd ../backend
if command -v uv &> /dev/null; then
    uv run vulture . --min-confidence 80 --exclude=*test*,main.py || true
else
    python -m vulture . --min-confidence 80 --exclude=*test*,main.py || true
fi

# ─── Complexity (Optional) ────────────────────────────────
echo ""
echo "▶ Cyclomatic complexity (radon)"
if command -v uv &> /dev/null; then
    uv run radon cc . -a --min B --show-closures || true
else
    python -m radon cc . -a --min B --show-closures || true
fi

echo ""
echo "✅ All quality checks passed!"