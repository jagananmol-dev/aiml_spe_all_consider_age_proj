# VEDA AI — Intelligence Service Dockerfile
# Multi-stage build for smaller production image

# ── Stage 1: Builder ──────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install -e . \
    && pip install --no-cache-dir --prefix=/install jupyter notebook

# Packages above went to /install; spaCy must be importable to fetch its model
RUN PYTHONPATH=/install/lib/python3.12/site-packages python -m spacy download en_core_web_sm

# ── Stage 2: Runtime ─────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy source code and notebooks
COPY src/ src/
COPY notebooks/ notebooks/
COPY start.sh .
RUN chmod +x start.sh

# Expose API port + Jupyter port
EXPOSE 8002 8888

# Health check on API
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

# Start both services
CMD ["./start.sh"]
