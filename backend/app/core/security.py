"""
Security utilities: JWT (RS256), password hashing, and token revocation.

Security design:
  - RS256 asymmetric signing: private key signs, public key verifies
  - Access tokens: 15-minute expiry — short-lived by design
  - Refresh tokens: opaque reference stored in Redis, rotated on every use
  - JTI (JWT ID) blocklist in Redis for immediate revocation on logout
  - bcrypt cost factor 12 — resistant to GPU brute-force
  - Constant-time comparison in all sensitive operations
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── JWT key loading ────────────────────────────────────────────────────────────

def _load_private_key() -> str:
    """Load RS256 private key from file system. Fails fast if missing."""
    key_path = Path(settings.jwt_private_key_path)
    if not key_path.exists():
        raise FileNotFoundError(
            f"JWT private key not found at {key_path}. "
            "Run: openssl genrsa -out keys/private.pem 2048"
        )
    return key_path.read_text(encoding="utf-8")


def _load_public_key() -> str:
    """Load RS256 public key from file system."""
    key_path = Path(settings.jwt_public_key_path)
    if not key_path.exists():
        raise FileNotFoundError(
            f"JWT public key not found at {key_path}. "
            "Run: openssl rsa -in keys/private.pem -pubout -out keys/public.pem"
        )
    return key_path.read_text(encoding="utf-8")


# Load keys once at module import — fail fast if missing in production
try:
    _PRIVATE_KEY: str = _load_private_key()
    _PUBLIC_KEY: str = _load_public_key()
except FileNotFoundError:
    if settings.is_production:
        raise
    # Development fallback: log warning but don't crash
    logger.warning(
        "jwt_keys_not_found_using_dev_fallback",
        hint="Generate keys with scripts/generate_keys.sh before production deployment",
    )
    # Generate ephemeral keys for development only
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    _rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _PRIVATE_KEY = _rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    _PUBLIC_KEY = _rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    Cost factor 12 — ~250ms per hash on modern hardware.
    """
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """
    Constant-time bcrypt comparison — prevents timing attacks.
    Returns False (not exception) on mismatch.
    """
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT token creation ─────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    org_id: str,
    role: str,
    jti: str | None = None,
) -> tuple[str, str]:
    """
    Create a signed RS256 JWT access token.

    Returns:
        (token, jti) — jti is the unique token ID used for revocation

    Payload fields:
        sub  — subject (user_id)
        org  — organisation_id
        role — user role for RBAC
        jti  — unique token ID (for blocklist revocation)
        iss  — issuer
        iat  — issued at
        exp  — expiry
    """
    now = datetime.now(UTC)
    token_jti = jti or str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub":  str(user_id),
        "org":  str(org_id),
        "role": role,
        "jti":  token_jti,
        "iss":  settings.jwt_issuer,
        "iat":  now,
        "exp":  now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "type": "access",
    }

    token = jwt.encode(payload, _PRIVATE_KEY, algorithm=settings.jwt_algorithm)
    return token, token_jti


def create_refresh_token() -> tuple[str, str]:
    """
    Generate an opaque refresh token and its SHA-256 hash.

    The raw token is sent to the client.
    The hash is stored in the database.

    Returns:
        (raw_token, token_hash)
    """
    raw_token = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_refresh_token(raw_token: str) -> str:
    """Hash a raw refresh token for database lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ── JWT verification ──────────────────────────────────────────────────────────

class TokenPayload:
    """Typed wrapper around decoded JWT claims."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.user_id: str = payload["sub"]
        self.org_id: str = payload["org"]
        self.role: str = payload["role"]
        self.jti: str = payload["jti"]
        self.expires_at: datetime = datetime.fromtimestamp(payload["exp"], tz=UTC)
        self.issued_at: datetime = datetime.fromtimestamp(payload["iat"], tz=UTC)


class TokenVerificationError(Exception):
    """Raised when a JWT fails verification."""
    pass


class TokenExpiredError(TokenVerificationError):
    """Raised when a JWT has expired."""
    pass


def decode_access_token(token: str) -> TokenPayload:
    """
    Decode and verify an RS256 JWT access token.

    Raises:
        TokenExpiredError   — if the token has expired
        TokenVerificationError — if the token is invalid for any other reason
    """
    try:
        payload = jwt.decode(
            token,
            _PUBLIC_KEY,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True, "verify_iss": True},
        )
        return TokenPayload(payload)
    except ExpiredSignatureError:
        raise TokenExpiredError("Access token has expired")
    except JWTError as exc:
        raise TokenVerificationError(f"Invalid access token: {exc}") from exc


# ── IP hashing (for audit log — GDPR compliant) ───────────────────────────────

def hash_ip_address(ip: str) -> str:
    """
    One-way hash of an IP address for audit logging.
    We record that a request came from a unique source without storing the IP.
    """
    return hashlib.sha256(
        f"{ip}:{settings.secret_key}".encode("utf-8")
    ).hexdigest()[:16]  # First 16 chars — sufficient for uniqueness in logs


# ── Token blocklist helpers ───────────────────────────────────────────────────
# Redis key patterns — kept consistent for reliable lookup

def blocklist_key(jti: str) -> str:
    """Redis key for a blocklisted JWT JTI."""
    return f"clm:jwt_blocklist:{jti}"


def rate_limit_key(ip_hash: str) -> str:
    """Redis key for login rate limiting per IP."""
    return f"clm:rate_limit:login:{ip_hash}"
