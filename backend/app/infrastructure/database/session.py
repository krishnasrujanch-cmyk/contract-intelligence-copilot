"""
Async SQLAlchemy session management.

Design:
  - Single engine instance per process (connection pooling)
  - AsyncSession factory for dependency injection into FastAPI routes
  - Automatic transaction rollback on exception
  - Health-check utility for startup validation
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Engine factory ────────────────────────────────────────────────────────────

def _build_engine() -> AsyncEngine:
    """
    Build the async SQLAlchemy engine with production-appropriate settings.
    Called once at module import time.
    """
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_pre_ping=True,       # Validate connections before use (handles DB restarts)
        pool_recycle=3600,        # Recycle connections after 1 hour
        echo=settings.is_development and settings.debug,  # SQL logging in dev only
        echo_pool=False,
        future=True,
    )


# ── Module-level singletons ───────────────────────────────────────────────────

engine: AsyncEngine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # Prevent lazy-load issues after commit in async context
)


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an AsyncSession per request.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...

    Guarantees:
      - Session is closed after the request completes
      - Uncommitted transactions are rolled back on exception
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Context manager variant (for use outside of FastAPI) ──────────────────────

@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions outside FastAPI DI.
    Used in Celery tasks and scripts.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Health check ─────────────────────────────────────────────────────────────

async def check_database_health() -> bool:
    """
    Verify database connectivity. Used in /health endpoint.
    Returns True if database is reachable, False otherwise.
    """
    from sqlalchemy import text
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("database_health_check_failed", error=str(exc))
        return False


# ── Graceful shutdown ─────────────────────────────────────────────────────────

async def close_engine() -> None:
    """Dispose the connection pool on application shutdown."""
    await engine.dispose()
    logger.info("database_engine_disposed")
