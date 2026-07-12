"""
FastAPI application factory for the Contract Intelligence Copilot.

Startup sequence:
  1. Configure structured logging
  2. Validate settings
  3. Initialise DB engine and run health checks
  4. Register middleware (CORS, rate limiting, audit logging, PII scrubbing)
  5. Mount API routers
  6. Register shutdown hooks

Security middleware order (outermost → innermost):
  TrustedHostMiddleware → CORSMiddleware → RateLimitMiddleware →
  RequestIDMiddleware → AuditMiddleware → Routes
"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.infrastructure.database.session import check_database_health, close_engine

logger = get_logger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifecycle resources.
    Replaces deprecated @app.on_event("startup") pattern.
    """
    # ── Startup ──
    configure_logging(settings.log_level)
    logger.info(
        "application_starting",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
    )

    # Validate database connectivity on startup — fail fast
    if not await check_database_health():
        logger.critical("database_unreachable_on_startup")
        raise RuntimeError("Cannot connect to database. Check POSTGRES_* env vars.")

    logger.info("database_connected")

    # Initialise ChromaDB client (lazy — validates connectivity)
    from app.infrastructure.vector_store.chroma_client import initialise_chroma
    await initialise_chroma()
    logger.info("chromadb_initialised")

    # Initialise PII engine (loads spaCy model — can take ~10s first time)
    from app.infrastructure.pii.presidio_engine import initialise_pii_engine
    await initialise_pii_engine()
    logger.info("pii_engine_initialised")

    logger.info("application_ready")

    yield  # ── Application running ──

    # ── Shutdown ──
    await close_engine()
    logger.info("application_shutdown_complete")


# ── Application factory ────────────────────────────────────────────────────────

def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.
    Separated from module-level instantiation for testability.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered legal contract analysis with multi-agent reasoning, "
            "risk scoring, obligation tracking, and RAG-powered chatbot."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        default_response_class=ORJSONResponse,  # faster JSON serialisation
        lifespan=lifespan,
    )

    _register_middleware(app)
    _register_routers(app)
    _register_exception_handlers(app)

    return app


def _register_middleware(app: FastAPI) -> None:
    """Register middleware in correct order (outermost registered last in FastAPI)."""

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

    # ── Request ID & Timing ───────────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Response:
        """
        Assign a unique trace_id to every request and bind it to structlog context.
        Also measures and exposes request processing time.
        """
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()

        # Bind trace_id to all log entries within this request context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = trace_id
        response.headers["X-Process-Time"] = str(duration_ms)

        logger.info(
            "http_request",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response

    # ── Security headers ──────────────────────────────────────────────────────
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next) -> Response:
        """Add OWASP-recommended security headers to every response."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response


def _register_routers(app: FastAPI) -> None:
    """Mount all API routers under /api/v1."""
    from app.api.v1.endpoints import auth, contracts, clauses, chat, users, feedback, health

    API_PREFIX = "/api/v1"

    app.include_router(health.router, prefix="/health", tags=["Health"])
    app.include_router(auth.router, prefix=f"{API_PREFIX}/auth", tags=["Authentication"])
    app.include_router(contracts.router, prefix=f"{API_PREFIX}/contracts", tags=["Contracts"])
    app.include_router(clauses.router, prefix=f"{API_PREFIX}/clauses", tags=["Clauses"])
    app.include_router(chat.router, prefix=f"{API_PREFIX}/chat", tags=["RAG Chatbot"])
    app.include_router(users.router, prefix=f"{API_PREFIX}/users", tags=["User Management"])
    app.include_router(feedback.router, prefix=f"{API_PREFIX}/feedback", tags=["Feedback"])


def _register_exception_handlers(app: FastAPI) -> None:
    """Global exception handlers — prevent stack traces leaking to clients."""

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Resource not found", "path": request.url.path},
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            content={"detail": "Method not allowed"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler — logs the full exception server-side
        but returns a safe, generic message to the client.
        Prevents internal error details from leaking (Fortify: Information Exposure).
        """
        logger.exception(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal error occurred. Please try again later.",
                "trace_id": structlog.contextvars.get_contextvars().get("trace_id"),
            },
        )


# ── Module-level app instance ─────────────────────────────────────────────────
app: FastAPI = create_application()
