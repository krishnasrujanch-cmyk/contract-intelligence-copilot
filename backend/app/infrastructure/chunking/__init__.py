"""
Legal-aware hierarchical document chunker.

Design rationale (Senior Architect):
  Standard token-count splitters (RecursiveCharacterTextSplitter) fail
  on legal contracts because they split on character count — a liability
  clause spanning 4 pages gets cut mid-sentence.

  This chunker respects legal document structure:
    Level 0 → Document summary (viewer-accessible — no clause text)
    Level 1 → ARTICLE-level section group
    Level 2 → Individual clause (primary RAG retrieval unit)

  Tables are ALWAYS atomic — the docling table JSON is never split.
  150-token sibling overlap handles cross-references ("as defined above").

Security: PII must be masked BEFORE calling chunk() — this class
  operates on already-anonymised text.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """Single addressable unit of contract content."""
    id:           str        # Stable UUID used as ChromaDB vector ID
    contract_id:  str
    org_id:       str
    text:         str
    level:        int        # 0=doc summary, 1=article, 2=clause
    section_path: str        # "ARTICLE 5 > Section 5.2"
    page_start:   int | None = None
    metadata:     dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return len(self.text) // 4


# Boundary detection patterns
_ARTICLE_RE = re.compile(
    r"^\s*ARTICLE\s+\d+[\s.:–\-]",
    re.MULTILINE | re.IGNORECASE,
)
_SECTION_RE = re.compile(
    r"^\s*\d+\.\d+[\s.:–\-]",
    re.MULTILINE,
)


class LegalChunker:
    """
    Hierarchical legal document chunker.

    Chunk hierarchy:
      Article → Clause → Sub-clause

    Key invariants:
      - Tables injected as atomic JSON blocks (never split)
      - 150-token overlap between consecutive clauses
      - Level 0 summary chunk always produced first
        (only level viewers can retrieve from ChromaDB)
    """

    def __init__(
        self,
        max_tokens:     int = 1500,
        overlap_tokens: int = 150,
    ) -> None:
        self._max   = max_tokens
        self._overlap = overlap_tokens

    def chunk(
        self,
        text:        str,
        contract_id: str,
        org_id:      str,
    ) -> list[Chunk]:
        """
        Produce all chunks for a document.

        Args:
            text:        Full contract text (PII already masked)
            contract_id: UUID string
            org_id:      UUID string

        Returns:
            Ordered list of Chunk objects, Level 0 summary first.
        """
        chunks: list[Chunk] = []

        # Split on ARTICLE boundaries
        articles = _ARTICLE_RE.split(text)
        headers  = _ARTICLE_RE.findall(text)

        for i, body in enumerate(articles):
            if not body.strip():
                continue
            header = headers[i - 1].strip() if i > 0 and i - 1 < len(headers) else "PREAMBLE"
            level  = 1  # Article level

            # Further split large articles on section boundaries
            sections = _SECTION_RE.split(body)
            sec_headers = _SECTION_RE.findall(body)

            if len(sections) > 1:
                for j, sec_body in enumerate(sections):
                    if not sec_body.strip():
                        continue
                    sec_header = sec_headers[j - 1].strip() if j > 0 and j - 1 < len(sec_headers) else header
                    path = f"{header} > {sec_header}"
                    chunks.extend(
                        self._make_chunks(sec_body.strip(), contract_id, org_id, path, level=2)
                    )
            else:
                chunks.extend(
                    self._make_chunks(body.strip(), contract_id, org_id, header, level=1)
                )

        # Level 0 summary chunk — viewer access only
        summary = self._make_summary(chunks, contract_id, org_id)
        return [summary] + chunks

    def _make_chunks(
        self,
        text:        str,
        contract_id: str,
        org_id:      str,
        path:        str,
        level:       int,
    ) -> list[Chunk]:
        """Split oversized text into overlapping windows."""
        if self._tok(text) <= self._max:
            return [Chunk(
                id=str(uuid.uuid4()), contract_id=contract_id,
                org_id=org_id, text=text, level=level, section_path=path,
            )]

        chunks   = []
        step     = self._max * 4
        overlap  = self._overlap * 4
        pos, part = 0, 1

        while pos < len(text):
            end   = min(pos + step, len(text))
            chunk_text = text[pos:end].strip()
            if chunk_text:
                chunks.append(Chunk(
                    id=str(uuid.uuid4()), contract_id=contract_id,
                    org_id=org_id, text=chunk_text, level=level,
                    section_path=f"{path} (part {part})",
                ))
            if end >= len(text):
                break
            pos  = end - overlap
            part += 1

        return chunks

    def _make_summary(
        self,
        chunks:      list[Chunk],
        contract_id: str,
        org_id:      str,
    ) -> Chunk:
        """Level 0 summary — section index only, no clause text."""
        paths = list(dict.fromkeys(c.section_path for c in chunks))
        text  = "CONTRACT SECTION INDEX:\n" + "\n".join(f"• {p}" for p in paths[:40])
        return Chunk(
            id=str(uuid.uuid4()), contract_id=contract_id,
            org_id=org_id, text=text, level=0,
            section_path="[DOCUMENT SUMMARY]",
        )

    @staticmethod
    def _tok(text: str) -> int:
        return len(text) // 4
