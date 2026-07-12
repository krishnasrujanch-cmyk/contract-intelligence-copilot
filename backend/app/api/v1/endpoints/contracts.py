"""
Contract management endpoints.
Reprocess runs synchronously — no silent background failures.
"""
from __future__ import annotations

import uuid
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import CurrentUser
from app.core.logging import get_logger
from app.domain.enums import ContractStatus
from app.domain.models import AuditLog, Contract, Clause, UserContractAssignment
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=200)
async def upload_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = None,
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="Not authorized.")

    allowed = {".pdf", ".docx", ".doc", ".txt"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"File type {suffix} not supported.")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 50MB.")

    import os
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/workspaces/contract-intelligence-copilot/backend/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    cid = uuid.uuid4()
    filename = file.filename or f"{cid}{suffix}"
    title = Path(filename).stem
    dest = upload_dir / f"{cid}{suffix}"
    dest.write_bytes(content)

    contract = Contract(
        id=cid,
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        title=title,
        original_filename=filename,
        file_path=str(dest),
        file_type=suffix.lstrip("."),
        
        status=ContractStatus.UPLOADED.value,
    )
    db.add(contract)
    db.add(AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action="contract_upload",
        resource_type="contract",
        resource_id=cid,
        log_context={"filename": filename, "size": len(content)},
    ))
    await db.commit()

    # Background processing
    background_tasks.add_task(_process_contract, str(cid), str(current_user.org_id))

    return {"contract_id": str(cid), "status": "uploaded", "message": f"Contract '{title}' uploaded successfully."}


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("", status_code=200)
async def list_contracts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == "admin":
        result = await db.execute(
            select(Contract).where(Contract.org_id == current_user.org_id)
            .order_by(Contract.created_at.desc())
        )
    elif current_user.role == "reviewer":
        assigned = await db.execute(
            select(UserContractAssignment.contract_id)
            .where(UserContractAssignment.user_id == current_user.id)
        )
        ids = [r[0] for r in assigned.all()]
        result = await db.execute(
            select(Contract).where(
                Contract.org_id == current_user.org_id,
                Contract.id.in_(ids) if ids else Contract.id.is_(None),
            ).order_by(Contract.created_at.desc())
        )
    else:
        # Viewer — only assigned contracts (same as reviewer)
        assigned = await db.execute(
            select(UserContractAssignment.contract_id)
            .where(UserContractAssignment.user_id == current_user.id)
        )
        ids = [r[0] for r in assigned.all()]
        if not ids:
            return []  # No assignments = no contracts visible
        result = await db.execute(
            select(Contract).where(
                Contract.org_id == current_user.org_id,
                Contract.id.in_(ids),
            ).order_by(Contract.created_at.desc())
        )

    contracts = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
            "overall_risk": c.overall_risk,
            "risk_score": c.risk_score,
            "page_count": c.page_count,
            "file_type": c.file_type,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in contracts
    ]


# ── Get single ─────────────────────────────────────────────────────────────────

