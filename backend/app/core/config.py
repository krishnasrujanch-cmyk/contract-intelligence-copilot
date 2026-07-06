"""
Application configuration using Pydantic Settings v2.

Design:
  - CORS_ORIGINS stored as plain string in .env, parsed at runtime via property
  - No list fields sourced directly from env — avoids Pydantic v2 JSON parse issue
  - All secrets via environment only — never hardcoded
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING     = "staging"
    PRODUCTION  = "production"


class LLMProvider(str, Enum):
    GROQ   = "groq"
    OPENAI = "openai"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_parse_none_str="null",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_name:    str         = "Contract Intelligence Copilot"
    app_version: str         = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug:       bool        = False
    log_level:   str         = "INFO"
    secret_key:  str         = Field(..., min_length=32)

    # ── LLM — Groq ───────────────────────────────────────────────────────────
    groq_api_key:             str   = Field(..., description="Groq API key")
    groq_reasoner_model:      str   = "llama-3.3-70b-versatile"
    groq_judge_model:         str   = "llama-3.3-70b-versatile"
    groq_answerer_model:      str   = "llama-3.3-70b-versatile"
    groq_extractor_model:     str   = "llama-3.1-8b-instant"
    groq_safety_model:        str   = "llama-3.1-8b-instant"
    groq_max_tokens:          int   = Field(default=4096, ge=256, le=32768)
    groq_temperature:         float = Field(default=0.1, ge=0.0, le=2.0)
    groq_requests_per_minute: int   = Field(default=30, ge=1, le=300)

    # ── LLM — OpenAI ─────────────────────────────────────────────────────────
    openai_api_key:      str   = Field(..., description="OpenAI API key")
    openai_backup_model: str   = "gpt-4o-mini"
    openai_vision_model: str   = "gpt-4o"
    openai_max_tokens:   int   = Field(default=4096, ge=256, le=16384)
    openai_temperature:  float = Field(default=0.1, ge=0.0, le=2.0)

    # ── LLM Router ────────────────────────────────────────────────────────────
    preferred_llm:           LLMProvider = LLMProvider.GROQ
    llm_max_retries:         int         = Field(default=3, ge=1, le=10)
    llm_retry_delay_seconds: float       = Field(default=2.0, ge=0.5, le=30.0)

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model:     str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url:          str = Field(..., description="asyncpg connection URL")
    database_pool_size:    int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=5, le=120)

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url:       str = Field(..., description="Redis connection URL")
    redis_pool_size: int = Field(default=10, ge=1, le=50)

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chromadb_host:                 str = "localhost"
    chromadb_port:                 int = Field(default=8100, ge=1024, le=65535)
    chromadb_collection_clauses:   str = "clm_clauses"
    chromadb_collection_templates: str = "clm_templates"

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_private_key_path:            Path = Path("/app/keys/private.pem")
    jwt_public_key_path:             Path = Path("/app/keys/public.pem")
    jwt_algorithm:                   str  = "RS256"
    jwt_access_token_expire_minutes: int  = Field(default=15, ge=5, le=60)
    jwt_refresh_token_expire_days:   int  = Field(default=7, ge=1, le=30)
    jwt_issuer:                      str  = "contract-intelligence-copilot"

    # ── Security ──────────────────────────────────────────────────────────────
    bcrypt_rounds:         int = Field(default=12, ge=10, le=16)
    login_max_attempts:    int = Field(default=5, ge=3, le=20)
    login_lockout_minutes: int = Field(default=15, ge=5, le=60)
    max_upload_size_mb:    int = Field(default=50, ge=1, le=200)

    # KEY FIX: store CORS as plain string — parse to list via @property
    # Pydantic Settings v2 tries JSON.parse() on list[str] env vars and fails
    # on comma-separated values. Storing as str + parsing in property is robust.
    cors_origins_str: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        alias="CORS_ORIGINS",
    )

    # ── Business Rules ────────────────────────────────────────────────────────
    ocr_confidence_threshold:  int   = Field(default=75, ge=0, le=100)
    risk_escalation_threshold: int   = Field(default=80, ge=0, le=100)
    max_tool_iterations:       int   = Field(default=3, ge=1, le=10)
    judge_max_retries:         int   = Field(default=2, ge=1, le=5)
    chunk_max_tokens:          int   = Field(default=1500, ge=256, le=8192)
    chunk_overlap_tokens:      int   = Field(default=150, ge=0, le=512)

    # ── Celery ────────────────────────────────────────────────────────────────
    celery_broker_url:     str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── LangSmith ─────────────────────────────────────────────────────────────
    langchain_tracing_v2: bool = True
    langchain_api_key:    str  = ""
    langchain_project:    str  = "contract-intelligence-copilot"
    langchain_endpoint:   str  = "https://api.smith.langchain.com"

    # ── File Storage ──────────────────────────────────────────────────────────
    upload_dir:          Path = Path("/app/uploads")
    max_file_size_bytes: int  = Field(default=52_428_800, ge=1_048_576)

    # ── Demo ──────────────────────────────────────────────────────────────────
    demo_admin_email:       str = "admin@clm.demo"
    demo_admin_password:    str = "Admin@Demo2026!"
    demo_reviewer_email:    str = "reviewer@clm.demo"
    demo_reviewer_password: str = "Review@Demo2026!"
    demo_viewer_email:      str = "viewer@clm.demo"
    demo_viewer_password:   str = "View@Demo2026!"

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def cors_origins(self) -> list[str]:
        """Parse CORS origins from raw comma-separated string."""
        return [o.strip() for o in self.cors_origins_str.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def chromadb_url(self) -> str:
        return f"http://{self.chromadb_host}:{self.chromadb_port}"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got: {v!r}")
        return upper

    @model_validator(mode="after")
    def validate_jwt_keys_in_production(self) -> "Settings":
        if not self.is_development:
            for path, label in [
                (self.jwt_private_key_path, "private"),
                (self.jwt_public_key_path,  "public"),
            ]:
                if not path.exists():
                    raise ValueError(
                        f"JWT {label} key not found at {path}. "
                        "Run: ./backend/scripts/generate_keys.sh"
                    )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — env vars parsed exactly once per process."""
    return Settings()


settings: Final[Settings] = get_settings()
