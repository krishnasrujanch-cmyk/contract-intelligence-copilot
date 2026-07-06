"""
SQLAlchemy ORM models — Contract Intelligence Copilot.

Design decisions:
  - UUID PKs everywhere (prevents enumeration attacks)
  - foreign_keys= specified on ALL relationships to eliminate ambiguity
  - 'metadata' column renamed to 'contract_metadata' (reserved by DeclarativeBase)
  - Append-only AuditLog (no UPDATE/DELETE ever issued against this table)
  - TimestampMixin via __abstract__ base avoids repeated column definitions
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime,
    ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.domain.enums import (
    ChunkLevel, ContractStatus, JudgeVerdict,
    ObligationParty, ObligationStatus, RiskLevel,
)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── 1. Organizations ──────────────────────────────────────────────────────────

class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id:              Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:            Mapped[str]       = mapped_column(String(255), nullable=False)
    slug:            Mapped[str]       = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan:            Mapped[str]       = mapped_column(String(50), default="starter", nullable=False)
    risk_thresholds: Mapped[dict]      = mapped_column(JSONB, default=dict, nullable=False)
    llm_provider:    Mapped[str]       = mapped_column(String(20), default="groq", nullable=False)
    org_settings:    Mapped[dict]      = mapped_column("settings", JSONB, default=dict, nullable=False)
    is_active:       Mapped[bool]      = mapped_column(Boolean, default=True, nullable=False)

    users:     Mapped[list["User"]]     = relationship("User", back_populates="organization",
                                            foreign_keys="User.org_id")
    contracts: Mapped[list["Contract"]] = relationship("Contract", back_populates="organization",
                                            foreign_keys="Contract.org_id")

    __table_args__ = (
        CheckConstraint("length(slug) >= 2", name="ck_organizations_slug_length"),
    )


# ── 2. Users ──────────────────────────────────────────────────────────────────

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id:             Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id:         Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email:          Mapped[str]               = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash:  Mapped[str]               = mapped_column(String(60), nullable=False)
    full_name:      Mapped[str]               = mapped_column(String(255), nullable=False)
    role:           Mapped[str]               = mapped_column(String(20), nullable=False)
    is_active:      Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    login_attempts: Mapped[int]               = mapped_column(Integer, default=0, nullable=False)
    locked_until:   Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    last_login:     Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    created_by:     Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="users", foreign_keys=[org_id]
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user",
        foreign_keys="RefreshToken.user_id",
        cascade="all, delete-orphan"
    )
    # Contracts this user uploaded
    uploaded_contracts: Mapped[list["Contract"]] = relationship(
        "Contract", back_populates="uploaded_by_user",
        foreign_keys="Contract.uploaded_by"
    )
    # Reviewer contract assignments
    contract_assignments: Mapped[list["UserContractAssignment"]] = relationship(
        "UserContractAssignment", back_populates="user",
        foreign_keys="UserContractAssignment.user_id",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin','reviewer','viewer')", name="ck_users_role"),
        Index("ix_users_org_id_role", "org_id", "role"),
    )


# ── 3. Refresh Tokens ─────────────────────────────────────────────────────────

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id:          Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:     Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash:  Mapped[str]               = mapped_column(String(64), unique=True, nullable=False)
    jti:         Mapped[str]               = mapped_column(String(36), nullable=False, index=True)
    issued_at:   Mapped[datetime]          = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at:  Mapped[datetime]          = mapped_column(DateTime(timezone=True), nullable=False)
    revoked:     Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    revoked_at:  Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    ip_hash:     Mapped[Optional[str]]     = mapped_column(String(64))
    device_hint: Mapped[Optional[str]]     = mapped_column(String(100))

    user: Mapped[User] = relationship(
        "User", back_populates="refresh_tokens", foreign_keys=[user_id]
    )

    __table_args__ = (
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked"),
    )


# ── 4. Contracts ──────────────────────────────────────────────────────────────

class Contract(TimestampMixin, Base):
    __tablename__ = "contracts"

    id:                Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id:            Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    uploaded_by:       Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    title:             Mapped[str]               = mapped_column(String(500), nullable=False)
    contract_type:     Mapped[Optional[str]]     = mapped_column(String(100))
    counterparty:      Mapped[Optional[str]]     = mapped_column(String(500))
    status:            Mapped[str]               = mapped_column(String(20), default=ContractStatus.UPLOADED.value, nullable=False)
    file_path:         Mapped[str]               = mapped_column(String(1024), nullable=False)
    file_type:         Mapped[Optional[str]]     = mapped_column(String(20))
    original_filename: Mapped[str]               = mapped_column(String(255), nullable=False)
    file_size_bytes:   Mapped[Optional[int]]     = mapped_column(BigInteger)
    page_count:        Mapped[Optional[int]]     = mapped_column(Integer)
    has_images:        Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    has_tables:        Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    ocr_confidence:    Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    language:          Mapped[str]               = mapped_column(String(10), default="en", nullable=False)
    signed_date:       Mapped[Optional[date]]    = mapped_column(Date)
    effective_date:    Mapped[Optional[date]]    = mapped_column(Date)
    expiry_date:       Mapped[Optional[date]]    = mapped_column(Date)
    auto_renewal:      Mapped[Optional[bool]]    = mapped_column(Boolean)
    renewal_notice_days: Mapped[Optional[int]]   = mapped_column(Integer)
    overall_risk:      Mapped[Optional[str]]     = mapped_column(String(20))
    risk_score:        Mapped[Optional[int]]     = mapped_column(Integer)
    # Renamed from 'metadata' — reserved word in SQLAlchemy DeclarativeBase
    contract_metadata: Mapped[dict]              = mapped_column("metadata", JSONB, default=dict, nullable=False)
    parent_id:         Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="SET NULL"))
    processing_job_id: Mapped[Optional[str]]     = mapped_column(String(36))
    error_message:     Mapped[Optional[str]]     = mapped_column(Text)

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="contracts", foreign_keys=[org_id]
    )
    uploaded_by_user: Mapped[User] = relationship(
        "User", back_populates="uploaded_contracts", foreign_keys=[uploaded_by]
    )
    clauses: Mapped[list["Clause"]] = relationship(
        "Clause", back_populates="contract",
        foreign_keys="Clause.contract_id",
        cascade="all, delete-orphan"
    )
    obligations: Mapped[list["Obligation"]] = relationship(
        "Obligation", back_populates="contract",
        foreign_keys="Obligation.contract_id",
        cascade="all, delete-orphan"
    )
    user_assignments: Mapped[list["UserContractAssignment"]] = relationship(
        "UserContractAssignment", back_populates="contract",
        foreign_keys="UserContractAssignment.contract_id",
        cascade="all, delete-orphan"
    )
    child_contracts: Mapped[list["Contract"]] = relationship(
        "Contract", foreign_keys=[parent_id]
    )

    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_contracts_risk_score"),
        Index("ix_contracts_org_status", "org_id", "status"),
        Index("ix_contracts_org_expiry", "org_id", "expiry_date"),
        Index("ix_contracts_org_risk",   "org_id", "risk_score"),
    )


# ── 5. Clauses ────────────────────────────────────────────────────────────────

class Clause(TimestampMixin, Base):
    __tablename__ = "clauses"

    id:                    Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id:           Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    org_id:                Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), nullable=False)
    clause_type:           Mapped[str]               = mapped_column(String(50), nullable=False)
    title:                 Mapped[Optional[str]]     = mapped_column(String(500))
    raw_text:              Mapped[str]               = mapped_column(Text, nullable=False)
    summary:               Mapped[Optional[str]]     = mapped_column(Text)
    page_number:           Mapped[Optional[int]]     = mapped_column(Integer)
    page_end:              Mapped[Optional[int]]     = mapped_column(Integer)
    chunk_level:           Mapped[int]               = mapped_column(Integer, default=ChunkLevel.CLAUSE.value, nullable=False)
    risk_level:            Mapped[Optional[str]]     = mapped_column(String(20))
    risk_score:            Mapped[Optional[int]]     = mapped_column(Integer)
    risk_reason:           Mapped[Optional[str]]     = mapped_column(Text)
    suggested_revision:    Mapped[Optional[str]]     = mapped_column(Text)
    is_standard:           Mapped[Optional[bool]]    = mapped_column(Boolean)
    deviation_notes:       Mapped[Optional[str]]     = mapped_column(Text)
    extraction_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    judge_verdict:         Mapped[Optional[str]]     = mapped_column(String(20))
    extracted_data:        Mapped[dict]              = mapped_column(JSONB, default=dict, nullable=False)
    vector_id:             Mapped[Optional[str]]     = mapped_column(String(36))
    flagged_for_review:    Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    review_notes:          Mapped[Optional[str]]     = mapped_column(Text)

    contract: Mapped[Contract] = relationship(
        "Contract", back_populates="clauses", foreign_keys=[contract_id]
    )
    obligations: Mapped[list["Obligation"]] = relationship(
        "Obligation", back_populates="clause",
        foreign_keys="Obligation.clause_id"
    )

    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_clauses_risk_score"),
        Index("ix_clauses_contract_type", "contract_id", "clause_type"),
        Index("ix_clauses_org_risk",      "org_id", "risk_score"),
        Index("ix_clauses_org_flagged",   "org_id", "flagged_for_review"),
    )


# ── 6. Obligations ────────────────────────────────────────────────────────────

class Obligation(TimestampMixin, Base):
    __tablename__ = "obligations"

    id:           Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id:  Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    clause_id:    Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="SET NULL"))
    org_id:       Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), nullable=False)
    title:        Mapped[str]               = mapped_column(String(500), nullable=False)
    description:  Mapped[Optional[str]]     = mapped_column(Text)
    party:        Mapped[str]               = mapped_column(String(20), default=ObligationParty.BOTH.value, nullable=False)
    due_date:     Mapped[Optional[date]]    = mapped_column(Date, index=True)
    recurrence:   Mapped[Optional[str]]     = mapped_column(String(20))
    amount:       Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    currency:     Mapped[Optional[str]]     = mapped_column(String(3))
    status:       Mapped[str]               = mapped_column(String(20), default=ObligationStatus.PENDING.value, nullable=False)
    assigned_to:  Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))

    contract: Mapped[Contract]        = relationship("Contract", back_populates="obligations", foreign_keys=[contract_id])
    clause:   Mapped[Optional[Clause]]= relationship("Clause",   back_populates="obligations", foreign_keys=[clause_id])
    alerts:   Mapped[list["Alert"]]   = relationship("Alert", back_populates="obligation",
                                           foreign_keys="Alert.obligation_id",
                                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_obligations_org_due",    "org_id", "due_date"),
        Index("ix_obligations_org_status", "org_id", "status"),
    )


# ── 7. Alerts ─────────────────────────────────────────────────────────────────

class Alert(Base):
    __tablename__ = "alerts"

    id:            Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id:        Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), nullable=False)
    obligation_id: Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("obligations.id", ondelete="CASCADE"))
    contract_id:   Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    alert_type:    Mapped[str]               = mapped_column(String(20), nullable=False)
    severity:      Mapped[str]               = mapped_column(String(20), nullable=False)
    message:       Mapped[str]               = mapped_column(Text, nullable=False)
    trigger_date:  Mapped[date]              = mapped_column(Date, nullable=False)
    sent_at:       Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    status:        Mapped[str]               = mapped_column(String(20), default="pending", nullable=False)
    channels:      Mapped[list]              = mapped_column(JSONB, default=list, nullable=False)
    created_at:    Mapped[datetime]          = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    obligation: Mapped[Optional[Obligation]] = relationship(
        "Obligation", back_populates="alerts", foreign_keys=[obligation_id]
    )

    __table_args__ = (
        Index("ix_alerts_org_trigger", "org_id", "trigger_date"),
        Index("ix_alerts_status",      "status"),
    )


# ── 8. User-Contract Assignments ──────────────────────────────────────────────

class UserContractAssignment(Base):
    __tablename__ = "user_contract_assignments"

    id:          Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    # assigned_by is a second FK to users — SQLAlchemy needs explicit foreign_keys
    # on every relationship to avoid AmbiguousForeignKeysError
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    assigned_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # user_id → User (reviewer being assigned)
    user: Mapped[User] = relationship(
        "User", back_populates="contract_assignments", foreign_keys=[user_id]
    )
    # contract_id → Contract
    contract: Mapped[Contract] = relationship(
        "Contract", back_populates="user_assignments", foreign_keys=[contract_id]
    )
    # assigned_by → User (admin who did the assigning) — no back_populates needed
    assigner: Mapped[User] = relationship(
        "User", foreign_keys=[assigned_by]
    )

    __table_args__ = (
        UniqueConstraint("user_id", "contract_id", name="uq_user_contract"),
        Index("ix_assignments_user",     "user_id"),
        Index("ix_assignments_contract", "contract_id"),
    )


# ── 9. Feedback ───────────────────────────────────────────────────────────────

class Feedback(Base):
    __tablename__ = "feedback"

    id:              Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id:          Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    clause_id:       Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), nullable=False)
    is_positive:     Mapped[bool]           = mapped_column(Boolean, nullable=False)
    feedback_target: Mapped[str]            = mapped_column(String(50), nullable=False)
    original_value:  Mapped[Optional[str]]  = mapped_column(String(200))
    suggested_value: Mapped[Optional[str]]  = mapped_column(String(200))
    notes:           Mapped[Optional[str]]  = mapped_column(Text)
    created_at:      Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_feedback_org",    "org_id"),
        Index("ix_feedback_clause", "clause_id"),
    )


# ── 10. Audit Log (append-only — no UPDATE or DELETE) ────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_log"

    id:            Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id:        Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id:       Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), nullable=False)
    user_role:     Mapped[str]             = mapped_column(String(20), nullable=False)
    action:        Mapped[str]             = mapped_column(String(50), nullable=False)
    resource_type: Mapped[Optional[str]]   = mapped_column(String(50))
    resource_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ip_hash:       Mapped[Optional[str]]   = mapped_column(String(64))
    trace_id:      Mapped[Optional[str]]   = mapped_column(String(36))
    duration_ms:   Mapped[Optional[int]]   = mapped_column(Integer)
    # Renamed from 'context' — avoids any future reserved word conflicts
    log_context:   Mapped[dict]            = mapped_column("context", JSONB, default=dict, nullable=False)
    created_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_audit_org_action", "org_id", "action"),
        Index("ix_audit_user",       "user_id"),
        Index("ix_audit_resource",   "resource_type", "resource_id"),
    )
