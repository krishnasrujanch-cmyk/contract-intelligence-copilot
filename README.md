# Contract Intelligence Copilot

**IITM Pravartak Professional Certificate in Agentic AI & Applications — Capstone Project**

Scenario 1: Business Operations Copilot | Track A: LangChain + LangGraph

---

## What It Does

AI-powered contract analysis system that extracts clauses, scores risk, answers questions, and learns from feedback — in read-only decision support mode.
---

## Quick Start (5 minutes)

```bash
git clone https://github.com/krishnasrujanch-cmyk/contract-intelligence-copilot
cd contract-intelligence-copilot

# Start everything
./start.sh
```

Then open:
- **UI:** http://localhost:5173
- **API:** http://localhost:8000/docs

**Demo login:**
---

## Architecture

| Layer | Technology | Purpose |
|---|---|---|
| LLM Primary | Groq llama-3.3-70b-versatile | Extraction, reasoning, answers |
| LLM Fast | Groq llama-3.1-8b-instant | Safety guard, extraction |
| LLM Fallback | OpenAI gpt-4o-mini | Backup when Groq rate-limited |
| Orchestration | LangChain 0.3 + LangGraph 0.2 | ReAct agent + stateful pipeline |
| Vector Store | ChromaDB 0.5 (embedded) | Clause embeddings + RBAC retrieval |
| Embeddings | all-MiniLM-L6-v2 (local) | Zero API cost, 384 dimensions |
| Database | PostgreSQL 16 + SQLAlchemy async | Contracts, clauses, audit log |
| Session Memory | Redis 7 (2hr TTL) | Multi-turn conversation context |
| PII Protection | Microsoft Presidio | Mask before LLM, restore for auth |
| Auth | JWT RS256 + bcrypt-12 | Stateless, refresh rotation |
| API | FastAPI 0.115 + Pydantic v2 | 7 endpoint groups, OpenAPI docs |
| UI | React 18 + Vite + Tailwind | Login, Dashboard, Upload, Chat, Users |

---

## Multi-Agent Pipeline
---

## Evaluation Results

| Metric | Regex Baseline | LLM CoT | Improvement |
|---|---|---|---|
| Clause F1 | 55.6% | 95.2% | +39.6% |
| Risk Scoring | ❌ Not supported | ✅ 0-100 scale | — |
| Semantic Understanding | ❌ Keyword only | ✅ Full context | — |
| Processing Time | <0.01s | 2-26s | Speed vs quality |

---

## Security Design

- **RBAC at data layer** — ChromaDB `where` filter on every query. Prompt injection cannot escalate roles.
- **Two-layer safety guard** — keyword check (<1ms) + LLM classification for ambiguous queries
- **JWT RS256** — asymmetric signing, 15-min access tokens, opaque refresh tokens with rotation
- **PII masking** — Presidio strips personal data before any LLM call; deterministic tokens for re-identification
- **Audit log** — every action logged with UUID trace, role, and action type (no PII)
- **Read-only mode** — system never modifies contracts; flag_for_human_review() for escalation

---

## Project Structure
---

## Phase Completion

| Phase | Description | Status |
|---|---|---|
| 1 | Problem Framing Document | ✅ |
| 2 | FastAPI scaffold + DB + Auth | ✅ |
| 3 | LLM integration + prompt comparison | ✅ |
| 4 | RAG pipeline + ChromaDB + LegalChunker | ✅ |
| 5 | LangGraph tools + guardrails | ✅ |
| 6 | Multi-turn memory (Redis) | ✅ |
| 7 | Feedback + adaptive calibration | ✅ |
| 8 | React UI | ✅ |
| 9 | Evaluation + safety review + docs | ✅ |
