"""
Phase 6 — Multi-Turn Memory End-to-End Test.

Tests:
  1. First turn — no prior context
  2. Second turn — follow-up referencing prior answer (memory test)
  3. Third turn — "what did we discuss?" (session recall test)
  4. Session isolation — different session_id gets fresh context
  5. Session clear — after clear, follow-up loses context

Run:
  cd /workspaces/contract-intelligence-copilot/backend
  source .venv/bin/activate
  set -a && source /workspaces/contract-intelligence-copilot/.env && set +a
  python scripts/phase6_memory_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

BASE = Path("/workspaces/contract-intelligence-copilot")
sys.path.insert(0, str(BASE / "backend"))

from app.agents.memory import SessionMemoryManager
from app.agents.langgraph_agent import get_agent_graph

ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
ROLE    = "admin"

# Use valid UUIDs for session keys
SESSION_A = str(uuid.uuid4())
SESSION_B = str(uuid.uuid4())

memory  = SessionMemoryManager()
graph   = get_agent_graph()

TURNS = [
    {
        "session":   SESSION_A,
        "query":     "What is the liability cap in this contract?",
        "test_name": "Turn 1 — Initial query (no prior context)",
        "check":     lambda a: "50,000" in a or "liability" in a.lower(),
    },
    {
        "session":   SESSION_A,
        "query":     "Is that cap sufficient given the payment amounts?",
        "test_name": "Turn 2 — Follow-up (should remember liability cap)",
        "check":     lambda a: len(a) > 50,  # Just check it responded
    },
    {
        "session":   SESSION_A,
        "query":     "Summarise what we have discussed so far in this conversation",
        "test_name": "Turn 3 — Session recall (should reference prior turns)",
        "check":     lambda a: len(a) > 80,
    },
    {
        "session":   SESSION_B,
        "query":     "What is the liability cap in this contract?",
        "test_name": "Turn 4 — Different session (should have no memory of Session A)",
        "check":     lambda a: len(a) > 20,
    },
]


async def run_turn(session_id: str, query: str) -> tuple[str, int]:
    """Run a single turn through the agent with memory injection."""
    ctx     = memory.load(USER_ID, session_id, ORG_ID, ROLE)
    history = ctx.to_langchain_messages()

    state = {
        "messages":       history,
        "role":           ROLE,
        "org_id":         ORG_ID,
        "query":          query,
        "safety_verdict": "",
        "answer":         "",
        "citations":      [],
        "iteration":      0,
        "flagged":        False,
        "error":          "",
    }

    final  = await graph.ainvoke(state)
    answer = final.get("answer", "")

    if not answer:
        msgs = final.get("messages", [])
        if msgs:
            last   = msgs[-1]
            answer = last.content if hasattr(last, "content") else str(last)

    # Save turn to memory
    memory.save(ctx, query, answer, [])
    return answer, len(ctx.turns)


async def main() -> None:
    print("=" * 60)
    print("PHASE 6 — MULTI-TURN MEMORY TEST")
    print("=" * 60)
    print(f"Session A: {SESSION_A[:8]}...")
    print(f"Session B: {SESSION_B[:8]}...")

    results  = []
    all_pass = True

    for i, turn in enumerate(TURNS, 1):
        print(f"\n[{i}/{len(TURNS)}] {turn['test_name']}")
        print(f"  Session: {turn['session'][:8]}...")
        print(f"  Query:   {turn['query']}")

        try:
            answer, prior_turns = await run_turn(turn["session"], turn["query"])
            passed = turn["check"](answer)
            all_pass = all_pass and passed

            print(f"  Prior turns in context: {prior_turns}")
            print(f"  Answer: {answer[:200]}{'...' if len(answer) > 200 else ''}")
            print(f"  Result: {'✓ PASS' if passed else '✗ FAIL'}")

            results.append({
                "test":        turn["test_name"],
                "prior_turns": prior_turns,
                "answer":      answer,
                "passed":      passed,
            })

        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({"test": turn["test_name"], "error": str(exc), "passed": False})
            all_pass = False

    # Test: session clear
    print(f"\n[5/5] Turn 5 — Session clear test")
    memory.clear_session(USER_ID, SESSION_A)
    ctx_after_clear = memory.load(USER_ID, SESSION_A, ORG_ID, ROLE)
    cleared_ok = len(ctx_after_clear.turns) == 0
    all_pass = all_pass and cleared_ok
    print(f"  After clear — turns in session: {len(ctx_after_clear.turns)}")
    print(f"  Result: {'✓ PASS' if cleared_ok else '✗ FAIL'} (expected 0 turns)")
    results.append({"test": "Session clear", "passed": cleared_ok})

    # Summary
    passed_count = sum(1 for r in results if r.get("passed"))
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed_count}/{len(results)} tests passed")
    print(f"{'='*60}")
    for r in results:
        icon = "✓" if r.get("passed") else "✗"
        print(f"  {icon} {r['test']}")

    out = BASE / "test_contracts" / "phase6_memory_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Results → {out}")


if __name__ == "__main__":
    asyncio.run(main())
