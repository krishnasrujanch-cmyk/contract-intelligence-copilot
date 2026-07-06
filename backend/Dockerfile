# =============================================================================
# Contract Intelligence Copilot — Backend Dockerfile
# Multi-stage build: builder → runtime
# Security: non-root user, minimal image, no dev deps in production
# =============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

LABEL stage=builder

WORKDIR /build

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest stable
RUN pip install --no-cache-dir --upgrade pip==24.3.1

# Copy and compile wheels (allows runtime stage to install without build tools)
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Contract Intelligence Copilot"
LABEL version="1.0.0"

# Security: create non-root user and group
RUN groupadd --system --gid 1001 clmapp \
    && useradd --system --uid 1001 --gid clmapp --no-create-home clmapp

WORKDIR /app

# Install ONLY runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pre-compiled wheels from builder stage
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl \
    && rm -rf /wheels

# Download spaCy NER model for Presidio PII detection
RUN python -m spacy download en_core_web_lg

# Copy application source (owned by non-root user)
COPY --chown=clmapp:clmapp app/         ./app/
COPY --chown=clmapp:clmapp alembic/     ./alembic/
COPY --chown=clmapp:clmapp alembic.ini  ./alembic.ini
COPY --chown=clmapp:clmapp scripts/     ./scripts/

# Create upload directory with correct permissions
RUN mkdir -p /app/uploads && chown -R clmapp:clmapp /app/uploads
RUN mkdir -p /app/keys && chown -R clmapp:clmapp /app/keys

# Drop to non-root user — never run as root in production
USER clmapp

EXPOSE 8000

# Built-in health check — used by Docker Compose and container orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
