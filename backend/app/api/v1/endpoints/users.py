"""
User management endpoints — admin only.
Includes contract assignment for reviewer role.
"""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.middleware.auth import CurrentUser
from app.core.logging import get_logger
from app.domain.models import User, UserContractAssignment, Contract
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


class UserResponse(BaseModel):
    id: str; email: str; full_name: str; role: str
    is_active: bool; last_login: str | None; created_at: str

    @classmethod
    def from_orm(cls, u: User) -> "UserResponse":
        return cls(id=str(u.id), email=u.email, full_name=u.full_name,
                   role=u.role, is_active=u.is_active,
                   last_login=u.last_login.isoformat() if u.last_login else None,
                   created_at=u.created_at.isoformat())


class AssignContractsRequest(BaseModel):
    contract_ids: list[str]


class AssignmentResponse(BaseModel):
    user_id: str
    contract_id: str


@router.get("", response_model=list[UserResponse], status_code=200)
async def list_users(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    result = await db.execute(
        select(User).where(User.org_id == current_user.org_id, User.is_active.is_(True))
        .order_by(User.role, User.full_name)
    )
    return [UserResponse.from_orm(u) for u in result.scalars().all()]


@router.get("/assignments", response_model=list[AssignmentResponse], status_code=200)
async def list_assignments(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    result = await db.execute(
        select(UserContractAssignment)
        .join(User, User.id == UserContractAssignment.user_id)
        .where(User.org_id == current_user.org_id)
    )
    return [AssignmentResponse(user_id=str(a.user_id), contract_id=str(a.contract_id))
            for a in result.scalars().all()]


@router.post("/{user_id}/assignments", status_code=200)
async def assign_contracts(user_id: str, body: AssignContractsRequest,
                           current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    try:
        target_uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id.")

    result = await db.execute(
        select(User).where(User.id == target_uid, User.org_id == current_user.org_id)
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    if target_user.role not in ("reviewer", "viewer"):
        raise HTTPException(status_code=400, detail=f"Assignment only for reviewer and viewer roles. Got: {target_user.role}")

    valid_ids: list[uuid.UUID] = []
    for cid_str in body.contract_ids:
        try:
            cid = uuid.UUID(cid_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid contract_id: {cid_str}")
        cr = await db.execute(select(Contract).where(Contract.id == cid, Contract.org_id == current_user.org_id))
        if not cr.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Contract {cid_str} not found.")
        valid_ids.append(cid)

    await db.execute(delete(UserContractAssignment).where(UserContractAssignment.user_id == target_uid))
    for cid in valid_ids:
        db.add(UserContractAssignment(user_id=target_uid, contract_id=cid, assigned_by=current_user.id))
    await db.commit()

    logger.info("contracts_assigned", admin_id=str(current_user.id),
                reviewer_id=user_id, count=len(valid_ids))
    return {"user_id": user_id, "assigned": len(valid_ids),
            "contract_ids": [str(c) for c in valid_ids]}


@router.delete("/{user_id}/assignments/{contract_id}", status_code=200)
async def remove_assignment(user_id: str, contract_id: str,
                            current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    try:
        uid = uuid.UUID(user_id); cid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID.")
    await db.execute(delete(UserContractAssignment).where(
        UserContractAssignment.user_id == uid,
        UserContractAssignment.contract_id == cid,
    ))
    await db.commit()
    return {"status": "removed", "user_id": user_id, "contract_id": contract_id}
