# Phase 9 — Safety and Security Review

## OWASP Top 10 Coverage

| Risk | Mitigation | Status |
|---|---|---|
| A01 Broken Access Control | RBAC at ChromaDB data layer + JWT role validation | ✅ |
| A02 Cryptographic Failures | RS256 JWT, bcrypt-12 passwords, no secrets in code | ✅ |
| A03 Injection | Parameterised SQLAlchemy ORM, UUID validation on Redis keys | ✅ |
| A04 Insecure Design | Read-only system, audit log, flag_for_human_review guardrail | ✅ |
| A05 Security Misconfiguration | Pydantic Settings fails fast on missing keys, no debug in prod | ✅ |
| A06 Vulnerable Components | All deps pinned in requirements.txt, no langchain-xai | ✅ |
| A07 Auth Failures | Rate limiting (5 attempts/15min), account lockout, refresh rotation | ✅ |
| A08 Data Integrity | Alembic migrations, ACID PostgreSQL, append-only audit log | ✅ |
| A09 Logging Failures | structlog JSON, every auth event logged, no PII in logs | ✅ |
| A10 SSRF | No user-supplied URLs fetched, LLM calls to fixed endpoints only | ✅ |

## RBAC Security Model
**Key security property:** A prompt injection attack cannot escalate a viewer to
admin because the restricted clause text never leaves ChromaDB. The LLM only
sees what the role filter allows through.

## PII Protection Flow
## Limitations Acknowledged

1. Groq free tier (100K tokens/day) — rate limits in extended testing
2. spaCy en_core_web_sm (15MB) used instead of en_core_web_lg (750MB) — lower NER accuracy
3. No file virus scanning (ClamAV stub present but not activated)
4. Session memory cleared on Redis restart — stateless degradation mode activates
5. Judge single-pass — REVISE loop not retried when Groq quota exhausted
