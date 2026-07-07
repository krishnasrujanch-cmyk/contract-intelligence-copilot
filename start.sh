#!/usr/bin/env bash
set -e
echo "🚀 Starting Contract Intelligence Copilot..."

# Start services (passwordless via sudoers)
sudo service postgresql start > /dev/null 2>&1 && echo "✅ PostgreSQL started" || \
  redis-server --daemonize yes --port 5432 2>/dev/null; echo "✅ PostgreSQL up"

redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || \
  sudo service redis-server start > /dev/null 2>&1
sleep 1
redis-cli ping > /dev/null 2>&1 && echo "✅ Redis started"

# Activate venv and load env
cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a

# Start FastAPI
echo "🌐 Starting FastAPI on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
