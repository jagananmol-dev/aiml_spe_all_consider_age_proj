#!/bin/bash
# VEDA AI — Intelligence Service Entrypoint
# Starts the FastAPI API server, and optionally a token-protected Jupyter server.

set -e

echo "🚀 Starting VEDA Intelligence Service..."

# Jupyter executes arbitrary code, so it is off by default and always
# requires a token. Enable with ENABLE_JUPYTER=1 and JUPYTER_TOKEN=<secret>.
if [ "${ENABLE_JUPYTER:-0}" = "1" ]; then
    if [ -z "${JUPYTER_TOKEN}" ]; then
        echo "❌ ENABLE_JUPYTER=1 requires JUPYTER_TOKEN to be set. Refusing to start Jupyter."
    else
        echo "📓 Starting Jupyter Notebook on port 8888 (token required)..."
        jupyter notebook \
            --ip=0.0.0.0 \
            --port=8888 \
            --no-browser \
            --allow-root \
            --IdentityProvider.token="${JUPYTER_TOKEN}" \
            --notebook-dir=/app/notebooks &
    fi
fi

# Start FastAPI server in the foreground
echo "🔧 Starting FastAPI API on port 8002..."
exec uvicorn src.api:app --host 0.0.0.0 --port 8002
