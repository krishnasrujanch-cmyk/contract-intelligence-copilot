"""
Phase 4 — RAG Pipeline.

Architecture (Senior Architect perspective):
  Four single-responsibility classes following SRP/SOLID:

  LegalChunker     → splits contract text on ARTICLE/SECTION boundaries
                     tables atomic, 150-token overlap, Level 0 summary chunk

  ChunkEmbedder    → embeds chunks via local sentence-transformers,
                     upserts to ChromaDB (idempotent)

  RoleFilter       → builds ChromaDB where-filter enforcing RBAC
                     at the data layer — injection-proof

  AnswerSynthesiser → retrieves role-scoped chunks, calls Groq Answerer,
                      returns cited answer

  RAGPipeline      → Facade orchestrating all four (index + answer)

Security:
  - RBAC enforced at ChromaDB retrieval — data never enters LLM context
    if the user's role prohibits it (viewer gets level=0 summaries only)
  - PII must be masked before calling index_contract()
  - API keys sourced from environment only — never from arguments
  - Citations mandatory — LLM instructed to refuse if context insufficient

SOLID compliance:
  - SRP: each class has exactly one reason to change
  - OCP: new roles added in RoleFilter.build() only — no other changes
  - DIP: RAGPipeline depends on abstractions (injectable in tests)
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from app.core.logging import get_logger
from app.infrastructure.chunking import Chunk, LegalChunker

logger = get_logger(__name__)

_CHROMA_PATH = "/workspaces/contract-intelligence-copilot/backend/chroma_data"

# ── Embedding model singleton (lazy-loaded) ───────────────────────────────────
_embed_model = None


def _get_embed_model():
    """
    Lazy singleton for the embedding model.
    First call takes ~5s to load weights; subsequent calls are instant.
    Thread-safe in CPython due to GIL on the assignment.
    """
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("embedding_model_loaded", model="all-MiniLM-L6-v2", dims=384)
    return _embed_model


# ── ChromaDB collection singleton (lazy-loaded) ───────────────────────────────
_chroma_client = None
_clauses_col   = None


def _get_collection():
    """
    Lazy singleton for the ChromaDB collection.
    PersistentClient stores data to disk — survives process restarts.
    """
    global _chroma_client, _clauses_col
    if _clauses_col is None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        _chroma_client = chromadb.PersistentClient(
            path=_CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _clauses_col = _chroma_client.get_or_create_collection(
            name="clm_clauses",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("chromadb_ready", path=_CHROMA_PATH, count=_clauses_col.count())
    return _clauses_col


# ── RBAC filter ───────────────────────────────────────────────────────────────

class RoleFilter:
    """
    Builds ChromaDB where-filters enforcing role-based access control.

    Security guarantee: filters applied at the vector store layer —
    before any data enters the LLM context window. A prompt injection
    attack cannot escalate a viewer to admin because the restricted
    chunks never leave ChromaDB.

    Role semantics:
      admin    → all org chunks unrestricted
      reviewer → assigned contracts only
      viewer   → level=0 summary chunks only (no clause text)
    """

    @staticmethod
    def build(
        role: str,
        org_id: str,
        assigned_contract_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {"org_id": {"$eq": org_id}}

        if role == "admin":
            return base

        if role == "reviewer":
            if not assigned_contract_ids:
                # Reviewer with no assignments gets nothing — fail-safe
                return {**base, "contract_id": {"$eq": "__NO_ACCESS__"}}
            return {
                "$and": [
                    base,
                    {"contract_id": {"$in": assigned_contract_ids}},
                ]
            }

        # viewer — level 0 document summaries only
        return {
            "$and": [
                base,
                {"level": {"$eq": 0}},
            ]
        }


# ── Chunk embedder ────────────────────────────────────────────────────────────

class ChunkEmbedder:
    """
    Embeds and upserts chunks into ChromaDB.

    Upsert semantics: safe to reprocess the same contract —
    existing vectors are updated, not duplicated.

    Batch size of 32 prevents OOM on the free Codespace (2GB RAM).
    """

    def embed_and_store(
        self,
        chunks: list[Chunk],
        contract_id: str,
        org_id: str,
        clause_types: dict[str, str] | None = None,
    ) -> int:
        if not chunks:
            return 0

        model      = _get_embed_model()
        collection = _get_collection()
        texts      = [c.text for c in chunks]

        # Batch embedding — show_progress_bar=False for clean logs
        embeddings = model.encode(
            texts, batch_size=32, show_progress_bar=False
        ).tolist()

        metadatas = []
        for c in chunks:
            metadatas.append({
                "contract_id":  contract_id,
                "org_id":       org_id,
                "level":        c.level,
                "section_path": c.section_path,
                "clause_type":  (clause_types or {}).get(c.id, "unknown"),
                "char_count":   len(c.text),
            })

        collection.upsert(
            ids=       [c.id for c in chunks],
            embeddings=embeddings,
            documents= texts,
            metadatas= metadatas,
        )

        logger.info("chunks_embedded", contract_id=contract_id, count=len(chunks))
        return len(chunks)


# ── RAG Retriever ─────────────────────────────────────────────────────────────

class RAGRetriever:
    """
    Retrieves role-scoped chunks relevant to a user query.

    Returns chunks with metadata for citation generation.
    Relevance score = 1.0 - cosine_distance (higher = more relevant).
    """

    def retrieve(
        self,
        query: str,
        role: str,
        org_id: str,
        assigned_contract_ids: list[str] | None = None,
        n_results: int = 6,
        contract_id: str | None = None,
    ) -> list[dict[str, Any]]:
        model      = _get_embed_model()
        collection = _get_collection()

        if collection.count() == 0:
            logger.warning("chromadb_empty_no_contracts_indexed")
            return []

        query_vec    = model.encode([query])[0].tolist()
        where_filter = RoleFilter.build(role, org_id, assigned_contract_ids)

        # Scope to specific contract if provided — prevents cross-contract collision
        if contract_id:
            if "$and" in where_filter:
                where_filter["$and"].append({"contract_id": {"$eq": contract_id}})
            else:
                where_filter = {"$and": [where_filter, {"contract_id": {"$eq": contract_id}}]}

        n = min(n_results, collection.count())

        results   = collection.query(
            query_embeddings=[query_vec],
            where=where_filter,
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        docs      = (results.get("documents") or [[]])[0]
        metas     = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        retrieved = [
            {
                "text":      doc,
                "metadata":  meta,
                "relevance": round(1.0 - dist, 3),
            }
            for doc, meta, dist in zip(docs, metas, distances)
        ]

        logger.info("rag_retrieved", role=role, returned=len(retrieved))
        return retrieved


# ── Answer Synthesiser ────────────────────────────────────────────────────────

class AnswerSynthesiser:
    """
    Synthesises a cited answer from retrieved chunks using Groq Answerer LLM.

    Citation format: [N] references the numbered context chunks.
    Viewer role receives an additional instruction to paraphrase only —
    never quote clause text verbatim (RBAC output restriction).

    Fails gracefully when no chunks are retrieved or LLM key is missing.
    """

    _SYSTEM_BASE = """You are a legal contract analysis assistant in READ-ONLY mode.
