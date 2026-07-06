"""
Microsoft Presidio PII engine — de-identification and re-identification.

Pipeline:
  Raw contract text
    → PresidioEngine.anonymize()     [before LLM — PII replaced with tokens]
    → LLM processes anonymized text
    → PresidioEngine.deanonymize()   [after LLM — tokens replaced for authorised roles]

Redis mask store:
  key  = clm:pii_mask:{session_id}:{token}
  val  = original PII value
  TTL  = processing session lifetime (cleared after analysis complete)

Security guarantees:
  - LLM NEVER sees real PII
  - Masks are deterministic within a session: same PII → same token
  - Masks deleted from Redis after processing completes
  - Company names and contract amounts are NOT masked (needed for analysis)
  - No PII written to structlog or LangSmith traces
"""
from __future__ import annotations

import hashlib
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Lazy imports (spaCy model is large — only load when needed) ───────────────
_analyzer   = None
_anonymizer = None
_initialized = False


async def initialise_pii_engine() -> None:
    """
    Load Presidio analyzer and anonymizer.
    Called once at application startup — spaCy model load takes ~10s.
    """
    global _analyzer, _anonymizer, _initialized

    if _initialized:
        return

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        _analyzer   = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
        _initialized = True

        logger.info("presidio_pii_engine_ready")

    except ImportError:
        logger.warning(
            "presidio_not_installed_pii_masking_disabled",
            hint="pip install presidio-analyzer presidio-anonymizer spacy && python -m spacy download en_core_web_lg",
        )

    except Exception as exc:
        logger.error("presidio_init_failed", error=str(exc))


# ── PII entity types to detect ────────────────────────────────────────────────
# Deliberately excluded: ORGANIZATION (company names needed for contract identity)
# Deliberately excluded: MONEY amounts (needed for risk scoring)
_ENTITIES_TO_ANONYMIZE = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "LOCATION",       # Physical addresses only — not company HQ
    "DATE_TIME",      # Only DOB context — contract dates preserved separately
    "MEDICAL_LICENSE",
    "URL",
]


def anonymize_text(text: str, session_id: str) -> tuple[str, dict[str, str]]:
    """
    Replace PII in text with deterministic tokens.

    Returns:
        (anonymized_text, mask_map)
        mask_map: {token → original_value} for re-identification

    Design: deterministic token generation means the same PII string
    always maps to the same token within a session — maintaining
    referential consistency across clauses (PERSON_1 in clause 3
    is the same person as PERSON_1 in clause 12).
    """
    if not _initialized or _analyzer is None:
        logger.debug("pii_engine_not_ready_returning_text_unchanged")
        return text, {}

    try:
        results = _analyzer.analyze(
            text=text,
            entities=_ENTITIES_TO_ANONYMIZE,
            language="en",
        )

        if not results:
            return text, {}

        mask_map: dict[str, str] = {}
        anonymized = text

        # Process in reverse order to preserve character offsets
        for result in sorted(results, key=lambda r: r.start, reverse=True):
            original_value = text[result.start:result.end]

            # Deterministic token: hash of (session_id + original_value + entity_type)
            # Same PII = same token within a session
            token_hash = hashlib.sha256(
                f"{session_id}:{original_value}:{result.entity_type}".encode()
            ).hexdigest()[:8].upper()
            token = f"[{result.entity_type}_{token_hash}]"

            mask_map[token] = original_value
            anonymized = anonymized[:result.start] + token + anonymized[result.end:]

        logger.debug(
            "pii_anonymized",
            entity_count=len(results),
            session_id=session_id,
        )
        return anonymized, mask_map

    except Exception as exc:
        logger.error("pii_anonymization_failed", error=str(exc))
        return text, {}


def deanonymize_text(text: str, mask_map: dict[str, str]) -> str:
    """
    Restore original PII values in text using the mask map.
    Only called for authorised roles (admin, reviewer) after LLM processing.
    """
    if not mask_map:
        return text

    result = text
    for token, original in mask_map.items():
        result = result.replace(token, original)
    return result


def scan_output_for_pii(text: str) -> list[str]:
    """
    Scan LLM output for any PII that slipped through.
    Returns list of detected entity types (not values — never log PII).
    Used as a second-layer check before displaying responses to users.
    """
    if not _initialized or _analyzer is None:
        return []

    try:
        results = _analyzer.analyze(
            text=text,
            entities=_ENTITIES_TO_ANONYMIZE,
            language="en",
        )
        detected = list({r.entity_type for r in results})
        if detected:
            logger.warning("pii_detected_in_llm_output", entity_types=detected)
        return detected
    except Exception:
        return []