@router.get("/{contract_id}", status_code=200)
async def get_contract(
    contract_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    try:
        cid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid contract_id.")

    result = await db.execute(
        select(Contract).where(Contract.id == cid, Contract.org_id == current_user.org_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Contract not found.")

    return {
        "id": str(c.id),
        "title": c.title,
        "status": c.status,
        "overall_risk": c.overall_risk,
        "risk_score": c.risk_score,
        "page_count": c.page_count,
        "file_type": c.file_type,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ── Reprocess — SYNCHRONOUS, no silent failures ────────────────────────────────

@router.post("/{contract_id}/reprocess", status_code=200)
async def reprocess_contract(
    contract_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="Not authorized.")
    try:
        cid = uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid contract_id.")

    result = await db.execute(
        select(Contract).where(Contract.id == cid, Contract.org_id == current_user.org_id)
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found.")

    # Reset status
    await db.execute(
        update(Contract).where(Contract.id == cid)
        .values(status=ContractStatus.UPLOADED.value, risk_score=None, overall_risk=None)
    )
    await db.execute(delete(Clause).where(Clause.contract_id == cid))
    await db.commit()

    # Run synchronously — no background task, no silent failure
    try:
        clauses_saved, avg, overall = await _extract_and_save(
            cid, current_user.org_id, contract
        )
        return {
            "status": "analyzed",
            "contract_id": contract_id,
            "clauses": clauses_saved,
            "avg_risk": avg,
            "overall_risk": overall,
        }
    except Exception as exc:
        logger.error("reprocess_failed", contract_id=contract_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reprocess failed: {exc}")


# ── Shared extraction logic ────────────────────────────────────────────────────

async def _extract_and_save(
    cid: uuid.UUID,
    org_id: uuid.UUID,
    contract: Contract,
) -> tuple[int, int, str]:
    """Parse → mask → LLM extract → save clauses → index ChromaDB. Returns (count, avg, overall)."""
    from app.infrastructure.parsers import ParserFactory
    from app.infrastructure.pii.presidio_engine import anonymize_text, initialise_pii_engine
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.infrastructure.llm.router import AgentRole, LLMRouter
    from app.infrastructure.llm.json_parser import parse_clauses
    from app.agents.rag.pipeline import RAGPipeline
    from app.infrastructure.database.session import AsyncSessionLocal

    await initialise_pii_engine()

    raw_bytes = Path(contract.file_path).read_bytes()
    parser = ParserFactory.get_parser(raw_bytes)
    parsed = parser.parse(raw_bytes, contract.original_filename)
    logger.info("contract_parsed", pages=parsed.page_count, chars=len(parsed.text))

    # Mask for LLM extraction only
    masked, _ = anonymize_text(parsed.text, str(cid))

    # LLM extraction
    router = LLMRouter.get_instance()
    types = (
        "confidentiality, termination, ip_ownership, liability, indemnification, "
        "payment, auto_renewal, governing_law, force_majeure, financial_covenant, "
        "event_of_default, security, data_protection, sla, penalty, general"
    )
    prompt = (
        "Extract ALL clauses from this contract. Clause types: " + types + ". "
        "Return ONLY valid JSON: {\"clauses\": [{\"clause_type\": \"...\", "
        "\"title\": \"...\", \"raw_text\": \"...\", \"summary\": \"...\", "
        "\"risk_score\": 50, \"risk_level\": \"medium\", "
        "\"risk_reason\": \"...\", \"confidence\": 0.9}]}"
    )

    result = await router.invoke(
        AgentRole.EXTRACTOR,
        [SystemMessage(content=prompt), HumanMessage(content=masked)],
    )
    raw = result.content if hasattr(result, "content") else str(result)
    clauses_data = parse_clauses(raw)
    logger.info("clauses_extracted", count=len(clauses_data))

    # Save to DB + index ChromaDB with original (unmasked) text
    async with AsyncSessionLocal() as db:
        for c in clauses_data:
            s = c.get("risk_score")
            if isinstance(s, str):
                try: s = int(s)
                except: s = None
            db.add(Clause(
                contract_id=cid, org_id=org_id,
                clause_type=c.get("clause_type", "general"),
                title=c.get("title", "")[:500],
                raw_text=c.get("raw_text", ""),
                summary=c.get("summary", ""),
                risk_score=s, risk_level=c.get("risk_level"),
                risk_reason=c.get("risk_reason"),
                extraction_confidence=c.get("confidence"),
                flagged_for_review=(s or 0) >= 80,
                extracted_data={},
            ))

        scores = [c.get("risk_score") for c in clauses_data if isinstance(c.get("risk_score"), int)]
        avg = int(sum(scores) / len(scores)) if scores else 0
        mx = max(scores) if scores else 0
        overall = "critical" if mx >= 80 else "high" if mx >= 70 else "medium" if mx >= 40 else "low"

        await db.execute(
            update(Contract).where(Contract.id == cid).values(
                status=ContractStatus.ANALYZED.value,
                risk_score=avg, overall_risk=overall,
                page_count=parsed.page_count,
                file_type=parsed.file_type,
            )
        )
        await db.commit()

    # Index original text into ChromaDB (no PII masking for RAG)
    try:
        RAGPipeline().index_contract(parsed.text, str(cid), str(org_id))
        logger.info("chroma_indexed", contract_id=str(cid))
    except Exception as e:
        logger.warning("chroma_index_failed", error=str(e))

    return len(clauses_data), avg, overall


async def _process_contract(contract_id: str, org_id: str):
    """Background task for new uploads."""
    from app.infrastructure.database.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Contract).where(Contract.id == uuid.UUID(contract_id))
            )
            contract = result.scalar_one_or_none()
            if not contract:
                return
            await _extract_and_save(
                uuid.UUID(contract_id), uuid.UUID(org_id), contract
            )
    except Exception as exc:
        logger.error("background_process_failed", contract_id=contract_id, error=str(exc))
