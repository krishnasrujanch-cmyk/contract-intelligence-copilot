"""
FastAPI authentication and authorization dependencies.

Usage in route handlers:
    # Require any authenticated user
    current_user = Depends(get_current_user)

    # Require admin role
    current_user = Depends(require_role(UserRole.ADMIN))

    # Require admin or reviewer
    current_user = Depends(require_any_role(UserRole.ADMIN, UserRole.REVIEWER))

Design:
  - JWT verified on every request (stateless)
  - JTI checked against Redis blocklist (handles logout)
  - Role check happens BEFORE any business logic (fail fast)
  - All failures logged with trace_id for audit correlation
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import redis.asyncio as redis_async
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    TokenExpiredError,
    TokenPayload,
    TokenVerificationError,
    blocklist_key,
    decode_access_token,
)
from app.domain.enums import UserRole
from app.domain.models import User
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# ── Redis client (module-level singleton) ─────────────────────────────────────

_redis_client: redis_async.Redis | None = None


async def _get_redis() -> redis_async.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ── Token extraction ───────────────────────────────────────────────────────────

async def _extract_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Extract JWT from Authorization: Bearer <token> header."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ── JWT verification ───────────────────────────────────────────────────────────

async def _verify_token(
    token: str = Depends(_extract_token),
    redis_client: redis_async.Redis = Depends(_get_redis),
) -> TokenPayload:
    """
    Decode JWT and verify it has not been revoked (blocklist check).

    Raises 401 on:
      - Invalid or malformed token
      - Expired token
      - Revoked token (JTI in Redis blocklist)
    """
    try:
        payload = decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired. Please refresh your session.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenVerificationError as exc:
        logger.warning("invalid_token_rejected", reason=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check JTI blocklist — catches logged-out tokens
    is_revoked = await redis_client.exists(blocklist_key(payload.jti))
    if is_revoked:
        logger.warning("revoked_token_used", jti=payload.jti)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ── User hydration ────────────────────────────────────────────────────────────

async def get_current_user(
    payload: TokenPayload = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the authenticated User from the JWT sub claim.
    Ensures the user still exists and is active.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(User).where(User.id == payload.user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("user_not_found_or_inactive", user_id=payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated.",
        )

    return user


# ── Role-based access control ─────────────────────────────────────────────────

def require_role(*roles: UserRole) -> Callable:
    """
    Dependency factory: returns a dependency that enforces one of the given roles.

    Usage:
        @router.post("/admin-only")
        async def endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...

        @router.get("/admin-or-reviewer")
        async def endpoint(user: User = Depends(require_role(UserRole.ADMIN, UserRole.REVIEWER))):
            ...
    """
    allowed_roles = frozenset(r.value for r in roles)

    async def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                "authorization_denied",
                user_id=str(current_user.id),
                user_role=current_user.role,
                required_roles=list(allowed_roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied. Required role(s): {', '.join(allowed_roles)}. "
                    f"Your role: {current_user.role}."
                ),
            )
        return current_user

    return _check_role


# ── Convenience type aliases ──────────────────────────────────────────────────
# Use these in route signatures for cleaner code

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
ReviewerUser = Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.REVIEWER))]
AnyAuthenticatedUser = Annotated[User, Depends(get_current_user)]
