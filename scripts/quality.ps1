<#
.SYNOPSIS
    Quality checks for Sangam — run before commit
.DESCRIPTION
    Runs Ruff, MyPy, Bandit, ESLint, Prettier, and optional checks
.EXAMPLE
    .\scripts\quality.ps1
#>

param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "🔍 Running quality checks..." -ForegroundColor Cyan

# ─── Backend ──────────────────────────────────────────────
Write-Host "`n▶ Backend: Ruff lint" -ForegroundColor Yellow
Set-Location "$ProjectRoot\backend"

$UseUv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null

if ($UseUv) {
    uv run ruff check . --output-format=github
    uv run ruff format --check . --output-format=github
    uv run mypy . --strict --show-error-codes
    uv run bandit -r . -ll --exit-on-error
} else {
    python -m ruff check . --output-format=github
    python -m ruff format --check . --output-format=github
    python -m mypy . --strict --show-error-codes
    python -m bandit -r . -ll --exit-on-error
}

# ─── Frontend ─────────────────────────────────────────────
Write-Host "`n▶ Frontend: ESLint + Prettier" -ForegroundColor Yellow
Set-Location "$ProjectRoot\frontend"

if (Test-Path "package.json") {
    npx eslint js/ --ext .js --format=github
    npx prettier --check "js/**/*.js", "css/**/*.css", "*.html"
} else {
    Write-Warning "  No package.json found, skipping frontend checks"
    Write-Host "  Run: npm init -y && npm install -D eslint prettier eslint-plugin-jsdoc"
}

# ─── Dead Code (Optional) ─────────────────────────────────
Write-Host "`n▶ Dead code check (vulture)" -ForegroundColor Yellow
Set-Location "$ProjectRoot\backend"

if ($UseUv) {
    uv run vulture . --min-confidence 80 --exclude=*test*,main.py 2>$null || $true
} else {
    python -m vulture . --min-confidence 80 --exclude=*test*,main.py 2>$null || $true
}

# ─── Complexity (Optional) ────────────────────────────────
Write-Host "`n▶ Cyclomatic complexity (radon)" -ForegroundColor Yellow

if ($UseUv) {
    uv run radon cc . -a --min B --show-closures 2>$null || $true
} else {
    python -m radon cc . -a --min B --show-closures 2>$null || $true
}

Write-Host "`n✅ All quality checks passed!" -ForegroundColor Green