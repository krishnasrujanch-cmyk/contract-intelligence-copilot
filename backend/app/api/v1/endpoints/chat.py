"""
RAG chatbot endpoint — role-scoped retrieval + LLM synthesis.
Uses RAGPipeline directly for consistent contract_id scoping and PII handling.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import CurrentUser
from app.core.logging import get_logger
from app.domain.enums import AuditAction, UserRole
from app.domain.models import AuditLog, UserContractAssignment
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    query:        str       = Field(..., min_length=1, max_length=2000)
    contract_id:  str | None = None
    contract_ids: list[str] = Field(default_factory=list)
    session_id:   str | None = None


class ChatResponse(BaseModel):
    answer:         str
    sources:        list[dict] = []
    citations:      list[dict] = []
    confidence:     float = 0.0
    safety_refused: bool = False


@router.post("", response_model=ChatResponse)
async def chat_query(
    body:         ChatRequest,
    current_user: CurrentUser,
    db:           AsyncSession = Depends(get_db),
) -> ChatResponse:

    # 1 — Safety guard
    modification_keywords = [
        "modify","change","edit","update","delete","remove",
        "rewrite","replace","amend","alter","revise","create",
    ]
    if any(kw in body.query.lower() for kw in modification_keywords):
        return ChatResponse(
            answer="I operate in read-only mode and cannot assist with modification requests.",
            safety_refused=True,
        )

    # 2 — Get assigned contracts from DB for reviewer + viewer RBAC
    result = await db.execute(
        select(UserContractAssignment.contract_id)
        .where(UserContractAssignment.user_id == current_user.id)
    )
    db_assigned_ids = [str(r[0]) for r in result.all()]

    # Viewer with no assignments blocked entirely
    if current_user.role == "viewer" and not db_assigned_ids:
        return ChatResponse(
            answer="No contracts have been assigned to you yet. Please contact your administrator.",
            safety_refused=False,
        )

    # Use DB assignments for RBAC — not what frontend sends (security)
    assigned_ids = db_assigned_ids or None

    # 3 — Resolve contract scope
    contract_id = body.contract_id or (body.contract_ids[0] if body.contract_ids else None)

    # 4 — RAG pipeline (fixed parser, original text, contract scoping)
    from app.agents.rag.pipeline import RAGPipeline
    from app.infrastructure.pii.presidio_engine import deanonymize_text

    # For viewer: always use DB assignments, ignore frontend contract_id
    # For admin/reviewer: use frontend contract_id if provided
    effective_contract_id = None if current_user.role == "viewer" else contract_id
    effective_assigned = db_assigned_ids if current_user.role in ("viewer", "reviewer") else None

    rag_result = RAGPipeline().answer(
        query=body.query,
        role=current_user.role,
        org_id=str(current_user.org_id),
        assigned_contract_ids=effective_assigned,
        contract_id=effective_contract_id,
        n_results=6,
    )

    answer = rag_result.get("answer", "No answer found.")

    # 5 — Deanonymize any remaining PII tokens
    try:
        answer = deanonymize_text(answer)
    except Exception:
        pass

    citations = rag_result.get("citations", [])

    # 6 — Audit log
    try:
        db.add(AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.id,
            user_role=current_user.role,
            action=AuditAction.CHATBOT_QUERY.value,
            resource_type="chat",
            log_context={"contract_id": contract_id, "result_count": len(citations)},
        ))
        await db.commit()
    except Exception:
        pass

    return ChatResponse(
        answer=answer,
        sources=citations,
        citations=citations,
        confidence=rag_result.get("confidence", 0.0),
    )
