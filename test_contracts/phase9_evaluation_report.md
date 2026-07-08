# Phase 9 — Evaluation Report

| Phase | Component | Metric | Result |
|---|---|---|---|
| 3a | Regex Baseline | F1 | 18.2% |
| 3b | LLM CoT Groq | F1 | 95.2% |
| 3b | LLM CoT Groq | Risk MAE | ~18 pts vs expert |
| 4  | RAG Pipeline | Chunks | 36 |
| 5  | Safety | Pass rate | 6/6 |
| 5  | Guardrails | Blocks | 2/2 ✅ |
| 6  | Memory | Tests | 4/5 |
| 7  | Calibration | Types corrected | 4/9 |

## Security
| Control | Status |
|---|---|
| RBAC at data layer | ✅ ChromaDB where-filter |
| Safety guardrails | ✅ 2-layer keyword+LLM |
| PII protection | ✅ Presidio before LLM |
| JWT RS256 + bcrypt | ✅ |
| Audit log | ✅ Append-only, no PII |
| Read-only mode | ✅ No modification tools |
