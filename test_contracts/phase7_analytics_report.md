# Phase 7 — Feedback Analytics Report

**System:** Contract Intelligence Copilot
**Ground Truth:** 10 expert-labelled clauses from ground_truth_clauses.json
**LLM Results:** Phase 3 Chain-of-Thought (selected production strategy)

---

## 1. Risk Score Accuracy by Clause Type

| Clause Type | Expert Score | LLM Score (CoT) | Bias | Feedback | Positive Rate |
|---|---|---|---|---|---|
| confidentiality | 22 | 50 | 🔴 +27.5 | 2 | 0% |
| indemnification | 45 | 70 | 🔴 +25.0 | 0 | 0% |
| governing_law | 0 | 20 | 🔴 +20.0 | 0 | 0% |
| liability | 52 | 70 | 🔴 +17.5 | 0 | 0% |
| payment | 35 | 20 | 🟡 -15.0 | 0 | 0% |
| termination | 25 | 40 | 🟡 +15.0 | 0 | 0% |
| ip_ownership | 20 | 30 | 🟡 +10.0 | 1 | 100% |
| auto_renewal | 55 | 48 | 🟡 -7.5 | 2 | 50% |
| force_majeure | 20 | 25 | 🟢 +5.0 | 0 | 0% |

**Legend:** 🟢 ≤±5 (excellent) | 🟡 ±5-15 (acceptable) | 🔴 >±15 (correction applied)

---

## 2. Calibration Corrections Applied

### Current Risk Score Calibration

| Clause Type | Correction | Confidence | Status |
|---|---|---|---|
| confidentiality | -27.5 | 62% | Lower by 27.5 |
| indemnification | -25.0 | 60% | Lower by 25.0 |
| governing_law | -20.0 | 60% | Lower by 20.0 |
| liability | -17.5 | 60% | Lower by 17.5 |
| payment | No adjustment | 60% | Calibrated |
| termination | No adjustment | 60% | Calibrated |
| ip_ownership | No adjustment | 61% | Calibrated |
| auto_renewal | No adjustment | 62% | Calibrated |
| force_majeure | No adjustment | 60% | Calibrated |

---

## 3. Key Findings

- **Total clause types analysed:** 9
- **Well-calibrated (bias ≤ ±5):** 1 — force_majeure
- **Over-scored (bias > +15):** 4 — confidentiality, indemnification, governing_law, liability
- **Under-scored (bias < -15):** 0 — none

### Adaptive Calibration Impact

Corrections injected into Reasoner prompt for clause types where |bias| > 15.
Re-computed hourly as new feedback accumulates.

---

## 4. Prompt Engineering Decision Record

| Decision | Rationale |
|---|---|
| Chain-of-Thought selected | Highest F1 (95.2%) + best risk calibration in Phase 3 |
| Bias threshold = ±15 | Below ±15 is within LLM natural variance |
| Max correction = ±40 | Prevents extreme prompt injection from low-sample edge cases |
| Redis cache TTL = 1hr | Balances freshness vs DB query cost per LLM call |
| Confidence threshold 60% | Low-confidence hints omitted to avoid noise |

---

## 5. Phase 3 → Phase 7 Improvement Arc

| Metric | Zero-Shot | CoT | CoT + Calibration |
|---|---|---|---|
| Clause F1 | 90.0% | 95.2% | 95.2% |
| Risk Score MAE | ~25 pts | ~18 pts | ~12 pts (estimated) |
| Explainability | None | 4-step CoT | CoT + calibration rationale |
| Human Feedback Loop | No | No | Yes — drives adaptation |
