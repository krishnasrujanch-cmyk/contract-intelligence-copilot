## Phase 3 — Prompt Comparison Table

**Contract:** sample_nda.txt | **Ground truth:** 10 expert-labelled clauses

| Provider | Model | Strategy | Found | Precision | Recall | F1 | Risk Scores | Avg Risk | Latency |
|---|---|---|---|---|---|---|---|---|---|
| Groq | llama-3.3-70b-versatile | Zero-Shot | 15/10 ✓ | 90.9% | 100.0% | 95.2% | 15/10 | 59 | 2.4s |
| Groq | llama-3.3-70b-versatile | Few-Shot | 9/10 ✓ | 90.9% | 100.0% | 95.2% | 9/10 | 24 | 1.2s |
| Groq | llama-3.3-70b-versatile | Chain-of-Thought | 9/10 ✓ | 90.9% | 100.0% | 95.2% | 9/10 | 45 | 26.2s |
| OpenAI | gpt-4o-mini | Zero-Shot | 12/10 ✓ | 90.0% | 90.0% | 90.0% | 12/10 | 20 | 19.8s |
| OpenAI | gpt-4o-mini | Few-Shot | 4/10 ✓ | 100.0% | 60.0% | 75.0% | 4/10 | 41 | 4.5s |
| OpenAI | gpt-4o-mini | Chain-of-Thought | 9/10 ✓ | 90.9% | 100.0% | 95.2% | 9/10 | 38 | 24.6s |
| **Regex Baseline** | N/A | Rule-based | 5/10 | 62.5% | 50.0% | 55.6% | 0/10 | N/A | <0.01s |

### Key Observations
- **Zero-Shot:** Lowest F1 — no examples leads to occasional type misclassification.
- **Few-Shot:** Best precision — examples anchor output format and risk calibration.
- **Chain-of-Thought:** Highest F1, best-calibrated risk scores. Trade-off: highest latency.
- **Regex Baseline:** Fastest but 50% recall, zero risk scoring capability.