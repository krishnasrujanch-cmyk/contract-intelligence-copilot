# Phase 9 — System Evaluation Report

**System:** Contract Intelligence Copilot
**Capstone:** IITM Pravartak Professional Certificate in Agentic AI
**Scenario:** Business Operations Copilot (Decision Support Only)
**Framework:** LangChain + LangGraph (Track A)
**Evaluated:** 2026-07-08

---

## 1. Clause Extraction — LLM vs Baseline Comparison

| Metric | Regex Baseline | LLM (CoT, Groq) | Improvement |
|---|---|---|---|
| Precision | 100.0% | 90.9% | +-9.1% |
| Recall    | 10.0% | 100.0% | +90.0% |
| F1 Score  | 18.2% | 95.2% | +77.0% |
| Risk MAE  | N/A | 17.5 pts | — |

---

## 2. Safety Guardrails

- Total tests: 6 | Passed: 6 | Pass rate: 100.0%
- Guardrail tests: 2 | Pass rate: 100.0%
- Modification requests blocked: ✅
- Jailbreak attempts blocked: ✅
- RBAC enforced at data layer: ✅

---

## 3. RAG Pipeline

- Chunks indexed: 36 (LegalChunker with ARTICLE boundary detection)
- Queries tested: 5
- Avg retrieval confidence: 0.49
- Admin role chunks returned: 6 (full access)
- Viewer role chunks returned: 1 (summary only — RBAC enforced)
- Embedding model: sentence-transformers/all-MiniLM-L6-v2 (384d, local)

---

## 4. Multi-Turn Memory

- Tests: 5 | Passed: 4 | Pass rate: 80.0%
- Session storage: Redis HASH with 2-hour TTL
- Session isolation: Verified (different session_id = fresh context)
- Session clear on logout: Verified

---

## 5. Adaptive Risk Calibration

- Clause types analysed: 9
- Types requiring correction: 4 (confidentiality, indemnification, governing_law, liability)
- Calibration strategy: Prompt injection of calibration hints
- Threshold: bias > ±15 points from expert baseline

---

## 6. Architecture Summary

| Component | Implementation | Justification |
|---|---|---|
| LLM Primary | Groq llama-3.3-70b-versatile | Best open-weight model, free tier, low latency |
| LLM Fallback | OpenAI gpt-4o-mini | Vocareum course key, backup on Groq rate limit |
| Prompt Strategy | Chain-of-Thought | +39.6% F1 vs regex, best risk calibration |
| RAG | ChromaDB + all-MiniLM-L6-v2 | Local embeddings, zero API cost, RBAC filters |
| Memory | Redis HASH (2hr TTL) | Survives restarts, auto-expires, session-isolated |
| Safety | Two-layer (keyword + LLM) | Sub-ms for obvious attacks, LLM for ambiguous |
| RBAC | ChromaDB where-filter | Data layer — injection-proof, role from JWT |
| Feedback | Bias analysis + prompt injection | No fine-tuning needed, in-session adaptation |

---

## 7. Limitations and Future Work

1. **Groq free tier limits** — 100K tokens/day. Production deployment requires paid tier or self-hosted Llama.
2. **OCR quality** — scanned contracts rely on Tesseract. Poor scan quality reduces extraction accuracy.
3. **Single-contract RAG** — retrieval tested on one NDA. Multi-contract retrieval needs disambiguation logic.
4. **Judge loop** — REVISE cycle works but CoT latency (26s) makes multi-iteration expensive on free tier.
5. **UI** — functional React UI built; production would add PDF inline viewer and clause diff highlighting.
