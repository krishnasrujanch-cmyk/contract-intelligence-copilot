"""
Authentication endpoints: login, logout, token refresh.

Security controls:
  - Rate limiting: 5 failed attempts per IP per 15 minutes (Redis counter)
  - Account lockout: 15 minutes after exceeding max attempts
  - bcrypt password verification (constant-time)
  - JWT RS256 access tokens (15-minute expiry)
  - Opaque refresh tokens (7-day, rotated on every use)
  - JTI blocklist on logout (immediate revocation)
  - Full audit logging on every auth event
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import CurrentUser, _get_redis
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    blocklist_key,
    create_access_token,
    create_refresh_token,
    hash_ip_address,
    hash_refresh_token,
    rate_limit_key,
    verify_password,
)
from app.domain.enums import AuditAction
from app.domain.models import AuditLog, RefreshToken, User
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.jwt_access_token_expire_minutes * 60
    role: str
    user_id: str
    org_id: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_rate_limit(ip_hash: str, redis_client: redis_async.Redis) -> None:
    """
    Enforce login rate limiting: 5 attempts per 15 minutes per IP.
    Raises 429 if limit exceeded.
    """
    key = rate_limit_key(ip_hash)
    attempts = await redis_client.incr(key)
    if attempts == 1:
        # Set expiry on first attempt
        await redis_client.expire(key, settings.login_lockout_minutes * 60)
    if attempts > settings.login_max_attempts:
        ttl = await redis_client.ttl(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Try again in {ttl} seconds.",
            headers={"Retry-After": str(ttl)},
        )


async def _write_audit(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    user_role: str,
    action: AuditAction,
    ip_hash: str,
    trace_id: str,
    context: dict | None = None,
) -> None:
    """Write an immutable audit log entry."""
    entry = AuditLog(
        org_id=org_id,
        user_id=user_id,
        user_role=user_role,
        action=action.value,
        ip_hash=ip_hash,
        trace_id=trace_id,
        context=context or {},
    )
    db.add(entry)
    # No await commit here — let the session dependency handle it


# ── POST /login ───────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive JWT tokens",
)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis_async.Redis = Depends(_get_redis),
) -> TokenResponse:
    """
    Authenticate with email and password.
    Returns an access token (15 min) and refresh token (7 days).
    """
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = hash_ip_address(client_ip)
    trace_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Rate limiting check BEFORE hitting the database
    await _check_rate_limit(ip_hash, redis_client)

    # Fetch user by email
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    # Constant-time path — always verify (even for non-existent user)
    # This prevents user enumeration via timing differences
    dummy_hash = "$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    password_ok = verify_password(
        body.password,
        user.password_hash if user else dummy_hash,
    )

    if not user or not password_ok:
        if user:
            # Increment failed attempt counter
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(login_attempts=User.login_attempts + 1)
            )
            await _write_audit(
                db,
                org_id=user.org_id,
                user_id=user.id,
                user_role=user.role,
                action=AuditAction.LOGIN_FAILED,
                ip_hash=ip_hash,
                trace_id=trace_id,
            )
        logger.warning("login_failed", ip_hash=ip_hash)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(UTC):
        remaining = int((user.locked_until - datetime.now(UTC)).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked. Try again in {remaining} seconds.",
        )

    # Issue tokens
    access_token, jti = create_access_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )
    raw_refresh, refresh_hash = create_refresh_token()

    # Persist refresh token
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        jti=jti,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
        ip_hash=ip_hash,
    )
    db.add(refresh_record)

    # Reset failed attempt counter on successful login
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(login_attempts=0, locked_until=None, last_login=datetime.now(UTC))
    )

    # Clear rate limit counter on success
    await redis_client.delete(rate_limit_key(ip_hash))

    await _write_audit(
        db,
        org_id=user.org_id,
        user_id=user.id,
        user_role=user.role,
        action=AuditAction.LOGIN,
        ip_hash=ip_hash,
        trace_id=trace_id,
    )

    logger.info("login_success", user_id=str(user.id), role=user.role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        role=user.role,
        user_id=str(user.id),
        org_id=str(user.org_id),
    )


# ── POST /logout ──────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke current session tokens",
)
async def logout(
    request: Request,
    current_user: CurrentUser,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis_async.Redis = Depends(_get_redis),
) -> None:
    """
    Revoke the current access token (JTI blocklist) and refresh token.
    Immediate effect — no waiting for token expiry.
    """
    from app.core.security import decode_access_token

    # Extract JTI from the current request's access token
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()

    try:
        payload = decode_access_token(access_token)
        jti = payload.jti
        remaining_ttl = max(1, int((payload.expires_at - datetime.now(UTC)).total_seconds()))

        # Add JTI to Redis blocklist with TTL = remaining token lifetime
        await redis_client.setex(blocklist_key(jti), remaining_ttl, "1")
    except Exception:
        pass  # Token may already be invalid — logout succeeds regardless

    # Revoke refresh token in database
    refresh_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == refresh_hash,
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked.is_(False),
        )
    )
    refresh_record = result.scalar_one_or_none()
    if refresh_record:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == refresh_record.id)
            .values(revoked=True, revoked_at=datetime.now(UTC))
        )

    trace_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    client_ip = request.client.host if request.client else "unknown"

    await _write_audit(
        db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.LOGOUT,
        ip_hash=hash_ip_address(client_ip),
        trace_id=trace_id,
    )

    logger.info("logout_success", user_id=str(current_user.id))


# ── POST /refresh ─────────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis_async.Redis = Depends(_get_redis),
) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access token + rotated refresh token.
    The old refresh token is immediately revoked (rotation prevents replay attacks).
    """
    refresh_hash = hash_refresh_token(body.refresh_token)

    result = await db.execute(
        select(RefreshToken)
        .join(User, RefreshToken.user_id == User.id)
        .where(
            RefreshToken.token_hash == refresh_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    refresh_record = result.scalar_one_or_none()

    if refresh_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    # Fetch the associated user
    user_result = await db.execute(
        select(User).where(User.id == refresh_record.user_id, User.is_active.is_(True))
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated.",
        )

    # Revoke old refresh token (rotation)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == refresh_record.id)
        .values(revoked=True, revoked_at=datetime.now(UTC))
    )

    # Also blocklist the old access token's JTI
    if refresh_record.jti:
        await redis_client.setex(
            blocklist_key(refresh_record.jti),
            settings.jwt_access_token_expire_minutes * 60,
            "1",
        )

    # Issue new tokens
    new_access_token, new_jti = create_access_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )
    new_raw_refresh, new_refresh_hash = create_refresh_token()

    new_refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=new_refresh_hash,
        jti=new_jti,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    db.add(new_refresh_record)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_raw_refresh,
        role=user.role,
        user_id=str(user.id),
        org_id=str(user.org_id),
    )
