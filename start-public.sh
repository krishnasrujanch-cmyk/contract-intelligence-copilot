#!/usr/bin/env bash
set -e
echo "🚀 Starting Contract Intelligence Copilot (PUBLIC MODE)..."

# Get Codespace URL
CS=$(gh codespace list --json name -q '.[0].name' 2>/dev/null || echo "")
if [ -z "$CS" ]; then
    echo "⚠  Could not detect Codespace name — using localhost fallback"
    API_URL="http://localhost:8000"
else
    API_URL="https://${CS}-8000.app.github.dev"
fi

echo "📡 API URL: $API_URL"
echo "🌐 UI URL:  https://${CS}-5173.app.github.dev"

# Write frontend env
echo "VITE_API_URL=${API_URL}" > \
  /workspaces/contract-intelligence-copilot/frontend/.env.local
echo "✅ Frontend configured for public URL"

# Add Codespaces URL to CORS
FRONTEND_URL="https://${CS}-5173.app.github.dev"

# Start services
sudo service postgresql start > /dev/null 2>&1 || true
redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || true
sleep 2

cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a

# Add Codespaces CORS
export CORS_ORIGINS_STR="http://localhost:5173,${FRONTEND_URL}"

pkill -f uvicorn 2>/dev/null || true
sleep 2

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
sleep 4

# Make ports public
gh codespace ports visibility 8000:public 2>/dev/null || true
gh codespace ports visibility 5173:public 2>/dev/null || true

cd /workspaces/contract-intelligence-copilot/frontend
pkill -f vite 2>/dev/null || true
sleep 2
npm run dev &
sleep 4

echo ""
echo "============================================"
echo "✅ Running in PUBLIC MODE"
echo ""
echo "   UI  → https://${CS}-5173.app.github.dev"
echo "   API → https://${CS}-8000.app.github.dev/docs"
echo ""
echo "   admin@clm.demo / Admin@Demo2026!"
echo "============================================"

trap 'kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
wait
