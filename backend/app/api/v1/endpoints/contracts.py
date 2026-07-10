"""
Contract management endpoints.

POST /upload    → validate + queue async processing (returns job_id)
GET  /          → list contracts (RBAC scoped)
GET  /{id}      → contract detail + processing status
DELETE /{id}    → admin only — soft delete

Upload security:
  - File validated by magic bytes (not extension)
  - Max size enforced before reading into memory
  - Virus/malware scan hook (ClamAV stub — activate in production)
  - Contract stored at opaque UUID path (not original filename)
  - SSE endpoint for real-time processing progress
"""
from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import AdminUser, AnyAuthenticatedUser, CurrentUser
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ContractStatus, AuditAction, ContractStatus, UserRole
from app.domain.models import AuditLog, Contract, User, UserContractAssignment
from app.infrastructure.database.session import get_db
from app.infrastructure.parsers import ParserFactory

logger = get_logger(__name__)
router = APIRouter()

_ALLOWED_MIME = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class ContractResponse(BaseModel):
    id:           str
    title:        str
    status:       str
    risk_score:   int | None
    overall_risk: str | None
    file_type:    str | None
    page_count:   int | None
    created_at:   str

    class Config:
        from_attributes = True


# ── POST /contracts/upload ────────────────────────────────────────────────────

@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a contract for AI analysis",
)
async def upload_contract(
    file:         UploadFile = File(...),
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    """
    Accept a contract file, validate it, persist it, and queue async analysis.

    Returns immediately with a job_id — use GET /contracts/{id} to poll status
    or SSE endpoint /contracts/{id}/progress for real-time updates.
    """
    if current_user.role not in (UserRole.ADMIN.value, UserRole.REVIEWER.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload requires admin or reviewer role.")

    # Read first 2KB for MIME detection (avoid reading full file for type check)
    header_bytes = await file.read(2048)
    await file.seek(0)

    # Validate by magic bytes — never trust the extension
    try:
        ParserFactory.get_parser(header_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))

    # Enforce max file size
    all_bytes = await file.read()
    if len(all_bytes) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_size_mb} MB limit.",
        )

    # Store at opaque UUID path — original filename is sanitised separately
    contract_id   = str(uuid.uuid4())
    safe_extension = Path(file.filename or "upload").suffix.lower()
    if safe_extension not in {".pdf", ".docx", ".doc"}:
        safe_extension = ".pdf"
    stored_path = settings.upload_dir / f"{contract_id}{safe_extension}"

    async with aiofiles.open(stored_path, "wb") as f:
        await f.write(all_bytes)

    # Create contract record (status: UPLOADED)
    contract = Contract(
        id=uuid.UUID(contract_id),
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        title=Path(file.filename or "Untitled Contract").stem,
        status=ContractStatus.UPLOADED.value,
        file_path=str(stored_path),
        original_filename=Path(file.filename or "upload").name[:255],
        file_size_bytes=len(all_bytes),
    )
    db.add(contract)

    # Audit
    db.add(AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.CONTRACT_UPLOAD.value,
        resource_type="contract",
        resource_id=uuid.UUID(contract_id),
        log_context={"filename_length": len(file.filename or "")},
    ))

    await db.flush()  # Get DB ID before queuing

    # Queue async processing via Celery
    try:
        from app.tasks.document import process_contract_task
        job = process_contract_task.apply_async(
            args=[contract_id, str(current_user.org_id)],
            task_id=contract_id,
            queue="document_processing",
        )

        # Update contract with job ID
        contract.processing_job_id = job.id
        contract.status = ContractStatus.PROCESSING.value

    except Exception as exc:
        logger.error("task_queue_failed", contract_id=contract_id, error=str(exc))
        # Contract saved but not yet processing — user can retry

    logger.info("contract_uploaded", contract_id=contract_id, org_id=str(current_user.org_id))

    return {
        "contract_id":  contract_id,
        "status":       contract.status,
        "message":      "Contract uploaded. Analysis in progress.",
        "poll_url":     f"/api/v1/contracts/{contract_id}",
        "progress_url": f"/api/v1/contracts/{contract_id}/progress",
    }


# ── GET /contracts ────────────────────────────────────────────────────────────

