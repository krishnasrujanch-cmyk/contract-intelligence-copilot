# Contract Intelligence Copilot

> **IITM Pravartak Professional Certificate in Agentic AI & Applications**
> Capstone Project — Scenario 1: Business Operations Copilot (Read-Only Decision Support)

---

## Overview

An enterprise-grade AI-powered contract intelligence platform that automatically extracts clauses, assesses risk, and answers natural language questions about legal contracts — with role-based access control enforced at the vector store layer.

### Key Features

- **Multi-format ingestion** — PDF, DOCX, TXT with table extraction
- **AI clause extraction** — LLM-powered with 95.2% F1 score (vs 18.2% regex baseline)
- **Risk scoring** — 0–100 calibrated scores with adaptive feedback loop
- **RAG chat** — Natural language Q&A with citations, scoped per contract
- **RBAC** — Three-tier access control enforced at ChromaDB data layer
- **PII protection** — Microsoft Presidio masking before any LLM call
- **Adaptive calibration** — Phase 7 feedback loop improves scoring over time
- **Reviewer workflow** — Assign contracts, validate risk scores with 👍👎

---

## Architecture
### Multi-Agent Pipeline (LangGraph)
### RBAC at Data Layer

| Role | Contracts | RAG Chunks | Chat Access |
|---|---|---|---|
| Admin | All org contracts | All levels | All contracts |
| Reviewer | Assigned only | All levels | Assigned only |
| Viewer | Assigned only | Level=0 summaries | Summary answers only |

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM Orchestration | LangChain 0.3.25 + LangGraph 0.2.60 |
| Primary LLM | Groq llama-3.3-70b-versatile + llama-3.1-8b-instant |
| Fallback LLM | OpenAI gpt-4o-mini |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 (local, 384d) |
| Vector Store | ChromaDB 0.5.23 embedded |
| API Framework | FastAPI 0.115 + Pydantic v2 |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async |
| Task Queue | Celery 5.4 + Redis 7 |
| Auth | JWT RS256 + bcrypt-12 |
| PII Protection | Microsoft Presidio |
| Frontend | React 18 + Vite + TypeScript |
| Tracing | LangSmith |

---

## Quick Start (GitHub Codespaces)

```bash
# 1. Clone
git clone https://github.com/krishnasrujanch-cmyk/contract-intelligence-copilot
cd contract-intelligence-copilot

# 2. Configure environment
cp .env.example .env
# Add GROQ_API_KEY and OPENAI_API_KEY to .env

# 3. Install dependencies
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend && npm install

# 4. Start everything
cd .. && ./start.sh
```

### Access

| Service | URL |
|---|---|
| React UI | http://localhost:5173 |
| API Docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

---

## Demo Credentials

| Role | Email | Password |
|---|---|---|
| Admin | admin@clm.demo | Admin@Demo2026! |
| Reviewer | reviewer@clm.demo | Review@Demo2026! |
| Viewer | viewer@clm.demo | View@Demo2026! |

---

## Environment Variables

```env
GROQ_API_KEY=your_groq_key
OPENAI_API_KEY=your_openai_key
LANGCHAIN_API_KEY=your_langsmith_key
DATABASE_URL=postgresql+asyncpg://clm_user:welcome%40123@localhost:5432/clm_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
JWT_PRIVATE_KEY_PATH=/workspaces/contract-intelligence-copilot/backend/keys/private.pem
JWT_PUBLIC_KEY_PATH=/workspaces/contract-intelligence-copilot/backend/keys/public.pem
UPLOAD_DIR=/workspaces/contract-intelligence-copilot/backend/uploads
CHROMA_PATH=/workspaces/contract-intelligence-copilot/backend/chroma_data
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

---

## Viewing Data

### PostgreSQL

```bash
psql -U clm_user -d clm_db -h localhost
```

```sql
-- All contracts
SELECT id, title, status, overall_risk, risk_score, created_at
FROM contracts ORDER BY created_at DESC;

-- Clauses (highest risk first)
SELECT clause_type, title, risk_score, risk_level, flagged_for_review
FROM clauses WHERE contract_id = 'YOUR_ID' ORDER BY risk_score DESC;

-- User assignments
SELECT u.email, u.role, c.title
FROM user_contract_assignments a
JOIN users u ON u.id = a.user_id
JOIN contracts c ON c.id = a.contract_id;

