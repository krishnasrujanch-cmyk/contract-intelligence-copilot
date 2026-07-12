#!/usr/bin/env bash
set -e
echo "🚀 Starting Contract Intelligence Copilot (LOCAL MODE)..."

# Reset frontend to use Vite proxy (localhost)
echo "VITE_API_URL=" > \
  /workspaces/contract-intelligence-copilot/frontend/.env.local
echo "✅ Frontend configured for localhost"

# Start services
sudo service postgresql start > /dev/null 2>&1 || true
redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || true
sleep 2

cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a

pkill -f uvicorn 2>/dev/null || true
pkill -f vite 2>/dev/null || true
sleep 2

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
sleep 4

cd /workspaces/contract-intelligence-copilot/frontend
npm run dev &
sleep 4

echo ""
echo "============================================"
echo "✅ Running in LOCAL MODE"
echo ""
echo "   UI  → http://localhost:5173"
echo "   API → http://localhost:8000/docs"
echo ""
echo "   admin@clm.demo / Admin@Demo2026!"
echo "============================================"

trap 'kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
wait
