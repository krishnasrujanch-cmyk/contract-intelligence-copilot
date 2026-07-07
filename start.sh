#!/usr/bin/env bash
# =============================================================
# CLM Copilot — One-command startup after Codespace restart
# Usage: ./start.sh
# =============================================================
set -e

echo "🚀 Starting Contract Intelligence Copilot..."

# 1 — Start system services
echo "📦 Starting PostgreSQL and Redis..."
sudo service postgresql start > /dev/null 2>&1
sudo service redis-server start > /dev/null 2>&1

# Wait for PostgreSQL to be ready
until sudo -u postgres psql -c "SELECT 1" > /dev/null 2>&1; do
  sleep 1
done
echo "✅ PostgreSQL ready"

# Verify Redis
redis-cli ping > /dev/null 2>&1 && echo "✅ Redis ready"

# 2 — Activate virtual environment
cd /workspaces/contract-intelligence-copilot/backend
source .venv/bin/activate

# 3 — Load environment variables
set -a
source /workspaces/contract-intelligence-copilot/.env
set +a

echo "✅ Environment loaded"
echo "   DATABASE_URL: ${DATABASE_URL:0:40}..."
echo "   GROQ_API_KEY: ${GROQ_API_KEY:0:10}..."

# 4 — Start FastAPI in background
echo "🌐 Starting FastAPI on port 8000..."
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --log-level info &

FASTAPI_PID=$!
echo "✅ FastAPI started (PID: $FASTAPI_PID)"

# 5 — Wait and verify
sleep 4
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
  echo ""
  echo "============================================"
  echo "✅ CLM Copilot is running!"
  echo "   API Docs: http://localhost:8000/docs"
  echo "   Health:   http://localhost:8000/health"
  echo "   Ports tab in VS Code for public URLs"
  echo "============================================"
else
  echo "⚠️  FastAPI not yet ready — check logs above"
fi

# Keep script running so FastAPI logs are visible
wait $FASTAPI_PID

# ── Auto-reindex ChromaDB if empty ───────────────────────────────────────────
echo "🔍 Checking ChromaDB state..."
python3 - << 'PYEOF'
import sys
sys.path.insert(0, "/workspaces/contract-intelligence-copilot/backend")

import os
os.environ.setdefault("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))

try:
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path="/workspaces/contract-intelligence-copilot/backend/chroma_data",
        settings=Settings(anonymized_telemetry=False),
    )
    col = client.get_or_create_collection("clm_clauses")
    count = col.count()
    print(f"   ChromaDB: {count} vectors found")

    if count == 0:
        print("   ChromaDB empty — reindexing sample NDA...")
        from app.agents.rag.pipeline import RAGPipeline
        from pathlib import Path
        text = Path("/workspaces/contract-intelligence-copilot/test_contracts/sample_nda.txt").read_text()
        n = RAGPipeline().index_contract(text, "test-nda-phase4", "test-org-phase4")
        print(f"   ✅ Reindexed: {n} chunks stored")
    else:
        print(f"   ✅ ChromaDB intact — no reindex needed")
except Exception as e:
    print(f"   ⚠ ChromaDB check failed: {e}")
PYEOF