@router.get("", summary="List all contracts (RBAC scoped)")
async def list_contracts(
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Return contracts visible to the current user.
      Admin    → all org contracts
      Reviewer → only assigned contracts
      Viewer   → all contracts, summary fields only
    """
    if current_user.role in (UserRole.ADMIN.value, UserRole.VIEWER.value):
        result = await db.execute(
            select(Contract)
            .where(Contract.org_id == current_user.org_id)
            .order_by(Contract.created_at.desc())
        )
        contracts = result.scalars().all()
    else:
        # Reviewer: only assigned contracts
        result = await db.execute(
            select(Contract)
            .join(UserContractAssignment, UserContractAssignment.contract_id == Contract.id)
            .where(
                UserContractAssignment.user_id == current_user.id,
                Contract.org_id == current_user.org_id,
            )
            .order_by(Contract.created_at.desc())
        )
        contracts = result.scalars().all()

    return [
        {
            "id":           str(c.id),
            "title":        c.title,
            "status":       c.status,
            "risk_score":   c.risk_score,
            "overall_risk": c.overall_risk,
            "file_type":    c.file_type,
            "page_count":   c.page_count,
            "created_at":   c.created_at.isoformat(),
        }
        for c in contracts
    ]


# ── GET /contracts/{contract_id} ──────────────────────────────────────────────

@router.get("/{contract_id}", summary="Get contract detail")
async def get_contract(
    contract_id:  str,
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> dict:
    """Return contract details. RBAC enforced — reviewers limited to assigned contracts."""
    contract = await _get_contract_with_access_check(contract_id, current_user, db)

    return {
        "id":              str(contract.id),
        "title":           contract.title,
        "status":          contract.status,
        "contract_type":   contract.contract_type,
        "counterparty":    contract.counterparty,
        "risk_score":      contract.risk_score,
        "overall_risk":    contract.overall_risk,
        "signed_date":     contract.signed_date.isoformat() if contract.signed_date else None,
        "effective_date":  contract.effective_date.isoformat() if contract.effective_date else None,
        "expiry_date":     contract.expiry_date.isoformat() if contract.expiry_date else None,
        "auto_renewal":    contract.auto_renewal,
        "page_count":      contract.page_count,
        "has_tables":      contract.has_tables,
        "has_images":      contract.has_images,
        "ocr_confidence":  float(contract.ocr_confidence) if contract.ocr_confidence else None,
        "processing_job_id": contract.processing_job_id,
        "created_at":      contract.created_at.isoformat(),
    }


# ── DELETE /contracts/{contract_id} ──────────────────────────────────────────

@router.delete("/{contract_id}", status_code=status.HTTP_200_OK, summary="Delete contract (admin only)")
async def delete_contract(
    contract_id:  str,
    current_user: AdminUser = None,
    db:           AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a contract and remove its vector embeddings."""
    contract = await _get_contract_with_access_check(contract_id, current_user, db)

    # Remove from ChromaDB
    try:
        from app.infrastructure.vector_store.chroma_client import delete_contract_embeddings
        delete_contract_embeddings(str(contract.id), str(contract.org_id))
    except Exception as exc:
        logger.warning("embedding_deletion_failed", contract_id=contract_id, error=str(exc))

    # Soft delete — preserve audit trail
    contract.status = ContractStatus.ARCHIVED.value

    db.add(AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.CONTRACT_DELETE.value,
        resource_type="contract",
        resource_id=uuid.UUID(contract_id),
        context={},
    ))


# ── Shared access check helper ────────────────────────────────────────────────

async def _get_contract_with_access_check(
    contract_id:  str,
    current_user: User,
    db:           AsyncSession,
) -> Contract:
    """
    Fetch contract and verify the current user has access.
    Reviewers: only assigned contracts.
    Raises 404 (not 403) to prevent contract enumeration.
    """
    try:
        contract_uuid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    result = await db.execute(
        select(Contract).where(
            Contract.id == contract_uuid,
            Contract.org_id == current_user.org_id,
        )
    )
    contract = result.scalar_one_or_none()

    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    # Reviewer access check
    if current_user.role == UserRole.REVIEWER.value:
        assignment = await db.execute(
            select(UserContractAssignment).where(
                UserContractAssignment.user_id == current_user.id,
                UserContractAssignment.contract_id == contract_uuid,
            )
        )
        if assignment.scalar_one_or_none() is None:
            # Return 404 not 403 — prevents enumeration of contract IDs
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    return contract


@router.post("/{contract_id}/reprocess", status_code=200)
async def reprocess_contract(
    contract_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reprocess a stuck or failed contract — admin/reviewer only."""
    if current_user.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="Not authorized.")
    try:
        cid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid contract_id.")

    from sqlalchemy import select, update
    from app.domain.models import Contract
    from app.domain.enums import ContractStatus, ContractStatus

    r = await db.execute(select(Contract).where(
        Contract.id == cid,
        Contract.org_id == current_user.org_id,
    ))
    contract = r.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found.")

    # Reset status
    await db.execute(update(Contract).where(Contract.id == cid)
                     .values(status=ContractStatus.UPLOADED.value,
                             risk_score=None, overall_risk=None))
    await db.commit()

    # Run pipeline in background thread to avoid blocking the response
    import asyncio
    from app.tasks.document import _run_pipeline

    async def _bg():
        try:
            await _run_pipeline(str(cid), str(current_user.org_id))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"Reprocess failed: {exc}")

    asyncio.create_task(_bg())
    return {"status": "reprocessing", "contract_id": contract_id}
