#!/bin/bash
set -e
echo "=== Starting ==="
mkdir -p /app/uploads /app/chroma_data /app/backend/keys

if [ ! -f /app/backend/keys/private.pem ]; then
    openssl genrsa -out /app/backend/keys/private.pem 2048
    openssl rsa -in /app/backend/keys/private.pem -pubout -out /app/backend/keys/public.pem
fi

if [ ! -z "$DATABASE_URL" ]; then
    export DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql+asyncpg://|' | sed 's|^postgresql://|postgresql+asyncpg://|')
fi

cd /app/backend
python /app/db_setup.py &
echo "Starting server on port ${PORT:-8080}..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
