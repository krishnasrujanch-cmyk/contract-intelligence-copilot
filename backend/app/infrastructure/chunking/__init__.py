"""
Legal-aware hierarchical document chunker.

Design:
  Standard chunkers split on token count — fatal for legal contracts:
  a liability clause spanning 4 pages gets split mid-sentence and
  the LLM sees an incomplete clause without its subject.

  This chunker respects legal document structure:
    Level 0 → Document summary (viewer-accessible)
    Level 1 → Article / major section group
    Level 2 → Individual clause (primary retrieval unit)
    Level 3 → Sub-clause (precision queries)

  Tables are ALWAYS atomic — never split.
  150-token sibling overlap handles "the foregoing", "as defined above".

SOLID: ChunkingStrategy protocol → LegalChunker implements it.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ChunkLevel

logger = get_logger(__name__)


# ── Domain types ───────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    """A single addressable unit of contract content."""
    id:           str                  # Stable UUID — used as ChromaDB vector ID
    contract_id:  str
    org_id:       str
    text:         str                  # The actual content (clause text or summary)
    chunk_level:  ChunkLevel
    page_start:   int | None
    page_end:     int | None
    section_path: str                  # e.g. "ARTICLE 12 > Section 12.1 > (a)"
    metadata:     dict[str, Any] = field(default_factory=dict)
    is_table:     bool = False

    @property
    def token_estimate(self) -> int:
        """Rough token count: ~4 chars per token for English legal text."""
        return len(self.text) // 4


# ── Article/Section boundary patterns ────────────────────────────────────────

_ARTICLE_PATTERNS = [
    re.compile(r"^\s*ARTICLE\s+[IVXLC\d]+[\s.:–\-]", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*SECTION\s+\d+[\s.:–\-]", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*\d+\.\s+[A-Z][A-Z\s]{4,}", re.MULTILINE),  # "12. INDEMNIFICATION"
]

_SUBSECTION_PATTERNS = [
    re.compile(r"^\s*\d+\.\d+[\s.:–\-]", re.MULTILINE),         # "12.1 ..."
    re.compile(r"^\s*\([a-z]\)\s", re.MULTILINE),                # "(a) ..."
    re.compile(r"^\s*\([ivxlc]+\)\s", re.MULTILINE | re.IGNORECASE),  # "(i) ..."
]

_TABLE_MARKER = "__TABLE_BLOCK__"


# ── Chunking strategy protocol ────────────────────────────────────────────────

class ChunkingStrategy(Protocol):
    def chunk(
        self,
        text:        str,
        contract_id: str,
        org_id:      str,
        tables:      list[dict[str, Any]],
    ) -> list[Chunk]:
        ...


# ── Legal Chunker ─────────────────────────────────────────────────────────────

class LegalChunker:
    """
    Hierarchical legal document chunker.

    Strategy:
      1. Inject table placeholders into text (tables are atomic)
      2. Detect article/section boundaries using legal patterns
      3. Assign chunk levels based on nesting depth
      4. Generate 150-token overlap strips between siblings
      5. Produce Level 0 document summary chunk for viewer access
    """

    def __init__(
        self,
        max_tokens:     int = settings.chunk_max_tokens,
        overlap_tokens: int = settings.chunk_overlap_tokens,
    ) -> None:
        self._max_tokens     = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(
        self,
        text:        str,
        contract_id: str,
        org_id:      str,
        tables:      list[dict[str, Any]] | None = None,
    ) -> list[Chunk]:
        """
        Entry point: produce all chunks for a document.

        Args:
            text:        Full document text (PII already masked)
            contract_id: UUID string
            org_id:      UUID string
            tables:      List of docling table dicts (atomic JSON blocks)

        Returns:
            Ordered list of Chunk objects ready for embedding + DB storage
        """
        tables = tables or []
        chunks: list[Chunk] = []

        # Step 1: inject table placeholders
        text_with_placeholders, table_map = self._inject_table_placeholders(
            text, tables
        )

        # Step 2: detect boundaries and split into sections
        sections = self._split_into_sections(text_with_placeholders)

        # Step 3: produce chunks per section, restore tables
        for section in sections:
            section_chunks = self._process_section(
                section, contract_id, org_id, table_map
            )
            chunks.extend(section_chunks)

        # Step 4: add document-level summary chunk (Level 0 — viewer accessible)
        summary_chunk = self._build_summary_chunk(chunks, contract_id, org_id)
        chunks.insert(0, summary_chunk)

        logger.info(
            "chunking_complete",
            contract_id=contract_id,
            total_chunks=len(chunks),
            table_count=len(tables),
            level_counts={
                lvl.name: sum(1 for c in chunks if c.chunk_level == lvl)
                for lvl in ChunkLevel
            },
        )

        return chunks

    # ── Private helpers ────────────────────────────────────────────────────────

    def _inject_table_placeholders(
        self,
        text:   str,
        tables: list[dict[str, Any]],
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        """
        Replace table text blocks with stable placeholder strings.
        Tables are restored as atomic JSON blocks after chunking.
        """
        table_map: dict[str, dict[str, Any]] = {}
        result = text

        for i, table in enumerate(tables):
            placeholder = f"{_TABLE_MARKER}_{i}"
            table_map[placeholder] = table
            # Replace the table's raw text (if present) with placeholder
            if raw := table.get("raw_text", ""):
                result = result.replace(raw, f"\n{placeholder}\n", 1)

        return result, table_map

    def _split_into_sections(self, text: str) -> list[dict[str, Any]]:
        """
        Identify article/section boundaries and return section dicts.
        Each section carries its nesting level and header text.
        """
        lines  = text.split("\n")
        sections: list[dict[str, Any]] = []
        current: list[str] = []
        current_level = ChunkLevel.CLAUSE
        current_header = ""

        for line in lines:
            level = self._detect_level(line)
            if level is not None and current:
                # Save current accumulated section
                sections.append({
                    "text":   "\n".join(current),
                    "level":  current_level,
                    "header": current_header,
                })
                current = []
                current_level  = level
                current_header = line.strip()

            current.append(line)

        if current:
            sections.append({
                "text":   "\n".join(current),
                "level":  current_level,
                "header": current_header,
            })

        return sections

    def _detect_level(self, line: str) -> ChunkLevel | None:
        """Return chunk level if the line is a section boundary, else None."""
        for pattern in _ARTICLE_PATTERNS:
            if pattern.match(line):
                return ChunkLevel.ARTICLE
        for pattern in _SUBSECTION_PATTERNS:
            if pattern.match(line):
                return ChunkLevel.CLAUSE
        return None

    def _process_section(
        self,
        section:    dict[str, Any],
        contract_id: str,
        org_id:     str,
        table_map:  dict[str, dict[str, Any]],
    ) -> list[Chunk]:
        """Produce one or more chunks from a section, handling overflow."""
        text:  str        = section["text"]
        level: ChunkLevel = section["level"]
        header: str       = section["header"]
        chunks: list[Chunk] = []

        # Tables embedded in section → restore as atomic table chunk
        for placeholder, table_data in table_map.items():
            if placeholder in text:
                table_chunk = Chunk(
                    id=str(uuid.uuid4()),
                    contract_id=contract_id,
                    org_id=org_id,
                    text=str(table_data),
                    chunk_level=level,
                    page_start=table_data.get("page"),
                    page_end=table_data.get("page"),
                    section_path=header,
                    metadata={"type": "table", "table_index": table_data.get("index")},
                    is_table=True,
                )
                chunks.append(table_chunk)
                text = text.replace(placeholder, "").strip()

        if not text.strip():
            return chunks

        # Split oversized sections into overlapping sub-chunks
        if self._estimate_tokens(text) > self._max_tokens:
            sub_chunks = self._split_with_overlap(text, header, contract_id, org_id, level)
            chunks.extend(sub_chunks)
        else:
            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                contract_id=contract_id,
                org_id=org_id,
                text=text.strip(),
                chunk_level=level,
                page_start=None,
                page_end=None,
                section_path=header,
                metadata={},
            ))

        return chunks

    def _split_with_overlap(
        self,
        text:        str,
        header:      str,
        contract_id: str,
        org_id:      str,
        level:       ChunkLevel,
    ) -> list[Chunk]:
        """
        Split oversized text into overlapping windows.
        Each chunk gets a 150-token prefix from the previous chunk
        to preserve references like "the foregoing" and "as defined above".
        """
        words  = text.split()
        chunks: list[Chunk] = []
        step   = self._max_tokens * 4  # chars per step (4 chars/token estimate)
        overlap_chars = self._overlap_tokens * 4
        start  = 0
        text_bytes = text

        while start < len(text_bytes):
            end  = min(start + step, len(text_bytes))
            chunk_text = text_bytes[start:end]

            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                contract_id=contract_id,
                org_id=org_id,
                text=chunk_text.strip(),
                chunk_level=level,
                page_start=None,
                page_end=None,
                section_path=f"{header} (part {len(chunks)+1})",
                metadata={"is_continuation": start > 0},
            ))

            if end >= len(text_bytes):
                break
            start = end - overlap_chars  # overlap

        return chunks

    def _build_summary_chunk(
        self,
        all_chunks:  list[Chunk],
        contract_id: str,
        org_id:      str,
    ) -> Chunk:
        """
        Produce a Level 0 (document-level) summary chunk.
        This is the ONLY level viewers can retrieve via ChromaDB filter.
        Content: headers of all sections joined — enough for viewer queries.
        """
        headers = [
            c.section_path for c in all_chunks
            if c.section_path and c.chunk_level in (ChunkLevel.ARTICLE, ChunkLevel.CLAUSE)
        ]
        summary_text = (
            "Document summary — section index:\n"
            + "\n".join(f"• {h}" for h in headers[:50])  # cap at 50 headers
        )
        return Chunk(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            org_id=org_id,
            text=summary_text,
            chunk_level=ChunkLevel.DOCUMENT,
            page_start=None,
            page_end=None,
            section_path="[DOCUMENT SUMMARY]",
            metadata={"chunk_count": len(all_chunks)},
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return len(text) // 4
