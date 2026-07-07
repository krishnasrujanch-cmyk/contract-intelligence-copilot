from __future__ import annotations
from app.agents.risk_calibration import CalibrationDelta, RiskCalibrationEngine
from app.core.logging import get_logger

logger = get_logger(__name__)

_MIN_CONFIDENCE: float = 0.6


class AdaptivePromptBuilder:
    def __init__(self) -> None:
        self._engine = RiskCalibrationEngine()

    def build_calibrated_prompt(self, base_prompt: str, clause_types: list[str] | None = None) -> str:
        try:
            deltas = self._engine.get_cached_deltas()
        except Exception as exc:
            logger.warning("calibration_fetch_failed", error=str(exc))
            return base_prompt

        if not deltas:
            return base_prompt

        significant = [
            d for ctype, d in deltas.items()
            if (not clause_types or ctype in clause_types)
            and d.confidence >= _MIN_CONFIDENCE
            and d.correction != 0.0
        ]

        if not significant:
            return base_prompt

        significant.sort(key=lambda d: abs(d.correction), reverse=True)
        section = self._build_section(significant)
        logger.info("calibration_injected", count=len(significant))
        return base_prompt + "\n\n" + section

    def get_calibration_summary(self) -> str:
        try:
            deltas = self._engine.get_cached_deltas()
        except Exception as exc:
            return "Calibration unavailable: " + str(exc)

        if not deltas:
            return "No calibration data available."

        lines = [
            "### Current Risk Score Calibration",
            "",
            "| Clause Type | Correction | Confidence | Status |",
            "|---|---|---|---|",
        ]
        for d in sorted(deltas.values(), key=lambda x: abs(x.correction), reverse=True):
            if d.correction == 0.0:
                corr   = "No adjustment"
                status = "Calibrated"
            elif d.correction > 0:
                corr   = "+" + str(d.correction)
                status = "Raise by " + str(d.correction)
            else:
                corr   = str(d.correction)
                status = "Lower by " + str(abs(d.correction))
            conf = str(round(d.confidence * 100)) + "%"
            lines.append("| " + d.clause_type + " | " + corr + " | " + conf + " | " + status + " |")

        return "\n".join(lines)

    @staticmethod
    def _build_section(deltas: list[CalibrationDelta]) -> str:
        bullets = []
        for d in deltas:
            conf_pct = str(round(d.confidence * 100)) + "%"
            bullets.append("  * " + d.clause_type + ": " + d.reason + " (confidence: " + conf_pct + ")")
        bullet_text = "\n".join(bullets)
        return (
            "CALIBRATION GUIDANCE (learned from expert feedback):\n"
            + bullet_text
            + "\nApply these hints while maintaining analytical independence."
        )
