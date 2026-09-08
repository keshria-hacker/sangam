# =============================================================================
# Dockerfile — UniversalAI Backend
#
# Multi-stage build:
#   1. builder  — install Python dependencies (with build toolchain)
#   2. runtime  — copy only the built packages + application code (slim)
# =============================================================================

# ── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Build toolchain needed for packages that ship sdist rather than wheels
# (chromadb/onnxruntime, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Single source of truth: the dependency list lives at the repo root.
COPY requirements.txt .

# Install into /root/.local so we can copy *only* the installed packages
# into the runtime stage without bringing build-time cruft along.
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Runtime stage ───────────────────────────────────────────────────────────
FROM python:3.13-slim

# Runtime system dependencies — ocr + PDF rendering.
# tesseract-ocr & poppler-utils are needed by pytesseract & pdf2image
# respectively for scanned-document support.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from the builder stage — install to /usr/local
# so they are accessible system-wide by any user (including the unprivileged
# sangam user we create below).
COPY --from=builder /root/.local /usr/local
ENV PYTHONUNBUFFERED=1 \
    PORT=8001

# Create the non-root user so the app doesn't run as root.
RUN groupadd --system sangam && \
    useradd --system --gid sangam --create-home --shell /bin/bash sangam

WORKDIR /app/backend
COPY backend/ .

# Ensure the parent data directories exist on first startup.
# (These are bind-mounted as volumes in production; the mkdir is a safety net.)
RUN mkdir -p /app/uploads /app/history /app/logs /app/.chromadb && \
    chown -R sangam:sangam /app

USER sangam

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
