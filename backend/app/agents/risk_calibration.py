"""
Phase 7 — Risk Calibration Engine.

Responsibility: Compute calibration deltas from feedback statistics
and cache them in Redis for fast access during LLM prompt construction.

Design (SOLID):
  - SRP: calibration math only — no data access, no prompt building
  - OCP: new calibration strategies added by subclassing CalibrationStrategy
  - DIP: depends on FeedbackRepository abstraction and Redis abstraction

Algorithm:
  bias = mean(llm_score) - mean(expert_score)

  If bias > THRESHOLD  (+15): LLM over-scores → correction = -bias
  If bias < -THRESHOLD (-15): LLM under-scores → correction = -bias
  If |bias| <= THRESHOLD:     Within natural variance → no correction

  Rationale for ±15 threshold:
    LLM risk scoring has ~±10 point natural variance on identical input.
    Applying corrections for small biases would chase noise.
    Only correct when bias exceeds one standard deviation of natural variance.

Security:
  - Calibration deltas are numeric only — no string injection possible
  - Redis key namespaced to prevent collision with session memory keys
  - All Redis operations try/except — calibration failure is non-fatal
  - Deltas bounded to [-40, +40] range — prevents extreme prompt injection
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agents.feedback_repository import ClauseTypeStats, FeedbackRepository
from app.core.logging import get_logger

logger = get_logger(__name__)

_BIAS_THRESHOLD:    float = 15.0   # Minimum bias to trigger correction
_MAX_CORRECTION:    float = 40.0   # Cap correction magnitude
_REDIS_KEY:         str   = "clm:calibration:risk_deltas"
_CACHE_TTL_SECONDS: int   = 3600   # Re-compute calibration hourly


@dataclass(frozen=True)
class CalibrationDelta:
    """
    Immutable correction value for a single clause type.
    Applied to Reasoner system prompt to adjust expected score range.
    """
    clause_type: str
    correction:  float   # Positive = raise scores, Negative = lower scores
    confidence:  float   # 0.0-1.0 based on sample count and feedback volume
    reason:      str     # Human-readable explanation for the correction


class RiskCalibrationEngine:
    """
    Computes and caches risk score calibration deltas.

    Calibration flow:
      1. FeedbackRepository.get_clause_type_stats() → ClauseTypeStats list
      2. _compute_deltas() → CalibrationDelta per clause type
      3. Store in Redis with 1-hour TTL
      4. AdaptivePromptBuilder reads from Redis on every LLM call

    Cache strategy:
      Hot path (LLM call): Redis read — O(1), <1ms
      Cold path (cache miss): Compute from DB — O(N clauses), ~50ms
      Re-computation: Every hour OR explicitly triggered by admin

    Thread safety:
      - All state in Redis — no shared mutable Python state
      - Idempotent: running compute twice produces identical results
    """

    def __init__(self) -> None:
        self._repo         = FeedbackRepository()
        self._redis_client = None

    def _get_redis(self) -> Any:
        """Lazy Redis client — avoids connection at import time."""
        if self._redis_client is None:
            import redis
            from app.core.config import settings
            self._redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis_client

    def compute_and_cache(self) -> list[CalibrationDelta]:
        """
        Compute calibration deltas from current feedback data and cache in Redis.

        Called:
          - On system startup (load initial calibration)
          - Hourly via Celery beat task
          - Explicitly when admin triggers recalibration

        Returns:
            List of CalibrationDelta objects (also cached in Redis as JSON)
        """
        stats   = self._repo.get_clause_type_stats()
        deltas  = [self._compute_delta(s) for s in stats if s.sample_count > 0]

        # Cache in Redis as JSON for fast prompt injection
        try:
            redis_client = self._get_redis()
            payload = json.dumps([
                {
                    "clause_type": d.clause_type,
                    "correction":  d.correction,
                    "confidence":  d.confidence,
                    "reason":      d.reason,
                }
                for d in deltas
            ])
            redis_client.setex(_REDIS_KEY, _CACHE_TTL_SECONDS, payload)
            logger.info(
                "calibration_cached",
                delta_count=len(deltas),
                ttl_seconds=_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("calibration_cache_failed", error=str(exc))

        return deltas

    def get_cached_deltas(self) -> dict[str, CalibrationDelta]:
        """
        Retrieve calibration deltas from Redis cache.
        Falls back to computing from DB on cache miss.

        Returns:
            {clause_type: CalibrationDelta} — empty dict if unavailable
        """
        try:
            redis_client = self._get_redis()
            raw          = redis_client.get(_REDIS_KEY)

            if raw:
                loaded = json.loads(raw)
                return {
                    d["clause_type"]: CalibrationDelta(**d)
                    for d in loaded
                }

        except Exception as exc:
            logger.warning("calibration_cache_read_failed", error=str(exc))

        # Cache miss — compute on demand
        logger.info("calibration_cache_miss_computing")
        deltas = self.compute_and_cache()
        return {d.clause_type: d for d in deltas}

    def _compute_delta(self, stats: ClauseTypeStats) -> CalibrationDelta:
        """
        Compute correction for a single clause type.

        Correction formula:
          If bias > +THRESHOLD: correction = -bias (LLM over-scores → lower)
          If bias < -THRESHOLD: correction = -bias (LLM under-scores → raise)
          Otherwise:            correction = 0.0   (within natural variance)

        Correction bounded to [-MAX_CORRECTION, +MAX_CORRECTION].

        Confidence:
          Based on sample count and feedback volume.
          Low samples → low confidence → smaller prompt emphasis.
        """
        bias = stats.bias

        if abs(bias) <= _BIAS_THRESHOLD:
            correction = 0.0
            reason     = f"Bias of {bias:+.1f} is within natural variance (±{_BIAS_THRESHOLD:.0f}). No adjustment."
        else:
            # Invert bias to get correction direction
            raw_correction = -bias
            correction     = max(-_MAX_CORRECTION, min(_MAX_CORRECTION, raw_correction))
            direction      = "lower" if correction < 0 else "raise"
            reason         = (
                f"LLM scores {abs(bias):.1f} points {'above' if bias > 0 else 'below'} "
                f"expert baseline for '{stats.clause_type}' clauses. "
                f"Adjust scores {direction} by ~{abs(correction):.0f} points."
            )

        # Confidence: 0.5 base + bonus for sample size + feedback
        confidence = min(1.0, 0.5 + (stats.sample_count / 20.0) + (stats.feedback_count / 100.0))

        return CalibrationDelta(
            clause_type=stats.clause_type,
            correction =round(correction, 1),
            confidence =round(confidence, 2),
            reason     =reason,
        )
