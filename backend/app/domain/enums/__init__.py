"""
Domain enumerations for the Contract Intelligence Copilot.
All enums are string-based for JSON serialization compatibility.
"""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """RBAC roles with hierarchical access."""
    ADMIN = "admin"         # Full access: all contracts, user management, audit log
    REVIEWER = "reviewer"   # Assigned contracts: full clause text, risk details
    VIEWER = "viewer"       # All contracts: summary and risk scores only


class ContractStatus(str, Enum):
    """Processing pipeline stages."""
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    FAILED = "failed"
    ARCHIVED = "archived"


class FileType(str, Enum):
    """Supported document formats."""
    PDF = "pdf"
    SCANNED_PDF = "scanned_pdf"
    DOCX = "docx"
    DOC = "doc"


class ClauseType(str, Enum):
    """Legal clause taxonomy — 15 primary types."""
    PAYMENT = "payment"
    TERMINATION = "termination"
    LIABILITY = "liability"
    INDEMNIFICATION = "indemnification"
    CONFIDENTIALITY = "confidentiality"
    IP_OWNERSHIP = "ip_ownership"
    AUTO_RENEWAL = "auto_renewal"
    GOVERNING_LAW = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    FORCE_MAJEURE = "force_majeure"
    SLA = "sla"
    WARRANTIES = "warranties"
    ASSIGNMENT = "assignment"
    NON_COMPETE = "non_compete"
    DATA_PROTECTION = "data_protection"
    OTHER = "other"


class RiskLevel(str, Enum):
    """Risk severity bands mapped to score ranges."""
    LOW = "low"           # 0–39
    MEDIUM = "medium"     # 40–69
    HIGH = "high"         # 70–79
    CRITICAL = "critical" # 80–100 → mandatory human escalation

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        if score >= 80:
            return cls.CRITICAL
        if score >= 70:
            return cls.HIGH
        if score >= 40:
            return cls.MEDIUM
        return cls.LOW


class ObligationStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    WAIVED = "waived"


class ObligationParty(str, Enum):
    US = "us"
    COUNTERPARTY = "counterparty"
    BOTH = "both"


class AlertType(str, Enum):
    RENEWAL = "renewal"
    PAYMENT = "payment"
    DEADLINE = "deadline"
    RISK = "risk"
    EXPIRY = "expiry"


class AlertStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    SNOOZED = "snoozed"


class AlertChannel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"


class AuditAction(str, Enum):
    """All auditable actions — no PII in values."""
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    CONTRACT_UPLOAD = "CONTRACT_UPLOAD"
    CONTRACT_VIEW = "CONTRACT_VIEW"
    CONTRACT_DELETE = "CONTRACT_DELETE"
    CLAUSE_VIEW = "CLAUSE_VIEW"
    CLAUSE_FLAGGED = "CLAUSE_FLAGGED"
    CHATBOT_QUERY = "CHATBOT_QUERY"
    FEEDBACK_SUBMITTED = "FEEDBACK_SUBMITTED"
    USER_CREATED = "USER_CREATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    CONTRACT_ASSIGNED = "CONTRACT_ASSIGNED"
    SAFETY_REFUSAL = "SAFETY_REFUSAL"
    ESCALATION_TRIGGERED = "ESCALATION_TRIGGERED"


class ChunkLevel(int, Enum):
    """Hierarchical chunk level in the legal document structure."""
    DOCUMENT = 0    # Full document summary — viewers can access
    ARTICLE = 1     # Article/section group
    CLAUSE = 2      # Primary retrieval unit — reviewers and admins
    SUB_CLAUSE = 3  # Sub-clause for precise queries


class JudgeVerdict(str, Enum):
    """LLM-as-judge decision."""
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"  # Judge cannot resolve — needs human


class ProcessingStep(str, Enum):
    """Document processing pipeline steps for SSE progress reporting."""
    INTAKE = "intake"
    TYPE_DETECTION = "type_detection"
    TEXT_EXTRACTION = "text_extraction"
    VISION_PROCESSING = "vision_processing"
    PII_MASKING = "pii_masking"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    EXTRACTION_AGENT = "extraction_agent"
    RISK_AGENT = "risk_agent"
    OBLIGATION_AGENT = "obligation_agent"
    COMPARE_AGENT = "compare_agent"
    JUDGE_VALIDATION = "judge_validation"
    FINALIZATION = "finalization"
    COMPLETE = "complete"
    FAILED = "failed"
