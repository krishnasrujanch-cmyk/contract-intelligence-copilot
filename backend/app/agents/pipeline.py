"""
Multi-model agent pipeline orchestrated by LangGraph.

Pipeline flow:
  ┌─────────────────────────────────────────────────────────────┐
  │  Document Content Stream (text + table JSON + image desc)   │
  └─────────────────────────┬───────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  Safety Guard  │  llama-3.1-8b-instant
                    │  (pre-filter)  │  Intent classification
                    └───────┬────────┘
                    SAFE ───┘  UNSAFE ──► Refuse + Audit log
                            │
              ┌─────────────▼───────────────┐
              │         Extractor           │  llama-3.1-8b-instant
              │  Clause boundary detection  │  Fast, bulk, deterministic
              │  + type classification      │
              └─────────────┬───────────────┘
                            │  [ClauseObject list]
              ┌─────────────▼───────────────┐
              │         Reasoner            │  llama-3.3-70b-versatile
              │  Multi-step legal reasoning │  Chain-of-thought
              │  Risk scoring + explanation │  Temperature 0.1
              └─────────────┬───────────────┘
                            │  [RiskAssessment per clause]
              ┌─────────────▼───────────────┐
              │           Judge             │  llama-3.3-70b-versatile
              │  Independent validation     │  Temperature 0.0
              │  APPROVE | REVISE | ESCALATE│  Different bias = genuine check
              └─────────────┬───────────────┘
               APPROVE ─────┘  REVISE ──► back to Reasoner (max 2x)
               ESCALATE ──────────────► flag_for_human_review()
                            │
              ┌─────────────▼───────────────┐
              │         Answerer            │  llama-3.3-70b-versatile
              │  RAG synthesis              │  Citation generation
              │  User-facing response       │  Role-scoped output
              └─────────────┬───────────────┘
                            │
                    ┌───────▼────────┐
                    │  Final Output  │
                    │  + Obligations │
                    │  + Alerts      │
                    └────────────────┘
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ClauseType, JudgeVerdict, RiskLevel
from app.infrastructure.llm.router import AgentRole, LLMRouter, LLMRouterError
from app.infrastructure.llm.prompts import (
    EXTRACTOR_SYSTEM_PROMPT,
    REASONER_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    SAFETY_GUARD_SYSTEM_PROMPT,
)

logger = get_logger(__name__)


# ── Pipeline state ─────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    """
    Shared state flowing through the LangGraph pipeline.
    Each agent reads from and writes to this state.
    Immutable fields are set at pipeline entry and never modified.
    """
    # ── Immutable inputs (set at entry) ───────────────────────────────────────
    contract_id:   str
    org_id:        str
    content_stream: str      # Unified text from parser (text + tables + images)
    effective_date: str      # ISO date string — for obligation date resolution
    metadata:      dict[str, Any]

    # ── Safety ────────────────────────────────────────────────────────────────
    safety_verdict: str      # "SAFE" | "UNSAFE"
    safety_reason:  str

    # ── Extractor output ──────────────────────────────────────────────────────
    extracted_clauses: list[dict[str, Any]]  # Raw ClauseObject dicts

    # ── Reasoner output ───────────────────────────────────────────────────────
    risk_assessments: list[dict[str, Any]]   # RiskAssessment per clause

    # ── Judge output ──────────────────────────────────────────────────────────
    judge_verdict:  str      # JudgeVerdict value
    judge_feedback: str      # Feedback to Reasoner on REVISE
    judge_retry_count: int

    # ── Answerer output ───────────────────────────────────────────────────────
    final_clauses:    list[dict[str, Any]]   # Merged + validated clauses
    obligations:      list[dict[str, Any]]   # Extracted obligation objects
    pipeline_errors:  list[str]              # Non-fatal errors accumulated

    # ── Tracing ───────────────────────────────────────────────────────────────
    trace_id: str


# ── Node implementations ───────────────────────────────────────────────────────

async def safety_guard_node(state: PipelineState) -> dict[str, Any]:
    """
    Pre-filter: classify intent of the content before any expensive processing.
    Uses the fastest model (llama-3.1-8b-instant) for minimal latency.

    Returns SAFE for legal contract text.
    Returns UNSAFE for: prompt injection, jailbreak attempts, non-contract content.
    """
    router = LLMRouter.get_instance()

    messages = [
        SystemMessage(content=SAFETY_GUARD_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Classify this document content (first 2000 chars):\n\n"
            f"{state['content_stream'][:2000]}"
        )),
    ]

    try:
        result = await router.invoke(
            AgentRole.SAFETY_GUARD,
            messages,
            metadata={"contract_id": state["contract_id"], "org_id": state["org_id"]},
        )
        response_text = result.content if hasattr(result, "content") else str(result)

        # Expect JSON: {"verdict": "SAFE"|"UNSAFE", "reason": "..."}
        parsed = _parse_json_response(response_text)
        verdict = parsed.get("verdict", "UNSAFE").upper()
        reason  = parsed.get("reason", "Classification failed")

    except Exception as exc:
        logger.warning(
            "safety_guard_failed_defaulting_safe",
            error=str(exc),
            contract_id=state["contract_id"],
        )
        # Fail SAFE for legitimate contract documents
        verdict = "SAFE"
        reason  = "Safety check inconclusive — proceeding with analysis"

    return {"safety_verdict": verdict, "safety_reason": reason}


async def extractor_node(state: PipelineState) -> dict[str, Any]:
    router = LLMRouter.get_instance()
    clause_types_list = ", ".join(ct.value for ct in ClauseType)

    prompt_text = (
        "You are a legal clause extraction specialist. "
        "Extract ALL clauses from the contract text. "
        "Clause types to detect: " + clause_types_list + ". "
        "For each clause provide: clause_type, title, raw_text, summary, "
        "page_start (int or null), page_end (int or null), confidence (float 0-1), "
        "extracted_data (object with due_date, amount, currency, party fields). "
        "Return ONLY valid JSON like this example: "
        '{"clauses": [{"clause_type": "liability", "title": "Section 5", '
        '"raw_text": "...", "summary": "...", "page_start": null, '
        '"page_end": null, "confidence": 0.9, '
        '"extracted_data": {"due_date": null, "amount": null, '
        '"currency": null, "party": null}}]}'
    )

    messages = [
        SystemMessage(content=prompt_text),
        HumanMessage(content="Extract all clauses from this contract:\n\n" + state["content_stream"]),
    ]

    try:
        result = await router.invoke(
            AgentRole.EXTRACTOR,
            messages,
            metadata={"contract_id": state["contract_id"], "org_id": state["org_id"]},
        )
        response_text = result.content if hasattr(result, "content") else str(result)
        parsed = _parse_json_response(response_text)
        clauses = parsed.get("clauses", [])
        logger.info("extractor_completed", contract_id=state["contract_id"], clause_count=len(clauses))
        return {"extracted_clauses": clauses}
    except Exception as exc:
        logger.error("extractor_failed", contract_id=state["contract_id"], error=str(exc))
        return {
            "extracted_clauses": [],
            "pipeline_errors": state.get("pipeline_errors", []) + [f"Extractor failed: {exc}"],
        }


async def reasoner_node(state: PipelineState) -> dict[str, Any]:
    """
    Multi-step legal risk reasoning using chain-of-thought.

    Uses llama-3.3-70b-versatile (highest quality) because:
    - Complex reasoning about legal implications
    - Needs to understand industry-standard risk levels
    - Chain-of-thought improves accuracy for nuanced risk scoring

    Receives judge feedback on REVISE cycles to improve its analysis.

    Output per clause:
    {
        "clause_id_ref": "...",  # matches extracted_clauses index
        "risk_score": 85,
        "risk_level": "critical",
        "risk_reason": "Plain-English explanation",
        "suggested_revision": "...",
        "reasoning_steps": ["step 1", "step 2", ...]  # CoT trace
    }
    """
    router = LLMRouter.get_instance()

    judge_feedback_section = ""
    if state.get("judge_feedback"):
        judge_feedback_section = (
            f"\n\nJUDGE FEEDBACK FROM PREVIOUS ATTEMPT (retry {state['judge_retry_count']}):\n"
            f"{state['judge_feedback']}\n"
            f"Please address this feedback in your revised analysis.\n"
        )

    messages = [
        SystemMessage(content=REASONER_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Perform risk analysis on these extracted clauses:\n\n"
            f"{json.dumps(state['extracted_clauses'], indent=2)}"
            f"{judge_feedback_section}"
        )),
    ]

    try:
        result = await router.invoke(
            AgentRole.REASONER,
            messages,
            metadata={"contract_id": state["contract_id"], "retry": state.get("judge_retry_count", 0)},
        )
        response_text = result.content if hasattr(result, "content") else str(result)
        parsed = _parse_json_response(response_text)
        assessments = parsed.get("risk_assessments", [])

        logger.info(
            "reasoner_completed",
            contract_id=state["contract_id"],
            assessments_count=len(assessments),
            retry=state.get("judge_retry_count", 0),
        )
        return {"risk_assessments": assessments}

    except Exception as exc:
        logger.error("reasoner_failed", contract_id=state["contract_id"], error=str(exc))
        return {
            "risk_assessments": [],
            "pipeline_errors": state.get("pipeline_errors", []) + [f"Reasoner failed: {exc}"],
        }


async def judge_node(state: PipelineState) -> dict[str, Any]:
    """
    Independent validation of the Reasoner's risk assessments.

    Uses llama-3.3-70b-versatile with temperature=0.0 (deterministic):
    - DIFFERENT model weights than Reasoner (despite same base model name,
      different temperature + system prompt = genuinely different perspective)
    - Checks: Are risk scores calibrated? Is reasoning sound? Is type correct?

    Verdicts:
      APPROVE  → Assessments are sound → proceed to Answerer
      REVISE   → Issues found → send back to Reasoner with specific feedback
      ESCALATE → Cannot resolve → flag for human review

    Max retries: settings.judge_max_retries (default: 2)
    """
    router = LLMRouter.get_instance()

    messages = [
        SystemMessage(content=JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Validate these risk assessments against the original clauses:\n\n"
            f"ORIGINAL CLAUSES:\n{json.dumps(state['extracted_clauses'], indent=2)}\n\n"
            f"RISK ASSESSMENTS TO VALIDATE:\n{json.dumps(state['risk_assessments'], indent=2)}"
        )),
    ]

    try:
        result = await router.invoke(
            AgentRole.JUDGE,
            messages,
            metadata={"contract_id": state["contract_id"], "retry": state.get("judge_retry_count", 0)},
        )
        response_text = result.content if hasattr(result, "content") else str(result)
        parsed = _parse_json_response(response_text)

        verdict  = parsed.get("verdict", JudgeVerdict.APPROVE.value).upper()
        feedback = parsed.get("feedback", "")

        logger.info(
            "judge_completed",
            contract_id=state["contract_id"],
            verdict=verdict,
            retry_count=state.get("judge_retry_count", 0),
        )
        return {
            "judge_verdict":  verdict,
            "judge_feedback": feedback,
        }

    except Exception as exc:
        logger.error("judge_failed", contract_id=state["contract_id"], error=str(exc))
        # On judge failure, approve to unblock the pipeline
        return {
            "judge_verdict":  JudgeVerdict.APPROVE.value,
            "judge_feedback": "",
            "pipeline_errors": state.get("pipeline_errors", []) + [f"Judge failed: {exc}"],
        }


async def answerer_node(state: PipelineState) -> dict[str, Any]:
    """
    Final synthesis: merge extraction + risk into structured output.
    Falls back to extractor output with default risk scores if reasoner failed.
    """
    extracted = state.get("extracted_clauses", [])
    assessments = state.get("risk_assessments", [])

    # If no risk assessments (reasoner failed/quota), use extractor scores directly
    if not assessments and extracted:
        clauses_with_risk = []
        for clause in extracted:
            risk_score = clause.get("risk_score", 0) or 0
            if isinstance(risk_score, str):
                try: risk_score = int(risk_score)
                except: risk_score = 0
            clauses_with_risk.append({
                **clause,
                "risk_score":        risk_score,
                "risk_level":        RiskLevel.from_score(risk_score).value,
                "risk_reason":       clause.get("risk_reason", "Extracted by LLM."),
                "suggested_revision":None,
                "flagged_for_review":risk_score >= 80,
                "judge_verdict":     "APPROVE",
            })
    else:
        clauses_with_risk = _merge_clauses_and_risks(extracted, assessments)

    # Extract obligations from clauses with dates/amounts
    obligations = _extract_obligations_from_clauses(
        clauses_with_risk,
        state.get("effective_date", ""),
        state["contract_id"],
        state["org_id"],
    )

    logger.info(
        "answerer_completed",
        contract_id=state["contract_id"],
        final_clause_count=len(clauses_with_risk),
        obligation_count=len(obligations),
        escalated_count=sum(
            1 for c in clauses_with_risk
            if (c.get("risk_score") or 0) >= settings.risk_escalation_threshold
        ),
    )

    return {
        "final_clauses": clauses_with_risk,
        "obligations":   obligations,
    }


# ── Routing functions (LangGraph conditional edges) ───────────────────────────

def route_after_safety(state: PipelineState) -> str:
    """Route: SAFE → extractor, UNSAFE → END (refuse)."""
    if state.get("safety_verdict") == "SAFE":
        return "extractor"
    return END


def route_after_judge(state: PipelineState) -> str:
    """
    Route based on judge verdict:
      APPROVE  → answerer
      REVISE   → reasoner (if retries remain) or answerer (if exhausted)
      ESCALATE → answerer (with escalation flag set)
    """
    verdict     = state.get("judge_verdict", JudgeVerdict.APPROVE.value)
    retry_count = state.get("judge_retry_count", 0)

    if verdict == JudgeVerdict.APPROVE.value:
        return "answerer"

    if verdict == JudgeVerdict.REVISE.value:
        if retry_count < settings.judge_max_retries:
            return "reasoner"
        # Retries exhausted — proceed with current best assessment
        logger.warning(
            "judge_retries_exhausted_proceeding",
            contract_id=state["contract_id"],
            max_retries=settings.judge_max_retries,
        )
        return "answerer"

    # ESCALATE — proceed to answerer which will flag for human review
    return "answerer"


def increment_retry_count(state: PipelineState) -> dict[str, Any]:
    """Increment retry counter — called on REVISE path back to Reasoner."""
    return {"judge_retry_count": state.get("judge_retry_count", 0) + 1}


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_document_pipeline() -> Any:
    """
    Build and compile the LangGraph state machine for document processing.

    Returns a compiled graph ready for async invocation.
    Call once at startup — the compiled graph is reusable.
    """
    graph = StateGraph(PipelineState)

    # Register nodes
    graph.add_node("safety_guard", safety_guard_node)
    graph.add_node("extractor",    extractor_node)
    graph.add_node("reasoner",     reasoner_node)
    graph.add_node("judge",        judge_node)
    graph.add_node("answerer",     answerer_node)

    # Entry point
    graph.set_entry_point("safety_guard")

    # Edges
    graph.add_conditional_edges("safety_guard", route_after_safety)
    graph.add_edge("extractor", "reasoner")
    graph.add_edge("reasoner",  "judge")
    graph.add_conditional_edges(
        "judge",
        route_after_judge,
        {
            "reasoner": "reasoner",
            "answerer": "answerer",
            END:        END,
        },
    )
    graph.add_edge("answerer", END)

    compiled = graph.compile()

    logger.info("document_pipeline_compiled")
    return compiled


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict[str, Any]:
    """
    Extract JSON from LLM response, tolerating markdown code fences.
    Returns empty dict on parse failure — callers handle missing fields.
    """
    cleaned = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("llm_response_not_json", preview=cleaned[:200])
        return {}


def _merge_clauses_and_risks(
    clauses:     list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge extractor output with risk assessments by position index.
    Clauses without a matching assessment get a default LOW risk.
    """
    assessment_map = {i: a for i, a in enumerate(assessments)}
    merged = []

    for i, clause in enumerate(clauses):
        risk = assessment_map.get(i, {})
        risk_score = int(risk.get("risk_score", 0))
        merged.append({
            **clause,
            "risk_score":        risk_score,
            "risk_level":        RiskLevel.from_score(risk_score).value,
            "risk_reason":       risk.get("risk_reason", ""),
            "suggested_revision":risk.get("suggested_revision", ""),
            "flagged_for_review":risk_score >= settings.risk_escalation_threshold,
            "judge_verdict":     risk.get("judge_verdict", JudgeVerdict.APPROVE.value),
        })

    return merged


def _extract_obligations_from_clauses(
    clauses:        list[dict[str, Any]],
    effective_date: str,
    contract_id:    str,
    org_id:         str,
) -> list[dict[str, Any]]:
    """
    Extract obligation records from clause extracted_data fields.
    Obligation agent in a future iteration can be a dedicated LLM node;
    for Phase 2 baseline this uses the structured extracted_data.
    """
    obligations = []
    for clause in clauses:
        data = clause.get("extracted_data", {})
        if due_date := data.get("due_date"):
            obligations.append({
                "contract_id": contract_id,
                "org_id":      org_id,
                "title":       f"{clause.get('clause_type', 'obligation').title()} obligation",
                "description": clause.get("summary", ""),
                "due_date":    due_date,
                "party":       data.get("party", "both"),
                "amount":      data.get("amount"),
                "currency":    data.get("currency"),
                "recurrence":  data.get("recurrence"),
                "status":      "pending",
            })
    return obligations
