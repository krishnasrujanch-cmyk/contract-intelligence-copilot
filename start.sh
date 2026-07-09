#!/usr/bin/env bash
# =============================================================
# Contract Intelligence Copilot — One-command startup
# Usage: ./start.sh
# Starts: PostgreSQL, Redis, Celery, FastAPI, React UI
# =============================================================
set -e

echo "🚀 Starting Contract Intelligence Copilot..."
echo ""

# ── 1. PostgreSQL ─────────────────────────────────────────────
echo "📦 Starting PostgreSQL..."
sudo service postgresql start > /dev/null 2>&1 || true
sleep 2
if pg_isready -h localhost -p 5432 -q; then
    echo "✅ PostgreSQL ready"
else
    echo "⚠  PostgreSQL may not be ready — continuing anyway"
fi

# ── 2. Redis ──────────────────────────────────────────────────
echo "📦 Starting Redis..."
redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || \
    sudo service redis-server start > /dev/null 2>&1 || true
sleep 1
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis ready"
else
    echo "⚠  Redis may not be ready — continuing anyway"
fi

# ── 3. Environment ────────────────────────────────────────────
echo "🔧 Loading environment..."
cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a
echo "✅ Environment loaded"

# ── 4. ChromaDB reindex if empty ──────────────────────────────
echo "🔍 Checking ChromaDB..."
python3 - << 'PYEOF'
import sys, os
sys.path.insert(0, "/workspaces/contract-intelligence-copilot/backend")
os.chdir("/workspaces/contract-intelligence-copilot/backend")
try:
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path="/workspaces/contract-intelligence-copilot/backend/chroma_data",
        settings=Settings(anonymized_telemetry=False),
    )
    col = client.get_or_create_collection("clm_clauses")
    count = col.count()
    if count == 0:
        print("   ChromaDB empty — reindexing sample NDA...")
        from app.agents.rag.pipeline import RAGPipeline
        from pathlib import Path
        nda = Path("/workspaces/contract-intelligence-copilot/test_contracts/sample_nda.txt")
        if nda.exists():
            n = RAGPipeline().index_contract(nda.read_text(), "test-nda-phase4", "test-org-phase4")
            print(f"   ✅ Reindexed: {n} chunks")
        else:
            print("   ⚠  sample_nda.txt not found — skipping reindex")
    else:
        print(f"   ✅ ChromaDB has {count} vectors — no reindex needed")
except Exception as e:
    print(f"   ⚠  ChromaDB check skipped: {e}")
PYEOF

# ── 5. Ensure uploads directory exists ────────────────────────
mkdir -p /workspaces/contract-intelligence-copilot/backend/uploads
echo "✅ Uploads directory ready"

# ── 6. Celery worker (processes uploaded contracts) ───────────
echo "⚙️  Starting Celery worker..."
cd /workspaces/contract-intelligence-copilot/backend
celery -A app.tasks worker \
    --loglevel=warning \
    --concurrency=1 \
    -Q document_processing,alerts \
    --logfile=/tmp/celery.log &
CELERY_PID=$!
sleep 2
if kill -0 $CELERY_PID 2>/dev/null; then
    echo "✅ Celery worker running (PID $CELERY_PID)"
else
    echo "⚠  Celery may not have started — check /tmp/celery.log"
fi

# ── 7. FastAPI backend ────────────────────────────────────────
# Kill any existing instances
pkill -f uvicorn 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 2
echo "🌐 Starting FastAPI on port 8000..."
cd /workspaces/contract-intelligence-copilot/backend
uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level warning &
FASTAPI_PID=$!
sleep 4

if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ FastAPI ready (PID $FASTAPI_PID)"
else
    echo "⚠  FastAPI not yet ready — may still be starting"
fi

# ── 8. React frontend ─────────────────────────────────────────
echo "🎨 Starting React UI on port 5173..."
cd /workspaces/contract-intelligence-copilot/frontend
npm run dev --silent &
FRONTEND_PID=$!
sleep 3
echo "✅ React UI starting (PID $FRONTEND_PID)"

# ── Ready ─────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "✅ Contract Intelligence Copilot is running!"
echo ""
echo "   React UI  →  http://localhost:5173"
echo "   API Docs  →  http://localhost:8000/docs"
echo "   Health    →  http://localhost:8000/health"
echo ""
echo "   Demo logins:"
echo "   admin@clm.demo     / Admin@Demo2026!"
echo "   reviewer@clm.demo  / Review@Demo2026!"
echo "   viewer@clm.demo    / View@Demo2026!"
echo ""
echo "   Logs:"
echo "   Celery → /tmp/celery.log"
echo "   Press Ctrl+C to stop all services"
echo "============================================"
echo ""

# ── Keep alive — Ctrl+C kills all background jobs ─────────────
trap 'echo ""; echo "Stopping all services..."; kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
wait
