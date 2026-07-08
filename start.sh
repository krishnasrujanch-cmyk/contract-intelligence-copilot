#!/usr/bin/env bash
# =============================================================
# CLM Copilot — One-command startup
# Usage: ./start.sh
# =============================================================
set -e

echo "🚀 Starting Contract Intelligence Copilot..."

# ── System services ───────────────────────────────────────────
echo "📦 Starting PostgreSQL and Redis..."
sudo service postgresql start > /dev/null 2>&1 || true
sudo service redis-server start > /dev/null 2>&1 || \
  redis-server --daemonize yes --port 6379 --loglevel warning 2>/dev/null || true

sleep 2
pg_isready -h localhost -p 5432 -q && echo "✅ PostgreSQL ready"
redis-cli ping > /dev/null 2>&1 && echo "✅ Redis ready"

# ── ChromaDB reindex if empty ─────────────────────────────────
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
    print(f"   ChromaDB: {count} vectors")
    if count == 0:
        print("   Reindexing sample NDA...")
        from app.agents.rag.pipeline import RAGPipeline
        from pathlib import Path
        text = Path("/workspaces/contract-intelligence-copilot/test_contracts/sample_nda.txt").read_text()
        n = RAGPipeline().index_contract(text, "test-nda-phase4", "test-org-phase4")
        print(f"   ✅ {n} chunks indexed")
    else:
        print("   ✅ ChromaDB intact")
except Exception as e:
    print(f"   ⚠ ChromaDB: {e}")
PYEOF

# ── Backend ───────────────────────────────────────────────────
echo "🌐 Starting FastAPI on port 8000..."
cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate
set -a && source /workspaces/contract-intelligence-copilot/.env && set +a

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
FASTAPI_PID=$!

# ── Frontend ──────────────────────────────────────────────────
echo "🎨 Starting React UI on port 5173..."
cd /workspaces/contract-intelligence-copilot/frontend
npm run dev &
FRONTEND_PID=$!

# ── Wait for services ─────────────────────────────────────────
sleep 5
echo ""
echo "============================================"
echo "✅ Contract Intelligence Copilot running!"
echo ""
echo "   React UI  → http://localhost:5173"
echo "   API Docs  → http://localhost:8000/docs"
echo "   Health    → http://localhost:8000/health"
echo ""
echo "   Demo logins:"
echo "   admin@clm.demo    / Admin@Demo2026!"
echo "   reviewer@clm.demo / Review@Demo2026!"
echo "   viewer@clm.demo   / View@Demo2026!"
echo "============================================"

# Keep alive — Ctrl+C stops both
wait $FASTAPI_PID $FRONTEND_PID
