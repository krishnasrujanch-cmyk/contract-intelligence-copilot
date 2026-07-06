"""Clauses endpoints — read-only clause retrieval with RBAC."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.middleware.auth import CurrentUser
from app.domain.enums import UserRole
from app.domain.models import Clause, Contract, UserContractAssignment
from app.infrastructure.database.session import get_db

router = APIRouter()


@router.get("/{contract_id}", summary="Get clauses for a contract")
async def get_clauses(
    contract_id:  str,
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return clauses for a contract. Viewer role receives summary only."""
    try:
        cid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Contract not found.")

    # Verify org scope
    contract_result = await db.execute(
        select(Contract).where(Contract.id == cid, Contract.org_id == current_user.org_id)
    )
    if not contract_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Contract not found.")

    # Reviewer: check assignment
    if current_user.role == UserRole.REVIEWER.value:
        assignment = await db.execute(
            select(UserContractAssignment).where(
                UserContractAssignment.user_id == current_user.id,
                UserContractAssignment.contract_id == cid,
            )
        )
        if not assignment.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Contract not found.")

    result = await db.execute(
        select(Clause)
        .where(Clause.contract_id == cid)
        .order_by(Clause.page_number.asc())
    )
    clauses = result.scalars().all()
    is_viewer = current_user.role == UserRole.VIEWER.value

    return [
        {
            "id":           str(c.id),
            "clause_type":  c.clause_type,
            "title":        c.title,
            "summary":      c.summary,
            "raw_text":     None if is_viewer else c.raw_text,  # RBAC data restriction
            "risk_score":   c.risk_score,
            "risk_level":   c.risk_level,
            "risk_reason":  None if is_viewer else c.risk_reason,
            "page_number":  c.page_number,
            "flagged":      c.flagged_for_review,
            "confidence":   float(c.extraction_confidence) if c.extraction_confidence else None,
        }
        for c in clauses
    ]
