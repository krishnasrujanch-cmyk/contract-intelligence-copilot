"""
Phase 3a — Baseline Regex Clause Detector.

Documented limitations (required by capstone):
  LIMITATION 1 — Vocabulary brittleness:
    Regex matches only explicit ARTICLE/SECTION markers. Contracts using
    numbered clauses ("12. INDEMNIFICATION") or subsections (Section 5.2)
    are missed entirely. Non-standard templates produce zero results.

  LIMITATION 2 — No semantic understanding:
    Cannot distinguish a force majeure clause from text that merely mentions
    the term. Cannot extract USD amounts, notice periods, or dates.
    Risk scoring is impossible — regex has no concept of legal risk.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RegexClause:
    clause_type: str
    title:       str
    raw_text:    str
    char_start:  int
    char_end:    int
    confidence:  float
    risk_score:  None = None
    risk_reason: None = None


@dataclass
class ExtractionResult:
    clauses:          list[RegexClause]
    duration_seconds: float
    char_count:       int
    method:           str = "regex_baseline"
    limitations:      list[str] = field(default_factory=list)


_CLAUSE_TYPES = "confidentiality, termination, ip_ownership, liability, indemnification, payment, auto_renewal, governing_law, force_majeure, general"

_CLAUSE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("confidentiality", re.compile(
        r"ARTICLE\s+\d+\.\s+(?:CONFIDENTIALITY|NON-DISCLOSURE)[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("termination", re.compile(
        r"ARTICLE\s+\d+\.\s+TERM(?:\s+AND)?\s+TERMINATION[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("ip_ownership", re.compile(
        r"ARTICLE\s+\d+\.\s+INTELLECTUAL PROPERTY[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("liability", re.compile(
        r"ARTICLE\s+\d+\.\s+LIABILITY[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("payment", re.compile(
        r"ARTICLE\s+\d+\.\s+PAYMENT[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("governing_law", re.compile(
        r"ARTICLE\s+\d+\.\s+GOVERNING LAW[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("force_majeure", re.compile(
        r"ARTICLE\s+\d+\.\s+FORCE MAJEURE[^\n]*\n((?:(?!ARTICLE\s+\d+\.).+\n?){1,60})",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("auto_renewal", re.compile(
        r"automatically\s+renew.{0,300}days?\s+prior",
        re.IGNORECASE | re.DOTALL,
    )),
]

_DOCUMENTED_LIMITATIONS = [
    "LIMITATION 1 — Vocabulary brittleness: Regex matches only explicit ARTICLE/SECTION "
    "markers. Contracts using numbered clauses or subsections are missed entirely. "
    "The USD 50,000 liability cap (Section 5.2) is not detected as a standalone clause.",

    "LIMITATION 2 — Zero semantic understanding: Cannot distinguish a force majeure clause "
    "from text that merely mentions the term. Cannot extract USD amounts, notice periods, "
    "or dates. Risk scoring is impossible — regex has no concept of legal risk or "
    "industry-standard benchmarks. All matches receive confidence=1.0 regardless of quality.",
]


class RegexClauseExtractor:
    def __init__(self) -> None:
        self._patterns = _CLAUSE_PATTERNS

    def extract(self, text: str) -> ExtractionResult:
        start   = time.perf_counter()
        clauses: list[RegexClause] = []
        seen:    list[tuple[int, int]] = []

        for clause_type, pattern in self._patterns:
            for match in pattern.finditer(text):
                s, e = match.start(), match.end()
                if any(a <= s <= b or a <= e <= b for a, b in seen):
                    continue
                seen.append((s, e))
                raw = match.group(0).strip()
                clauses.append(RegexClause(
                    clause_type=clause_type,
                    title=self._title(raw),
                    raw_text=raw,
                    char_start=s,
                    char_end=e,
                    confidence=1.0,
                ))

        return ExtractionResult(
            clauses=sorted(clauses, key=lambda c: c.char_start),
            duration_seconds=round(time.perf_counter() - start, 4),
            char_count=len(text),
            limitations=_DOCUMENTED_LIMITATIONS,
        )

    @staticmethod
    def _title(text: str) -> str:
        for line in text.splitlines():
            s = line.strip()
            if s:
                return s[:120]
        return "Untitled Clause"


def evaluate(result: ExtractionResult, ground_truth: list[dict]) -> dict:
    extracted = [c.clause_type for c in result.clauses]
    gt_types  = [g["clause_type"] for g in ground_truth]
    tp = sum(1 for g in gt_types if g in extracted)
    fp = sum(1 for e in extracted if e not in gt_types)
    fn = sum(1 for g in gt_types if g not in extracted)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    missed = [g for g in ground_truth if g["clause_type"] not in extracted]
    return {
        "method": "regex_baseline",
        "clauses_found": len(result.clauses),
        "clauses_expected": len(ground_truth),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": round(prec, 3), "recall": round(rec, 3), "f1_score": round(f1, 3),
        "risk_scoring": "NOT SUPPORTED",
        "processing_time_seconds": result.duration_seconds,
        "missed_clauses": [{"id": m["id"], "type": m["clause_type"], "title": m["title"]} for m in missed],
    }


def run_baseline(contract_path: Path, gt_path: Path, out_path: Path) -> dict:
    text  = contract_path.read_text(encoding="utf-8")
    gt    = json.loads(gt_path.read_text(encoding="utf-8"))
    ext   = RegexClauseExtractor()
    res   = ext.extract(text)
    metrics = evaluate(res, gt)
    output = {
        "phase": "3a_baseline_regex",
        "contract": contract_path.name,
        "metrics": metrics,
        "extracted_clauses": [
            {"clause_type": c.clause_type, "title": c.title,
             "risk_score": None, "text_preview": c.raw_text[:200]}
            for c in res.clauses
        ],
        "documented_limitations": res.limitations,
    }
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    base = Path(__file__).parent.parent.parent.parent
    result = run_baseline(
        contract_path = base / "test_contracts" / "sample_nda.txt",
        gt_path       = base / "test_contracts" / "ground_truth_clauses.json",
        out_path      = base / "test_contracts" / "baseline_results.json",
    )
    m = result["metrics"]
    print(f"\n{'='*55}")
    print(f"PHASE 3a — BASELINE REGEX RESULTS")
    print(f"{'='*55}")
    print(f"Clauses found :  {m['clauses_found']} / {m['clauses_expected']}")
    print(f"Precision     :  {m['precision']:.1%}")
    print(f"Recall        :  {m['recall']:.1%}")
    print(f"F1 Score      :  {m['f1_score']:.1%}")
    print(f"Risk scoring  :  {m['risk_scoring']}")
    print(f"Time          :  {m['processing_time_seconds']}s")
    print(f"\nMISSED ({len(m['missed_clauses'])}):")
    for mc in m["missed_clauses"]:
        print(f"  [{mc['id']}] {mc['type']:20s} {mc['title']}")
    print(f"\nLIMITATIONS:")
    for lim in result["documented_limitations"]:
        print(f"\n  {lim[:100]}...")
    print(f"\n✓ Results → test_contracts/baseline_results.json")
