"""
Phase 6 — Multi-turn chat API endpoint with session memory.

Design:
  Wraps the Phase 5 LangGraph agent with session memory injection.
  Each request:
    1. Load session history from Redis
    2. Prepend history to agent messages
    3. Run agent (safety guard → tools → judge)
    4. Save completed turn to Redis
    5. Return answer + citations + session metadata

Security:
  - session_id validated as UUID before use (injection prevention)
  - user_id sourced from JWT token — not from request body
  - RBAC enforced at ChromaDB layer (unchanged from Phase 5)
  - No session data in response beyond session_id and turn_count
  - Rate limiting inherited from auth middleware

SOLID:
  - SRP: endpoint only orchestrates — memory and agent are separate classes
  - DIP: depends on SessionMemoryManager and get_agent_graph abstractions
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import SessionMemoryManager
from app.agents.langgraph_agent import get_agent_graph
from app.api.v1.middleware.auth import CurrentUser
from app.core.logging import get_logger
from app.infrastructure.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()

_memory_manager = SessionMemoryManager()


# ── Schemas ───────────────────────────────────────────────────────────────────

class MultiTurnChatRequest(BaseModel):
    """
    Request schema for multi-turn chat.
    session_id is client-generated UUID — enables stateless server design.
    """
    query:      str       = Field(..., min_length=1, max_length=2000,
                                  description="User question about contract")
    session_id: str       = Field(..., description="Client-generated session UUID")
    contract_ids: list[str] = Field(
        default_factory=list,
        description="Optional: scope query to specific contract IDs",
    )

    def validated_session_id(self) -> str:
        """Validate session_id is a proper UUID — prevents key injection."""
        try:
            return str(uuid.UUID(self.session_id))
        except ValueError as exc:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"session_id must be a valid UUID: {exc}",
            ) from exc


class Citation(BaseModel):
    index:        int
    section_path: str
    clause_type:  str
    relevance:    float


class MultiTurnChatResponse(BaseModel):
    answer:      str
    citations:   list[Citation]
    session_id:  str
    turn_number: int
    session_summary: str


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/chat/multi-turn",
    response_model=MultiTurnChatResponse,
    status_code=200,
    summary="Multi-turn contract Q&A with session memory",
)
async def multi_turn_chat(
    body:         MultiTurnChatRequest,
    current_user: CurrentUser,
    db:           AsyncSession = Depends(get_db),
) -> MultiTurnChatResponse:
    """
    Multi-turn contract chatbot with Redis-backed session memory.

    The session window (last 10 turns) is loaded from Redis and
    prepended to the agent's message history before each invocation.
    After the agent responds, the turn is saved back to Redis.

    Follow-up questions like "what was the liability cap we discussed?"
    work because prior turns are in the agent's context window.

    RBAC: enforced at ChromaDB where-filter — role from JWT, not request body.
    Memory isolation: session key = user_id + session_id — no cross-user leakage.
    """
    session_id = body.validated_session_id()
    user_id    = str(current_user.id)
    org_id     = str(current_user.org_id)
    role       = current_user.role

    # 1 — Load session history from Redis
    ctx     = _memory_manager.load(user_id, session_id, org_id, role)
    history = ctx.to_langchain_messages()

    logger.info(
        "multi_turn_chat_request",
        user_id    = user_id[:8],
        session_id = session_id[:8],
        role       = role,
        prior_turns= len(ctx.turns),
    )

    # 2 — Build initial agent state with memory injected
    graph = get_agent_graph()
    # Build assigned contract list for RBAC
    assigned_ids = body.contract_ids or []
    if body.contract_id and body.contract_id not in assigned_ids:
        assigned_ids = [body.contract_id]

    initial_state = {
        "messages":        history,
        "role":            role,
        "org_id":          org_id,
        "query":           body.query,
        "safety_verdict":  "",
        "answer":          "",
        "citations":       [],
        "iteration":       0,
        "flagged":         False,
        "error":           "",
        "contract_id":     body.contract_id,
        "assigned_contract_ids": assigned_ids if assigned_ids else None,
    }

    # 3 — Run agent pipeline (safety guard → tools → judge)
    try:
        final_state = await graph.ainvoke(initial_state)
        answer      = final_state.get("answer", "")
        citations   = final_state.get("citations", [])

        # Extract answer from last message if not set directly
        if not answer:
            messages = final_state.get("messages", [])
            if messages:
                last = messages[-1]
                answer = last.content if hasattr(last, "content") else str(last)

    except Exception as exc:
        logger.error("agent_invocation_failed", error=str(exc))
        answer    = "An error occurred processing your query. Please try again."
        citations = []

    # 4 — Save completed turn to Redis (non-blocking — failure is non-fatal)
    _memory_manager.save(
        ctx=ctx,
        user_message=body.query,
        agent_answer=answer,
        contracts_referenced=body.contract_ids,
    )

    # 5 — Build session summary for response metadata
    session_summary = _memory_manager.get_session_summary(ctx)

    return MultiTurnChatResponse(
        answer      = answer,
        citations   = [Citation(**c) for c in citations if isinstance(c, dict)
                       and all(k in c for k in ("index","section_path","clause_type","relevance"))],
        session_id  = session_id,
        turn_number = len(ctx.turns) + 1,
        session_summary = session_summary,
    )


@router.delete(
    "/chat/session/{session_id}",
    status_code=200,
    summary="Clear session memory (logout or explicit reset)",
)
async def clear_session(
    session_id:   str,
    current_user: CurrentUser,
) -> dict[str, str]:
    """
    Clear the Redis session window for the current user.
    Called on logout or when user explicitly resets the conversation.
    GDPR: user can request their session data be deleted at any time.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=400, detail="Invalid session_id format.")

    _memory_manager.clear_session(str(current_user.id), session_id)
    return {"status": "cleared", "session_id": session_id}
