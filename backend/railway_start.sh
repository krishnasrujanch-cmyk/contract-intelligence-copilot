#!/bin/bash
set -e

# Create required directories
mkdir -p /app/backend/keys /app/uploads /app/chroma_data

# Generate JWT keys if not present
if [ ! -f /app/backend/keys/private.pem ]; then
    echo "Generating JWT keys..."
    openssl genrsa -out /app/backend/keys/private.pem 2048
    openssl rsa -in /app/backend/keys/private.pem -pubout -out /app/backend/keys/public.pem
    echo "JWT keys generated"
fi

# Run database migrations
cd /app/backend
python -m alembic upgrade head 2>/dev/null || echo "Migrations skipped"

# Seed demo data
python scripts/seed_demo_data.py 2>/dev/null || echo "Seeding skipped"

# Start server
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
