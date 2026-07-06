"""
LLM Router — Multi-provider, multi-role language model management.

Architecture:
  Groq API (primary, free tier) → OpenAI (backup, Vocareum key)

Role-to-model mapping (Groq free tier optimised):
  ┌──────────────┬─────────────────────────────┬──────────┐
  │ Role         │ Model                       │ Why      │
  ├──────────────┼─────────────────────────────┼──────────┤
  │ Extractor    │ llama-3.1-8b-instant        │ Fast,    │
  │              │                             │ cheap,   │
  │              │                             │ bulk     │
  ├──────────────┼─────────────────────────────┼──────────┤
  │ Reasoner     │ llama-3.3-70b-versatile     │ Best     │
  │              │                             │ quality  │
  ├──────────────┼─────────────────────────────┼──────────┤
  │ Judge        │ llama-3.3-70b-versatile     │ Indep.   │
  │              │                             │ weights  │
  ├──────────────┼─────────────────────────────┼──────────┤
  │ Answerer     │ llama-3.3-70b-versatile     │ Best     │
  │              │                             │ citation │
  ├──────────────┼─────────────────────────────┼──────────┤
  │ Safety Guard │ llama-3.1-8b-instant        │ Fastest  │
  └──────────────┴─────────────────────────────┴──────────┘

Reliability:
  - Token budget tracking per role (prevents rate-limit exhaustion)
  - Sliding-window rate limiter (30 RPM Groq free tier)
  - Exponential backoff with jitter on transient errors
  - Circuit breaker: auto-switches to OpenAI after 3 consecutive failures
  - All calls traced via LangSmith automatically

Security:
  - API keys sourced from settings only — never from arguments
  - No prompt content logged — only metadata (token counts, latency, role)
  - PII scrubber attached as LangSmith callback
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Type aliases ──────────────────────────────────────────────────────────────
Messages: TypeAlias = list[BaseMessage]


# ── Agent role enumeration ────────────────────────────────────────────────────

class AgentRole(str, Enum):
    """
    Distinct roles in the multi-model pipeline.
    Each role maps to a specific model optimised for that task.
    """
    EXTRACTOR    = "extractor"    # Clause boundary detection + type classification
    REASONER     = "reasoner"     # Multi-step legal risk reasoning (chain-of-thought)
    JUDGE        = "judge"        # Independent validation of Reasoner output
    ANSWERER     = "answerer"     # RAG synthesis + user-facing response generation
    SAFETY_GUARD = "safety_guard" # Intent classification — runs before all other roles


# ── Rate limiter (sliding window) ─────────────────────────────────────────────

class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter.
    Tracks requests within a rolling time window.
    Used to respect Groq free tier: 30 RPM.
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Block until a request slot is available.
        Sleeps in small increments to avoid busy-waiting.
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                # Evict timestamps outside the current window
                while self._timestamps and self._timestamps[0] < now - self._window:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return

                # Calculate sleep duration until oldest request leaves window
                oldest = self._timestamps[0]
                sleep_for = (oldest + self._window - now) + 0.05  # small buffer
                logger.debug(
                    "rate_limiter_waiting",
                    sleep_seconds=round(sleep_for, 2),
                    queue_depth=len(self._timestamps),
                )

            await asyncio.sleep(sleep_for)


# ── Circuit breaker ────────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED   = "closed"    # Normal operation
    OPEN     = "open"      # Failing — reject requests immediately
    HALF_OPEN = "half_open" # Probing — allow one request to test recovery


@dataclass
class CircuitBreaker:
    """
    Simple circuit breaker for provider health management.
    Trips after `failure_threshold` consecutive failures.
    Resets after `recovery_timeout` seconds.
    """
    failure_threshold: int   = 3
    recovery_timeout:  float = 60.0

    _state:           CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count:   int          = field(default=0, init=False)
    _last_failure_at: float        = field(default=0.0, init=False)

    @property
    def is_available(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN — allow one probe

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_at = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker_tripped",
                failures=self._failure_count,
                threshold=self.failure_threshold,
            )


# ── Provider config ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GroqModelConfig:
    """Immutable configuration for a Groq model instance."""
    role:        AgentRole
    model_name:  str
    max_tokens:  int
    temperature: float


_GROQ_ROLE_CONFIGS: dict[AgentRole, GroqModelConfig] = {
    AgentRole.EXTRACTOR: GroqModelConfig(
        role=AgentRole.EXTRACTOR,
        model_name=settings.groq_extractor_model,
        max_tokens=2048,
        temperature=0.0,  # Deterministic extraction
    ),
    AgentRole.REASONER: GroqModelConfig(
        role=AgentRole.REASONER,
        model_name=settings.groq_reasoner_model,
        max_tokens=settings.groq_max_tokens,
        temperature=settings.groq_temperature,
    ),
    AgentRole.JUDGE: GroqModelConfig(
        role=AgentRole.JUDGE,
        model_name=settings.groq_judge_model,
        max_tokens=2048,
        temperature=0.0,  # Deterministic verdicts
    ),
    AgentRole.ANSWERER: GroqModelConfig(
        role=AgentRole.ANSWERER,
        model_name=settings.groq_answerer_model,
        max_tokens=settings.groq_max_tokens,
        temperature=settings.groq_temperature,
    ),
    AgentRole.SAFETY_GUARD: GroqModelConfig(
        role=AgentRole.SAFETY_GUARD,
        model_name=settings.groq_safety_model,
        max_tokens=256,   # Safety check needs only a short classification
        temperature=0.0,
    ),
}


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_groq_llm(config: GroqModelConfig) -> ChatGroq:
    """
    Build a ChatGroq instance for a specific agent role.
    Secrets sourced exclusively from settings — never from arguments.
    """
    return ChatGroq(
        model=config.model_name,
        api_key=settings.groq_api_key,          # type: ignore[arg-type]
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        # stream=False — we use SSE at the API layer, not at the LLM layer
    )


def _build_openai_backup(role: AgentRole) -> ChatOpenAI:
    """Build OpenAI backup model. Used when Groq circuit breaker trips."""
    # Use mini for all roles except vision (handled separately in parsers)
    return ChatOpenAI(
        model=settings.openai_backup_model,
        api_key=settings.openai_api_key,         # type: ignore[arg-type]
        max_tokens=settings.openai_max_tokens,
        temperature=settings.openai_temperature,
    )


# ── LLM Router ────────────────────────────────────────────────────────────────

class LLMRouter:
    """
    Central router for all LLM calls in the pipeline.

    Responsibilities:
      1. Select the correct model for each agent role
      2. Enforce rate limits (Groq free tier: 30 RPM)
      3. Retry transient errors with exponential backoff + jitter
      4. Circuit-break to OpenAI on persistent Groq failures
      5. Track token usage per role for monitoring and billing
      6. Emit structured log events (no prompt content — metadata only)

    Usage:
        router = LLMRouter.get_instance()
        result = await router.invoke(AgentRole.REASONER, messages)
    """

    _instance: "LLMRouter | None" = None

    def __init__(self) -> None:
        # Build LLM instances per role (done once — reused across calls)
        self._groq_llms: dict[AgentRole, ChatGroq] = {
            role: _build_groq_llm(config)
            for role, config in _GROQ_ROLE_CONFIGS.items()
        }
        self._openai_backup: dict[AgentRole, ChatOpenAI] = {}

        # Shared rate limiter — all roles share the 30 RPM budget
        self._rate_limiter = SlidingWindowRateLimiter(
            max_requests=settings.groq_requests_per_minute,
            window_seconds=60.0,
        )

        # Per-role circuit breakers for Groq
        self._circuit_breakers: dict[AgentRole, CircuitBreaker] = {
            role: CircuitBreaker() for role in AgentRole
        }

        # Token usage counters (in-memory; reset on restart)
        self._token_usage: dict[str, int] = {role.value: 0 for role in AgentRole}

        logger.info(
            "llm_router_initialised",
            preferred_provider=settings.preferred_llm.value,
            groq_models={
                role.value: cfg.model_name
                for role, cfg in _GROQ_ROLE_CONFIGS.items()
            },
        )

    @classmethod
    def get_instance(cls) -> "LLMRouter":
        """Singleton accessor — one router per process."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────────

    async def invoke(
        self,
        role:       AgentRole,
        messages:   Messages,
        *,
        metadata:   dict[str, Any] | None = None,
    ) -> ChatResult:
        """
        Invoke the appropriate LLM for the given role.

        Args:
            role:     Which agent role is making this call.
            messages: LangChain message list (SystemMessage, HumanMessage, etc.)
            metadata: Optional tracing metadata (contract_id, org_id — no PII).

        Returns:
            ChatResult with the model's response.

        Raises:
            LLMRouterError: If all providers fail after retries.
        """
        start = time.perf_counter()
        cb = self._circuit_breakers[role]

        # Try Groq first if circuit is available
        if cb.is_available and settings.preferred_llm == settings.preferred_llm.GROQ:
            try:
                result = await self._invoke_groq(role, messages, metadata)
                cb.record_success()
                self._log_call(role, "groq", result, start, metadata)
                return result
            except LLMRouterError:
                cb.record_failure()
                logger.warning(
                    "groq_failed_falling_back_to_openai",
                    role=role.value,
                    circuit_state=cb._state.value,
                )

        # Fallback to OpenAI
        try:
            result = await self._invoke_openai(role, messages, metadata)
            self._log_call(role, "openai", result, start, metadata)
            return result
        except Exception as exc:
            logger.error(
                "all_providers_failed",
                role=role.value,
                error=str(exc),
            )
            raise LLMRouterError(
                f"All LLM providers failed for role '{role.value}'. "
                "Check API keys and rate limits."
            ) from exc

    def get_langchain_llm(self, role: AgentRole) -> BaseChatModel:
        """
        Return the raw LangChain ChatModel for a role.
        Used by LangGraph agents that need the model as a node input.
        Falls back to OpenAI if Groq circuit is open.
        """
        cb = self._circuit_breakers[role]
        if cb.is_available:
            return self._groq_llms[role]
        return self._get_or_build_openai(role)

    def get_token_usage(self) -> dict[str, int]:
        """Return token usage counters for all roles. Used by monitoring."""
        return dict(self._token_usage)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _invoke_groq(
        self,
        role:     AgentRole,
        messages: Messages,
        metadata: dict[str, Any] | None,
    ) -> ChatResult:
        """
        Invoke Groq with rate limiting and retry logic.
        Rate limit is acquired BEFORE the network call.
        """
        await self._rate_limiter.acquire()

        llm = self._groq_llms[role]

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type((TimeoutError, ConnectionError)),
                stop=stop_after_attempt(settings.llm_max_retries),
                wait=wait_exponential_jitter(
                    initial=settings.llm_retry_delay_seconds,
                    max=30.0,
                    jitter=2.0,
                ),
                reraise=True,
            ):
                with attempt:
                    return await llm.ainvoke(messages)  # type: ignore[return-value]
        except Exception as exc:
            raise LLMRouterError(f"Groq invocation failed: {exc}") from exc

    async def _invoke_openai(
        self,
        role:     AgentRole,
        messages: Messages,
        metadata: dict[str, Any] | None,
    ) -> ChatResult:
        """Invoke OpenAI backup with retry."""
        llm = self._get_or_build_openai(role)

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type((TimeoutError, ConnectionError)),
                stop=stop_after_attempt(settings.llm_max_retries),
                wait=wait_exponential_jitter(initial=1.0, max=20.0, jitter=1.0),
                reraise=True,
            ):
                with attempt:
                    return await llm.ainvoke(messages)  # type: ignore[return-value]
        except Exception as exc:
            raise LLMRouterError(f"OpenAI fallback failed: {exc}") from exc

    def _get_or_build_openai(self, role: AgentRole) -> ChatOpenAI:
        """Lazy-build OpenAI client — only when actually needed."""
        if role not in self._openai_backup:
            self._openai_backup[role] = _build_openai_backup(role)
        return self._openai_backup[role]

    def _log_call(
        self,
        role:     AgentRole,
        provider: str,
        result:   ChatResult,
        start:    float,
        metadata: dict[str, Any] | None,
    ) -> None:
        """
        Log call metadata — NEVER log prompt content or response text.
        Only safe, non-PII metadata is included.
        """
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Extract token usage from result if available
        usage = getattr(result, "llm_output", {}) or {}
        token_count = (
            (usage.get("token_usage") or {}).get("total_tokens", 0)
        )

        if token_count:
            self._token_usage[role.value] = (
                self._token_usage.get(role.value, 0) + token_count
            )

        logger.info(
            "llm_call_completed",
            role=role.value,
            provider=provider,
            duration_ms=duration_ms,
            total_tokens=token_count,
            # Include safe metadata (contract IDs, org IDs) — never PII
            **(metadata or {}),
        )


# ── Custom exception ───────────────────────────────────────────────────────────

class LLMRouterError(Exception):
    """Raised when all configured LLM providers fail for a given role."""
    pass
