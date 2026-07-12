#!/bin/bash
set -e

# Railway provides DATABASE_URL and REDIS_URL automatically
# when you add PostgreSQL and Redis services

# Run migrations
python -m alembic upgrade head 2>/dev/null || echo "Migrations done or skipped"

# Start server
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
