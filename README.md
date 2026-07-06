# Contract Intelligence Copilot

> AI-powered legal contract analysis — IITM Pravartak Capstone Project
> **Scenario 1: Business Operations Copilot (Decision Support Only)**

---

## Architecture

**Multi-agent pipeline:** Grok 4.1 Fast (Reasoner + Answerer) → Llama 3.3 70B via Groq (Judge) → Response

**Tech stack:** FastAPI + LangChain + LangGraph + ChromaDB + PostgreSQL + Redis + React 18 + shadcn/ui

**RBAC:** admin | reviewer | viewer — enforced at ChromaDB retrieval layer (not prompt)

**PII masking:** Microsoft Presidio de-identifies before LLM, re-identifies for authorised roles

---

## Quick Start (macOS)

### Prerequisites
- Docker Desktop for Mac
- `brew install openssl` (for key generation)

### 1. Clone and configure
```bash
git clone <repo-url>
cd contract-intelligence-copilot
cp .env.example .env
# Edit .env — fill in XAI_API_KEY, GROQ_API_KEY, OPENAI_API_KEY
```

### 2. Generate JWT signing keys
```bash
chmod +x backend/scripts/generate_keys.sh
./backend/scripts/generate_keys.sh
```

### 3. Start all services
```bash
docker compose up --build
# First build: ~5 minutes (downloads models)
# Subsequent starts: ~30 seconds
```

### 4. Run database migrations
```bash
docker compose exec fastapi alembic upgrade head
```

### 5. Seed demo users
```bash
docker compose exec fastapi python -m app.scripts.seed_demo_data
```

### 6. Access
| Service | URL |
|---|---|
| React UI | http://localhost:3000 |
| FastAPI docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

### Demo credentials
| Role | Email | Password |
|---|---|---|
| Admin | admin@clm.demo | Admin@Demo2026! |
| Reviewer | reviewer@clm.demo | Review@Demo2026! |
| Viewer | viewer@clm.demo | View@Demo2026! |

---

## Project Structure

```
contract-intelligence-copilot/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routes and middleware
│   │   ├── agents/          # LangGraph multi-agent pipeline
│   │   ├── core/            # Config, logging, security
│   │   ├── domain/          # Models, schemas, enums
│   │   ├── infrastructure/  # DB, vector store, LLM, PII, chunking
│   │   └── tasks/           # Celery async jobs
│   ├── alembic/             # DB migrations
│   ├── keys/                # JWT RS256 key pair (gitignored)
│   ├── scripts/             # Setup and seed scripts
│   └── tests/               # pytest unit + integration
├── frontend/
│   └── src/
│       ├── components/      # shadcn/ui + feature components
│       ├── pages/           # Route-level pages
│       ├── services/        # Axios API client
│       └── store/           # Zustand auth state
├── test_contracts/          # Sample contracts for demo
├── docker-compose.yml
└── .env.example
```

---

## Running Tests

```bash
# Backend unit + integration tests
docker compose exec fastapi pytest tests/ -v --cov=app --cov-report=term

# Frontend type check
docker compose exec frontend npm run type-check
```

---

## Safety Design

| Safety Requirement | Implementation |
|---|---|
| Refuse data modification | Pre-LLM guardrail — no write tools exposed to agents |
| Explain uncertainty | Confidence score on every extraction — explicit flag below 75% |
| Escalate high-risk clauses | `flag_for_human_review()` auto-triggered for risk ≥ 80 |
| No PII in logs | structlog middleware strips PII fields before every log write |
| RBAC at data layer | ChromaDB `where` filter applied before LLM context assembled |

---

## LLM Cost Estimate

| Provider | Model | Role | Cost |
|---|---|---|---|
| xAI Grok | grok-4.1-fast | Reasoner + Answerer | ~$1-3 total (covered by $25 free credit) |
| Groq | llama-3.3-70b-versatile | Judge | Free (14,400 req/day) |
| OpenAI | gpt-4o-mini / gpt-4o | Backup + Vision OCR | Free (Vocareum key) |
