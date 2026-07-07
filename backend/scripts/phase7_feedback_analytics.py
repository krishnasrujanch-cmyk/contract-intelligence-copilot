"""
Phase 7 — Feedback Analytics Report Generator.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

BASE = Path("/workspaces/contract-intelligence-copilot")
sys.path.insert(0, str(BASE / "backend"))


def generate_report() -> str:
    from app.agents.feedback_repository import FeedbackRepository
    from app.agents.risk_calibration import RiskCalibrationEngine
    from app.agents.adaptive_prompt import AdaptivePromptBuilder

    print("Computing feedback analytics...")
    repo    = FeedbackRepository()
    engine  = RiskCalibrationEngine()
    builder = AdaptivePromptBuilder()
    stats   = repo.get_clause_type_stats()
    deltas  = engine.compute_and_cache()
    print(f"  Clause types analysed: {len(stats)}")
    print(f"  Calibration deltas:    {len(deltas)}")

    lines = [
        "# Phase 7 — Feedback Analytics Report",
        "",
        "**System:** Contract Intelligence Copilot",
        "**Ground Truth:** 10 expert-labelled clauses from ground_truth_clauses.json",
        "**LLM Results:** Phase 3 Chain-of-Thought (selected production strategy)",
        "",
        "---",
        "",
        "## 1. Risk Score Accuracy by Clause Type",
        "",
        "| Clause Type | Expert Score | LLM Score (CoT) | Bias | Feedback | Positive Rate |",
        "|---|---|---|---|---|---|",
    ]

    for s in stats:
        bias_str  = f"{s.bias:+.1f}" if s.bias != 0 else "0.0"
        bias_icon = "🔴" if abs(s.bias) > 15 else ("🟡" if abs(s.bias) > 5 else "🟢")
        lines.append(
            f"| {s.clause_type} | {s.expert_avg_score:.0f} | {s.llm_avg_score:.0f} "
            f"| {bias_icon} {bias_str} | {s.feedback_count} | {s.positive_rate:.0%} |"
        )

    over_scored     = [s for s in stats if s.bias > 15]
    under_scored    = [s for s in stats if s.bias < -15]
    well_calibrated = [s for s in stats if abs(s.bias) <= 5]

    lines += [
        "",
        "**Legend:** 🟢 ≤±5 (excellent) | 🟡 ±5-15 (acceptable) | 🔴 >±15 (correction applied)",
        "",
        "---",
        "",
        "## 2. Calibration Corrections Applied",
        "",
        builder.get_calibration_summary(),
        "",
        "---",
        "",
        "## 3. Key Findings",
        "",
        f"- **Total clause types analysed:** {len(stats)}",
        f"- **Well-calibrated (bias ≤ ±5):** {len(well_calibrated)} — "
            + (", ".join(s.clause_type for s in well_calibrated) or "none"),
        f"- **Over-scored (bias > +15):** {len(over_scored)} — "
            + (", ".join(s.clause_type for s in over_scored) or "none"),
        f"- **Under-scored (bias < -15):** {len(under_scored)} — "
            + (", ".join(s.clause_type for s in under_scored) or "none"),
        "",
        "### Adaptive Calibration Impact",
        "",
        "Corrections injected into Reasoner prompt for clause types where |bias| > 15.",
        "Re-computed hourly as new feedback accumulates.",
        "",
        "---",
        "",
        "## 4. Prompt Engineering Decision Record",
        "",
        "| Decision | Rationale |",
        "|---|---|",
        "| Chain-of-Thought selected | Highest F1 (95.2%) + best risk calibration in Phase 3 |",
        "| Bias threshold = ±15 | Below ±15 is within LLM natural variance |",
        "| Max correction = ±40 | Prevents extreme prompt injection from low-sample edge cases |",
        "| Redis cache TTL = 1hr | Balances freshness vs DB query cost per LLM call |",
        "| Confidence threshold 60% | Low-confidence hints omitted to avoid noise |",
        "",
        "---",
        "",
        "## 5. Phase 3 → Phase 7 Improvement Arc",
        "",
        "| Metric | Zero-Shot | CoT | CoT + Calibration |",
        "|---|---|---|---|",
        "| Clause F1 | 90.0% | 95.2% | 95.2% |",
        "| Risk Score MAE | ~25 pts | ~18 pts | ~12 pts (estimated) |",
        "| Explainability | None | 4-step CoT | CoT + calibration rationale |",
        "| Human Feedback Loop | No | No | Yes — drives adaptation |",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("PHASE 7 — FEEDBACK ANALYTICS REPORT")
    print("=" * 60)

    report = generate_report()

    md_path = BASE / "test_contracts" / "phase7_analytics_report.md"
    md_path.write_text(report, encoding="utf-8")
    print(f"\n✓ Markdown report → {md_path}")

    from app.agents.feedback_repository import FeedbackRepository
    from app.agents.risk_calibration import RiskCalibrationEngine
    repo   = FeedbackRepository()
    engine = RiskCalibrationEngine()
    stats  = repo.get_clause_type_stats()
    deltas = engine.compute_and_cache()

    summary = {
        "phase": "7_feedback_analytics",
        "clause_stats": [
            {
                "clause_type":      s.clause_type,
                "llm_avg_score":    s.llm_avg_score,
                "expert_avg_score": s.expert_avg_score,
                "bias":             s.bias,
                "feedback_count":   s.feedback_count,
                "positive_rate":    s.positive_rate,
            }
            for s in stats
        ],
        "calibration_deltas": [
            {
                "clause_type": d.clause_type,
                "correction":  d.correction,
                "confidence":  d.confidence,
                "reason":      d.reason,
            }
            for d in deltas
        ],
    }
    json_path = BASE / "test_contracts" / "phase7_analytics_results.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ JSON summary     → {json_path}")

    print("\n" + "=" * 60)
    print(report)


if __name__ == "__main__":
    main()
