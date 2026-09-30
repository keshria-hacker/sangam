<#
.SYNOPSIS
    Quality checks for Sangam — run before commit
.DESCRIPTION
    Runs Ruff, MyPy, Bandit, browser script syntax checks, and the test suite
.EXAMPLE
    .\scripts\quality.ps1
#>

param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Backend = "mainfiles/backend"
$Frontend = "mainfiles/frontend"

Write-Host "🔍 Running quality checks..." -ForegroundColor Cyan

# ─── Backend ───────────────────────────────────────
Write-Host "`n▶ Backend: Ruff lint" -ForegroundColor Yellow

$UseUv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null

if ($UseUv) {
    uv run ruff check "$Backend" --output-format=github
    uv run ruff format --check "$Backend" --output-format=github
    uv run mypy "$Backend" --show-error-codes
    uv run bandit -r "$Backend" -ll --exit-on-error
} else {
    python -m ruff check "$Backend" --output-format=github
    python -m ruff format --check "$Backend" --output-format=github
    python -m mypy "$Backend" --show-error-codes
    python -m bandit -r "$Backend" -ll --exit-on-error
}

# ─── Frontend ─────────────────────────────────────
Write-Host "`n▶ Frontend: syntax checks" -ForegroundColor Yellow

Get-ChildItem "$Frontend/js" -Recurse -Filter *.js | ForEach-Object {
    node --check $_.FullName
}

# ─── Tests ───────────────────────────────────────────
Write-Host "`n▶ Backend tests" -ForegroundColor Yellow
python -m pytest tests/ -q

Write-Host "`n✅ All quality checks passed!" -ForegroundColor Green
