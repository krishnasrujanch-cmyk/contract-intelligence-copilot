#!/usr/bin/env bash
set -e
echo "🚀 Starting Contract Intelligence Copilot..."

# Services
sudo service postgresql start > /dev/null 2>&1 || true
redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || \
  sudo service redis-server start > /dev/null 2>&1 || true
sleep 2
pg_isready -h localhost -p 5432 -q && echo "✅ PostgreSQL"
redis-cli ping > /dev/null 2>&1 && echo "✅ Redis"

# Activate env
cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a

# Celery worker (processes uploaded contracts)
echo "⚙️  Starting Celery worker..."
celery -A app.tasks worker --loglevel=warning --concurrency=1 \
  -Q document_processing,alerts &
echo "✅ Celery worker"

# FastAPI
echo "🌐 Starting FastAPI on :8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
sleep 3

# Frontend
echo "🎨 Starting React UI on :5173..."
cd /workspaces/contract-intelligence-copilot/frontend
npm run dev &

sleep 4
echo ""
echo "============================================"
echo "✅ Contract Intelligence Copilot running!"
echo "   UI  → http://localhost:5173"
echo "   API → http://localhost:8000/docs"
echo "   admin@clm.demo / Admin@Demo2026!"
echo "============================================"
wait
