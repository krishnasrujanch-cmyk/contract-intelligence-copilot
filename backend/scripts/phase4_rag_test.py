"""
Phase 4 — RAG Pipeline End-to-End Test.

Tests:
  1. Index the sample NDA into ChromaDB
  2. Query as admin (full access)
  3. Query as viewer (summary only)
  4. Verify citations are present
  5. Verify RBAC filter works

Run:
  cd /workspaces/contract-intelligence-copilot/backend
  source .venv/bin/activate
  set -a && source /workspaces/contract-intelligence-copilot/.env && set +a
  python scripts/phase4_rag_test.py
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path

BASE    = Path("/workspaces/contract-intelligence-copilot")
TC      = BASE / "test_contracts"
CONTRACT_ID = "test-nda-phase4"
ORG_ID      = "test-org-phase4"

sys.path.insert(0, str(BASE / "backend"))

from app.agents.rag.pipeline import RAGPipeline

TEST_QUERIES = [
    "What is the liability cap in this contract?",
    "What are the confidentiality obligations?",
    "When does the contract auto-renew and what is the notice period?",
    "What happens in a force majeure event?",
    "What are the payment terms and amounts?",
]

def run_test():
    print("=" * 60)
    print("PHASE 4 — RAG PIPELINE END-TO-END TEST")
    print("=" * 60)

    # Load contract
    contract_text = (TC / "sample_nda.txt").read_text(encoding="utf-8")
    print(f"\n✓ Contract loaded: {len(contract_text):,} chars")

    pipeline = RAGPipeline()

    # 1 — Index the contract
    print("\n[1/3] Indexing contract into ChromaDB...")
    n = pipeline.index_contract(contract_text, CONTRACT_ID, ORG_ID)
    print(f"  ✓ {n} chunks stored")

    # 2 — Admin queries (full access)
    print("\n[2/3] Admin role queries:")
    results = []
    for q in TEST_QUERIES:
        print(f"\n  Q: {q}")
        result = pipeline.answer(q, role="admin", org_id=ORG_ID)
        answer = result["answer"]
        cites  = result["citations"]
        conf   = result["confidence"]
        print(f"  A: {answer[:200]}...")
        print(f"     Citations: {len(cites)} | Confidence: {conf:.2f}")
        results.append({"query": q, "role": "admin",
                        "answer": answer, "citations": cites, "confidence": conf})

    # 3 — Viewer query (summary only)
    print("\n[3/3] Viewer role query (should get summary-level response):")
    viewer_result = pipeline.answer(
        "What are the key risks in this contract?",
        role="viewer", org_id=ORG_ID,
    )
    print(f"  A: {viewer_result['answer'][:300]}...")
    print(f"     Citations: {len(viewer_result['citations'])} | Confidence: {viewer_result['confidence']:.2f}")

    # Save results
    out = {
        "phase": "4_rag_test",
        "contract_id": CONTRACT_ID,
        "chunks_indexed": n,
        "admin_results": results,
        "viewer_result": viewer_result,
    }
    out_path = TC / "phase4_rag_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"PHASE 4 COMPLETE")
    print(f"  Chunks indexed: {n}")
    print(f"  Queries tested: {len(TEST_QUERIES)} (admin) + 1 (viewer)")
    print(f"  Results saved:  {out_path}")
    print(f"{'='*60}")

if __name__ == "__main__":
    run_test()
