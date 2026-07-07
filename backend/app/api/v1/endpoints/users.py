"""
User management endpoints (admin only).

POST /users          → create user
GET  /users          → list org users
PATCH /users/{id}    → update role or activate/deactivate
DELETE /users/{id}   → deactivate (never hard delete — audit trail)
POST /users/{id}/assign-contracts → assign contracts to reviewer
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import AdminUser
from app.core.config import settings
from app.core.security import hash_password
from app.domain.enums import AuditAction, UserRole
from app.domain.models import AuditLog, User, UserContractAssignment
from app.infrastructure.database.session import get_db

router = APIRouter()

import re
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{12,}$"
)


class CreateUserRequest(BaseModel):
    email:    EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    full_name:str = Field(..., min_length=2, max_length=255)
    role:     UserRole

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not _PASSWORD_PATTERN.match(v):
            raise ValueError(
                "Password must be ≥12 chars and contain uppercase, lowercase, digit, and special character."
            )
        return v


class UpdateUserRequest(BaseModel):
    role:      UserRole | None = None
    is_active: bool | None     = None


class AssignContractsRequest(BaseModel):
    contract_ids: list[str] = Field(..., min_length=1)


# ── POST /users ───────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create user (admin only)")
async def create_user(
    body:         CreateUserRequest,
    current_user: AdminUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    """Create a new user in the admin's organisation."""
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = User(
        org_id=current_user.org_id,
        email=str(body.email),
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role.value,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(user)

    db.add(AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.USER_CREATED.value,
        resource_type="user",
        context={"new_user_role": body.role.value},
    ))

    await db.flush()
    return {"id": str(user.id), "email": str(body.email), "role": body.role.value, "is_active": True}


# ── GET /users ────────────────────────────────────────────────────────────────

@router.get("", summary="List org users (admin only)")
async def list_users(
    current_user: AdminUser = None,
    db:           AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(User)
        .where(User.org_id == current_user.org_id)
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        {
            "id":         str(u.id),
            "full_name":  u.full_name,
            "role":       u.role,
            "is_active":  u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


# ── PATCH /users/{user_id} ────────────────────────────────────────────────────

@router.patch("/{user_id}", summary="Update user role or status (admin only)")
async def update_user(
    user_id:      str,
    body:         UpdateUserRequest,
    current_user: AdminUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    user = await _get_org_user(user_id, current_user.org_id, db)

    if body.role is not None:
        user.role = body.role.value
        db.add(AuditLog(
            org_id=current_user.org_id, user_id=current_user.id,
            user_role=current_user.role,
            action=AuditAction.USER_ROLE_CHANGED.value,
            resource_type="user", resource_id=user.id,
            context={"new_role": body.role.value},
        ))

    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            db.add(AuditLog(
                org_id=current_user.org_id, user_id=current_user.id,
                user_role=current_user.role,
                action=AuditAction.USER_DEACTIVATED.value,
                resource_type="user", resource_id=user.id, context={},
            ))

    return {"id": str(user.id), "role": user.role, "is_active": user.is_active}


# ── POST /users/{user_id}/assign-contracts ────────────────────────────────────

@router.post("/{user_id}/assign-contracts", summary="Assign contracts to reviewer")
async def assign_contracts(
    user_id:      str,
    body:         AssignContractsRequest,
    current_user: AdminUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    """Assign contracts to a reviewer. Creates assignment records."""
    reviewer = await _get_org_user(user_id, current_user.org_id, db)
    if reviewer.role != UserRole.REVIEWER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contract assignment is only valid for reviewer role.",
        )

    assigned = []
    for contract_id_str in body.contract_ids:
        try:
            contract_uuid = uuid.UUID(contract_id_str)
        except ValueError:
            continue

        # Upsert — safe to call multiple times
        existing = await db.execute(
            select(UserContractAssignment).where(
                UserContractAssignment.user_id == reviewer.id,
                UserContractAssignment.contract_id == contract_uuid,
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(UserContractAssignment(
                user_id=reviewer.id,
                contract_id=contract_uuid,
                assigned_by=current_user.id,
            ))
            assigned.append(contract_id_str)
            db.add(AuditLog(
                org_id=current_user.org_id, user_id=current_user.id,
                user_role=current_user.role,
                action=AuditAction.CONTRACT_ASSIGNED.value,
                resource_type="contract", resource_id=contract_uuid,
                context={"assigned_to_user_id": str(reviewer.id)},
            ))

    return {"assigned_count": len(assigned), "assigned_contract_ids": assigned}


async def _get_org_user(user_id: str, org_id: uuid.UUID, db: AsyncSession) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    result = await db.execute(select(User).where(User.id == uid, User.org_id == org_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user
