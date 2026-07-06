FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 1001 clmapp \
    && useradd --system --uid 1001 --gid clmapp --no-create-home clmapp
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 tesseract-ocr tesseract-ocr-eng curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl \
    && rm -rf /wheels
RUN python -m spacy download en_core_web_sm
COPY --chown=clmapp:clmapp app/ ./app/
COPY --chown=clmapp:clmapp alembic/ ./alembic/
COPY --chown=clmapp:clmapp alembic.ini ./alembic.ini
COPY --chown=clmapp:clmapp scripts/ ./scripts/
RUN mkdir -p /app/uploads /app/keys \
    && chown -R clmapp:clmapp /app/uploads /app/keys
USER clmapp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