-- Feedback log
SELECT clause_type, is_positive, suggested_value, created_at
FROM feedback ORDER BY created_at DESC LIMIT 20;
```

### ChromaDB

```python
import chromadb
from chromadb.config import Settings

col = chromadb.PersistentClient(
    path="backend/chroma_data",
    settings=Settings(anonymized_telemetry=False)
).get_or_create_collection("clm_clauses")

print(f"Total vectors: {col.count()}")

results = col.query(
    query_texts=["liability cap"],
    n_results=3,
    where={"contract_id": {"$eq": "YOUR_CONTRACT_ID"}}
)
for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
    print(f"[{meta['section_path']}]: {doc[:100]}")
```

---

## Evaluation Results (Phase 9)

| Component | Metric | Result |
|---|---|---|
| Regex Baseline | F1 | 18.2% |
| LLM CoT (Groq llama-3.3-70b) | F1 | **95.2%** |
| Safety Guardrails | Pass rate | **100%** (6/6) |
| RAG Multi-contract Isolation | Cross-contamination | **Zero** |
| Risk Score MAE (post-calibration) | Points | ~12 (estimated) |
| Multi-turn Memory | Tests passed | 4/5 |

---

## Test Contracts

| Contract | Domain | Clauses | Risk |
|---|---|---|---|
| software_license_agreement.pdf | Technology | 10 | Medium |
| saas_master_service_agreement.pdf | SaaS | 10 | Medium |
| supply_chain_master_agreement.pdf | Supply Chain | 10 | Medium |
| banking_loan_facility_agreement.pdf | Banking | 12 | Critical |
| it_outsourcing_master_services_agreement.pdf | IT Services | 13 | High |
| pharma_license_distribution_agreement.pdf | Pharma | 15 | High |

---

## Sample Chat Queries
---

## Publishing

### Demo (GitHub Codespaces)

```bash
# Make ports public
gh codespace ports visibility 8000:public
gh codespace ports visibility 5173:public
```

Share URLs:
- UI: `https://CODESPACE_NAME-5173.app.github.dev`
- API: `https://CODESPACE_NAME-8000.app.github.dev`

### Production (Railway — fastest)

```bash
npm install -g @railway/cli
railway login && railway init && railway up
```

### Production (Render)

1. Connect GitHub repo at render.com
2. Build: `cd backend && pip install -r requirements.txt`
3. Start: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add PostgreSQL and Redis add-ons
5. Set environment variables

### Production Roadmap

| Component | Current | Production Path |
|---|---|---|
| Vector Store | ChromaDB embedded | Pinecone (1 day migration) |
| LLM | Groq free tier | Self-hosted Llama / paid API |
| Auth | JWT | SSO (Auth0 / Keycloak) |
| Deployment | Codespaces | Kubernetes + Docker |
| File scanning | None | ClamAV |
| Monitoring | LangSmith free | LangSmith paid + Datadog |

---

## Phase Completion

| Phase | Description | Status |
|---|---|---|
| 1 | Problem Framing | ✅ |
| 2 | FastAPI + DB + Auth | ✅ |
| 3 | Baseline vs LLM comparison | ✅ |
| 4 | RAG pipeline + ChromaDB | ✅ |
| 5 | LangGraph agent + safety | ✅ |
| 6 | Redis memory + multi-turn | ✅ |
| 7 | Feedback + calibration | ✅ |
| 8 | React UI | ✅ |
| 9 | Evaluation + README | ✅ |

---

## Security

- JWT RS256 asymmetric signing
- bcrypt cost-12 password hashing
- Presidio PII masking before every LLM call
- RBAC at ChromaDB layer — prompt injection cannot bypass
- Pydantic v2 input validation on all endpoints
- CORS restricted to specific origins
- Full audit logging on all operations

---

Logging
cd /Users/srujan/Downloads/PYTHON/contract-intelligence-copilot
bash tail_logs.sh

Google cloud login
gcloud auth login
gcloud auth application-default login
gcloud config set project contractintelliegenceplatform

## Author

**Srujan Krishna** — Senior Java Architect and Agentic AI Engineer
GitHub: [@krishnasrujanch-cmyk](https://github.com/krishnasrujanch-cmyk)
Programme: IITM Pravartak Professional Certificate in Agentic AI & Applications

*Submitted July 2026*
