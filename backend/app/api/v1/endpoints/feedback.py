"""Feedback endpoint — thumbs up/down on risk scores for adaptive learning."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.middleware.auth import CurrentUser
from app.domain.enums import AuditAction, UserRole
from app.domain.models import AuditLog, Clause, Feedback
from app.infrastructure.database.session import get_db

router = APIRouter()


class FeedbackRequest(BaseModel):
    clause_id:       str
    is_positive:     bool
    feedback_target: str = Field(default="risk_score", pattern="^(risk_score|clause_type|summary|missing_clause)$")
    suggested_value: str | None = None
    notes:           str | None = Field(default=None, max_length=500)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Submit feedback on a clause")
async def submit_feedback(
    body:         FeedbackRequest,
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    """Viewer role cannot submit feedback."""
    if current_user.role == UserRole.VIEWER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot submit feedback.")

    try:
        clause_uuid = uuid.UUID(body.clause_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clause not found.")

    clause_result = await db.execute(
        select(Clause).where(Clause.id == clause_uuid, Clause.org_id == current_user.org_id)
    )
    clause = clause_result.scalar_one_or_none()
    if not clause:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clause not found.")

    feedback = Feedback(
        org_id=current_user.org_id,
        user_id=current_user.id,
        clause_id=clause_uuid,
        is_positive=body.is_positive,
        feedback_target=body.feedback_target,
        suggested_value=body.suggested_value,
        notes=body.notes,
    )
    db.add(feedback)
    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.FEEDBACK_SUBMITTED.value,
        resource_type="clause", resource_id=clause_uuid, log_context={},
    ))
    return {"status": "recorded"}
