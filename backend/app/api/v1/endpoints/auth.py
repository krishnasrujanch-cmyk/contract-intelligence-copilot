from __future__ import annotations
import uuid
from datetime import UTC, datetime, timedelta
import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.middleware.auth import CurrentUser, _get_redis
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    blocklist_key, create_access_token, create_refresh_token,
    hash_ip_address, hash_refresh_token, rate_limit_key, verify_password,
)
from app.domain.enums import AuditAction
from app.domain.models import AuditLog, RefreshToken, User
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


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


async def _check_rate_limit(ip_hash: str, redis_client: redis_async.Redis) -> None:
    key = rate_limit_key(ip_hash)
    attempts = await redis_client.incr(key)
    if attempts == 1:
        await redis_client.expire(key, settings.login_lockout_minutes * 60)
    if attempts > settings.login_max_attempts:
        ttl = await redis_client.ttl(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Try again in {max(ttl, 1)} seconds.",
            headers={"Retry-After": str(max(ttl, 1))},
        )


async def _write_audit(db, *, org_id, user_id, user_role, action, ip_hash, trace_id, context=None):
    db.add(AuditLog(
        org_id=org_id, user_id=user_id, user_role=user_role,
        action=action.value, ip_hash=ip_hash, trace_id=trace_id,
        log_context=context or {},
    ))


def _get_client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse, status_code=200,
             summary="Authenticate and receive JWT tokens")
async def login(request: Request, body: LoginRequest,
                db: AsyncSession = Depends(get_db),
                redis_client: redis_async.Redis = Depends(_get_redis)) -> TokenResponse:
    ip_hash = hash_ip_address(_get_client_ip(request))
    trace_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    await _check_rate_limit(ip_hash, redis_client)

    result = await db.execute(
        select(User).where(User.email == str(body.email), User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    dummy = "$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ok = verify_password(body.password, user.password_hash if user else dummy)

    if not user or not ok:
        if user:
            await db.execute(update(User).where(User.id == user.id)
                             .values(login_attempts=User.login_attempts + 1))
            await _write_audit(db, org_id=user.org_id, user_id=user.id,
                               user_role=user.role, action=AuditAction.LOGIN_FAILED,
                               ip_hash=ip_hash, trace_id=trace_id)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if user.locked_until and user.locked_until > datetime.now(UTC):
        secs = int((user.locked_until - datetime.now(UTC)).total_seconds())
        raise HTTPException(status_code=423, detail=f"Account locked for {secs}s.")

    access_token, jti = create_access_token(str(user.id), str(user.org_id), user.role)
    raw_refresh, refresh_hash = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=refresh_hash, jti=jti,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
        ip_hash=ip_hash,
    ))
    await db.execute(update(User).where(User.id == user.id)
                     .values(login_attempts=0, locked_until=None, last_login=datetime.now(UTC)))
    await redis_client.delete(rate_limit_key(ip_hash))
    await _write_audit(db, org_id=user.org_id, user_id=user.id, user_role=user.role,
                       action=AuditAction.LOGIN, ip_hash=ip_hash, trace_id=trace_id)
    logger.info("login_success", user_id=str(user.id), role=user.role)
    return TokenResponse(access_token=access_token, refresh_token=raw_refresh,
                         role=user.role, user_id=str(user.id), org_id=str(user.org_id))


@router.post("/logout", status_code=200,
             summary="Revoke current session tokens")
async def logout(request: Request, current_user: CurrentUser, body: RefreshRequest,
                 db: AsyncSession = Depends(get_db),
                 redis_client: redis_async.Redis = Depends(_get_redis)) -> None:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if token:
        try:
            from app.core.security import decode_access_token
            payload = decode_access_token(token)
            remaining = max(1, int((payload.expires_at - datetime.now(UTC)).total_seconds()))
            await redis_client.setex(blocklist_key(payload.jti), remaining, "1")
        except Exception:
            pass

    # Refresh token passed as X-Refresh-Token header (avoids body on 204)
    raw_refresh = request.headers.get("X-Refresh-Token", "")
    rh = hash_refresh_token(raw_refresh) if raw_refresh else ""
    res = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == rh,
                                   RefreshToken.user_id == current_user.id,
                                   RefreshToken.revoked.is_(False))
    )
    rec = res.scalar_one_or_none()
    if rec:
        await db.execute(update(RefreshToken).where(RefreshToken.id == rec.id)
                         .values(revoked=True, revoked_at=datetime.now(UTC)))
    await _write_audit(db, org_id=current_user.org_id, user_id=current_user.id,
                       user_role=current_user.role, action=AuditAction.LOGOUT,
                       ip_hash=hash_ip_address(_get_client_ip(request)),
                       trace_id=request.headers.get("X-Request-ID", str(uuid.uuid4())))
    logger.info("logout_success", user_id=str(current_user.id))


@router.post("/refresh", response_model=TokenResponse, status_code=200,
             summary="Refresh access token")
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db),
                        redis_client: redis_async.Redis = Depends(_get_redis)) -> TokenResponse:
    rh = hash_refresh_token(body.refresh_token)
    res = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == rh,
                                   RefreshToken.revoked.is_(False),
                                   RefreshToken.expires_at > datetime.now(UTC))
    )
    rec = res.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    ur = await db.execute(select(User).where(User.id == rec.user_id, User.is_active.is_(True)))
    user = ur.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or deactivated.")

    await db.execute(update(RefreshToken).where(RefreshToken.id == rec.id)
                     .values(revoked=True, revoked_at=datetime.now(UTC)))
    if rec.jti:
        await redis_client.setex(blocklist_key(rec.jti),
                                 settings.jwt_access_token_expire_minutes * 60, "1")

    new_access, new_jti = create_access_token(str(user.id), str(user.org_id), user.role)
    new_raw, new_hash = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=new_hash, jti=new_jti,
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
    ))
    return TokenResponse(access_token=new_access, refresh_token=new_raw,
                         role=user.role, user_id=str(user.id), org_id=str(user.org_id))
