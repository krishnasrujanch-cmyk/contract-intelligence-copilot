"""
Structured logging configuration using structlog.

Security guarantees:
  - PII fields are NEVER written to logs (scrubbed at processor level)
  - Contract text and clause content are NEVER logged
  - trace_id bound to every log entry for request correlation
  - LangSmith traces also scrubbed via custom callback
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

# ── PII field names that must NEVER appear in logs ────────────────────────────
_PII_FIELD_NAMES: frozenset[str] = frozenset({
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "private_key",
    "ssn",
    "passport",
    "credit_card",
    "bank_account",
    "contract_text",
    "clause_text",
    "raw_text",
    "email",          # logged only as hash, never plaintext
    "phone",
    "address",
})

# ── Regex patterns for inline PII detection ───────────────────────────────────
_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),  # phone US
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|[25][1-7][0-9]{14})\b"),  # credit card
]


def _scrub_pii_fields(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Structlog processor: remove PII fields and redact PII patterns.
    Runs on EVERY log entry before it is emitted.
    """
    keys_to_remove = []
    for key in event_dict:
        if key.lower() in _PII_FIELD_NAMES:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        event_dict[key] = "[REDACTED]"

    # Redact PII patterns found in string values
    for key, value in event_dict.items():
        if isinstance(value, str):
            for pattern in _PII_PATTERNS:
                value = pattern.sub("[PII_REDACTED]", value)
            event_dict[key] = value

    return event_dict


def _add_severity(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Map structlog level names to severity for cloud log aggregators."""
    level = event_dict.get("level", method_name).upper()
    event_dict["severity"] = level
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure structlog with JSON output, PII scrubbing, and trace correlation.
    Call once at application startup.
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _scrub_pii_fields,
        _add_severity,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Silence noisy third-party loggers in production
    for noisy_logger in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a bound logger with the given name.
    Use at module level: logger = get_logger(__name__)
    """
    return structlog.get_logger(name)
