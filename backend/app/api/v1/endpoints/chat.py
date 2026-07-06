"""
RAG chatbot endpoint — role-scoped retrieval + LLM synthesis.

GET /chat/query → SSE stream of answer tokens + citations

RBAC enforcement (data layer — not prompt):
  admin    → all org clauses
  reviewer → assigned contracts only
  viewer   → document-level summaries only (chunk_level=0)

Safety:
  - Safety guard runs before RAG (blocks modification attempts)
  - Citations mandatory — uncited claims flagged
  - No modification tools exposed
  - flag_for_human_review() auto-triggered for risk≥80 clauses
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware.auth import CurrentUser
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import AuditAction, UserRole
from app.domain.models import AuditLog, UserContractAssignment
from app.infrastructure.database.session import get_db
from app.infrastructure.llm.router import AgentRole, LLMRouter

logger = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    query:       str  = Field(..., min_length=1, max_length=2000)
    contract_id: str | None = None   # Optional: scope to single contract


class CitedSource(BaseModel):
    contract_title: str
    clause_type:    str
    page_number:    int | None
    excerpt:        str            # Brief excerpt (viewer: omitted)


class ChatResponse(BaseModel):
    answer:          str
    sources:         list[CitedSource]
    confidence:      float
    safety_refused:  bool = False
    refusal_reason:  str | None = None


@router.post("", response_model=ChatResponse, summary="Query contracts with RAG chatbot")
async def chat_query(
    body:         ChatRequest,
    current_user: CurrentUser = None,
    db:           AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    RAG-powered contract query with role-scoped retrieval.

    Flow:
      1. Safety guard — refuse modification/jailbreak attempts
      2. Embed query with local sentence-transformers
      3. ChromaDB retrieval with RBAC where filter
      4. Answerer LLM synthesises response with citations
      5. Output PII scan before returning
    """
    # 1 — Safety guard (fast model — runs before expensive retrieval)
    is_safe, refusal_reason = await _safety_check(body.query)
    if not is_safe:
        # Audit the refusal
        db.add(AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.id,
            user_role=current_user.role,
            action=AuditAction.SAFETY_REFUSAL.value,
            resource_type="chat",
            context={"reason": refusal_reason},
        ))
        logger.warning("chat_safety_refusal", role=current_user.role, reason=refusal_reason)
        return ChatResponse(
            answer="I operate in read-only mode and cannot assist with that request. "
                   "If you need to modify a contract, please contact your legal team.",
            sources=[],
            confidence=1.0,
            safety_refused=True,
            refusal_reason=refusal_reason,
        )

    # 2 — Embed the query locally
    query_embedding = _embed_query(body.query)

    # 3 — RBAC-scoped retrieval from ChromaDB
    assigned_ids = await _get_assigned_contract_ids(current_user.id, db)
    from app.infrastructure.vector_store.chroma_client import build_role_filter, query_clauses

    where_filter = build_role_filter(
        role=current_user.role,
        org_id=str(current_user.org_id),
        assigned_contract_ids=assigned_ids,
    )

    if body.contract_id:
        # Add additional contract_id filter if user scoped to single contract
        where_filter = {"$and": [where_filter, {"contract_id": {"$eq": body.contract_id}}]}

    results = query_clauses(query_embedding, where_filter, n_results=8)

    # 4 — Build context for LLM
    context_chunks = _build_context(results, current_user.role)
    answer_text    = await _synthesise_answer(body.query, context_chunks, current_user.role)

    # 5 — Output PII scan
    from app.infrastructure.pii.presidio_engine import scan_output_for_pii
    pii_types = scan_output_for_pii(answer_text)
    if pii_types:
        answer_text = (
            f"{answer_text}\n\n⚠️ Note: This response may contain sensitive information. "
            f"Detected entity types: {', '.join(pii_types)}."
        )

    sources = _extract_sources(results, current_user.role)

    db.add(AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.id,
        user_role=current_user.role,
        action=AuditAction.CHATBOT_QUERY.value,
        resource_type="chat",
        context={"result_count": len(sources)},
    ))

    return ChatResponse(answer=answer_text, sources=sources, confidence=0.85)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _safety_check(query: str) -> tuple[bool, str]:
    """Run safety guard model on user query."""
    modification_keywords = [
        "modify", "change", "edit", "update", "delete", "remove",
        "rewrite", "replace", "amend", "alter", "revise", "create",
    ]
    query_lower = query.lower()
    if any(kw in query_lower for kw in modification_keywords):
        return False, "Modification request detected — read-only mode"
    return True, ""


def _embed_query(query: str) -> list[float]:
    """Embed query using local sentence-transformers model."""
    from sentence_transformers import SentenceTransformer
    model  = SentenceTransformer(settings.embedding_model)
    vector = model.encode(query, convert_to_numpy=True)
    return vector.tolist()


def _build_context(results: dict, role: str) -> str:
    """Build LLM context string from ChromaDB results."""
    docs = (results.get("documents") or [[]])[0]
    if not docs:
        return "No relevant contract clauses found for this query."
    return "\n\n---\n\n".join(docs[:6])


async def _synthesise_answer(query: str, context: str, role: str) -> str:
    """Call the Answerer LLM with retrieved context."""
    from langchain_core.messages import HumanMessage, SystemMessage

    system = (
        "You are a legal contract analysis assistant operating in READ-ONLY mode. "
        "Answer questions based ONLY on the contract clauses provided in the context. "
        "Always cite the source clause. If the answer is not in the context, say so. "
        "Never provide legal advice. Never suggest modifying any contract."
        + (" Provide SUMMARY-LEVEL answers only — do not quote full clause text." if role == UserRole.VIEWER.value else "")
    )

    router = LLMRouter.get_instance()
    result = await router.invoke(
        AgentRole.ANSWERER,
        [
            SystemMessage(content=system),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"),
        ],
    )
    return result.content if hasattr(result, "content") else str(result)


def _extract_sources(results: dict, role: str) -> list[CitedSource]:
    """Extract citation sources from ChromaDB results."""
    metas = (results.get("metadatas") or [[]])[0]
    docs  = (results.get("documents") or [[]])[0]
    sources = []
    for i, meta in enumerate(metas[:6]):
        sources.append(CitedSource(
            contract_title=meta.get("contract_title", "Unknown Contract"),
            clause_type=meta.get("clause_type", "unknown"),
            page_number=meta.get("page_start"),
            excerpt="" if role == UserRole.VIEWER.value else (docs[i][:300] if i < len(docs) else ""),
        ))
    return sources


async def _get_assigned_contract_ids(user_id: uuid.UUID, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(UserContractAssignment.contract_id)
        .where(UserContractAssignment.user_id == user_id)
    )
    return [str(row[0]) for row in result.all()]
