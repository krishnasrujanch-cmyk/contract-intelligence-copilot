#!/bin/bash
set -e

echo "=== Starting Contract Intelligence Copilot ==="

mkdir -p /app/uploads /app/chroma_data /app/backend/keys

# Generate JWT keys
if [ ! -f /app/backend/keys/private.pem ]; then
    openssl genrsa -out /app/backend/keys/private.pem 2048
    openssl rsa -in /app/backend/keys/private.pem -pubout -out /app/backend/keys/public.pem
    echo "JWT keys generated"
fi

# Fix DATABASE_URL for asyncpg
if [ ! -z "$DATABASE_URL" ]; then
    export DATABASE_URL=$(echo "$DATABASE_URL" | \
        sed 's|^postgres://|postgresql+asyncpg://|' | \
        sed 's|^postgresql://|postgresql+asyncpg://|')
    echo "DB URL configured"
fi

cd /app/backend

# Setup database using Python file (not heredoc)
python /app/db_setup.py

# Start server
echo "Starting on port ${PORT:-8080}..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