Answer questions based ONLY on the numbered contract context below.

Rules you must ALWAYS follow:
1. Cite sources using [N] notation matching the context numbers.
2. If the answer is not in the context, say exactly:
   "This information is not found in the provided contract clauses."
3. Never suggest modifying any contract term.
4. Never provide legal advice — factual clause summaries only.
5. Keep answers concise, professional, and accurate.
6. Address the user by their role context when relevant."""

    _VIEWER_ADDENDUM = """
6. VIEWER ACCESS RESTRICTION: Paraphrase all content — do not quote
   clause text verbatim. Provide high-level summaries only."""

    def synthesise(
        self,
        query:  str,
        chunks: list[dict[str, Any]],
        role:   str,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        if not chunks:
            return {
                "answer":     "No relevant contract clauses found. "
                              "Please upload a contract first or refine your question.",
                "citations":  [],
                "confidence": 0.0,
            }

        # Build numbered context block
        context_lines = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            section = meta.get("section_path", "Unknown")
            ctype   = meta.get("clause_type", "unknown")
            rel     = chunk["relevance"]
            text    = chunk["text"][:800]
            context_lines.append(
                f"[{i}] Section: {section} | Type: {ctype} | Relevance: {rel:.2f}\n"
                f"     Text: {text}"
            )
        context = "\n\n".join(context_lines)

        role_context = {
            "admin":    "You are assisting an administrator with full contract access.",
            "reviewer": "You are assisting a legal reviewer validating contract risk scores.",
            "viewer":   "You are assisting a stakeholder with summary-level contract access.",
        }.get(role, "")

        system_prompt = self._SYSTEM_BASE + f"\n\nUser context: {role_context}"
        if user_name:
            system_prompt += f" User: {user_name}."
        if role == "viewer":
            system_prompt += self._VIEWER_ADDENDUM

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            return {
                "answer":     "LLM not configured — GROQ_API_KEY missing.",
                "citations":  [],
                "confidence": 0.0,
            }

        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=groq_key,
                max_tokens=1024,
                temperature=0.1,
            )
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"CONTEXT:\n{context}\n\nQUESTION: {query}"),
            ])
            answer = response.content if hasattr(response, "content") else str(response)

        except Exception as exc:
            logger.error("answer_synthesis_failed", error=str(exc))
            answer = f"Answer generation failed: {exc}"

        citations = [
            {
                "index":        i + 1,
                "section_path": c["metadata"].get("section_path", ""),
                "clause_type":  c["metadata"].get("clause_type", ""),
                "relevance":    c["relevance"],
            }
            for i, c in enumerate(chunks)
        ]
        avg_relevance = sum(c["relevance"] for c in chunks) / len(chunks)

        # Deanonymize PII tokens in the answer before returning
        try:
            from app.infrastructure.pii.presidio_engine import deanonymize_text
            answer = deanonymize_text(answer)
        except Exception:
            pass  # If deanonymization fails, return masked answer

        return {
            "answer":     answer,
            "citations":  citations,
            "confidence": round(avg_relevance, 3),
        }


# ── RAG Pipeline facade ───────────────────────────────────────────────────────

class RAGPipeline:
    """
    Facade over the four RAG components.

    Usage:
        pipeline = RAGPipeline()

        # After document upload + PII masking:
        n_chunks = pipeline.index_contract(masked_text, contract_id, org_id)

        # On chat query:
        result = pipeline.answer(query, role, org_id, assigned_ids)
        # result = {"answer": "...", "citations": [...], "confidence": 0.87}

    Thread safety: all state is in ChromaDB (disk) and the embedding
    model (read-only after loading). Safe for concurrent FastAPI requests.
    """

    def __init__(self) -> None:
        self._chunker     = LegalChunker()
        self._embedder    = ChunkEmbedder()
        self._retriever   = RAGRetriever()
        self._synthesiser = AnswerSynthesiser()

    def index_contract(
        self,
        masked_text:  str,
        contract_id:  str,
        org_id:       str,
        clause_types: dict[str, str] | None = None,
    ) -> int:
        """Chunk, embed, and store a contract. Call AFTER PII masking."""
        chunks = self._chunker.chunk(masked_text, contract_id, org_id)
        n      = self._embedder.embed_and_store(chunks, contract_id, org_id, clause_types)
        logger.info("contract_indexed", contract_id=contract_id, chunks=n)
        return n

    def answer(
        self,
        query:                 str,
        role:                  str,
        org_id:                str,
        assigned_contract_ids: list[str] | None = None,
        n_results:             int = 6,
        contract_id:           str | None = None,
    ) -> dict[str, Any]:
        """Retrieve role-scoped chunks and synthesise a cited answer.
        If contract_id is set, scopes retrieval to that contract only.
        """
        chunks = self._retriever.retrieve(
            query=query,
            role=role,
            org_id=org_id,
            assigned_contract_ids=assigned_contract_ids,
            n_results=n_results,
            contract_id=contract_id,
        )
        return self._synthesiser.synthesise(query, chunks, role)

    def delete_contract(self, contract_id: str, org_id: str) -> None:
        """Remove all vectors for a contract on deletion."""
        col = _get_collection()
        col.delete(where={
            "$and": [
                {"contract_id": {"$eq": contract_id}},
                {"org_id":      {"$eq": org_id}},
            ]
        })
        logger.info("contract_vectors_deleted", contract_id=contract_id)
