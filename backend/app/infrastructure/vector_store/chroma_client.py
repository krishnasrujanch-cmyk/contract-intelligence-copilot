"""
ChromaDB client — vector store for clause embeddings.

Architecture:
  - Single persistent ChromaDB client (HTTP mode connecting to Docker service)
  - Two collections: clauses + org_templates
  - Role-based where filters applied at retrieval time (RBAC at data layer)
  - Embeddings generated locally via sentence-transformers (zero API cost)

RBAC enforcement:
  admin    → no filter         (all org clauses)
  reviewer → contract_id filter (assigned contracts only)
  viewer   → chunk_level=0     (document summaries only, no clause text)
"""
from __future__ import annotations

from typing import Any

import chromadb
from chromadb import HttpClient
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ChunkLevel, UserRole

logger = get_logger(__name__)

# ── Module-level client (singleton) ───────────────────────────────────────────
_client:              chromadb.HttpClient | None = None
_clauses_collection:  Any = None
_templates_collection: Any = None


async def initialise_chroma() -> None:
    """
    Connect to the ChromaDB Docker service and initialise collections.
    Called once at application startup via main.py lifespan.
    """
    global _client, _clauses_collection, _templates_collection

    try:
        _client = chromadb.HttpClient(
            host=settings.chromadb_host,
            port=settings.chromadb_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Verify connectivity
        _client.heartbeat()

        # Get or create collections
        _clauses_collection = _client.get_or_create_collection(
            name=settings.chromadb_collection_clauses,
            metadata={"hnsw:space": "cosine"},
        )
        _templates_collection = _client.get_or_create_collection(
            name=settings.chromadb_collection_templates,
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "chromadb_connected",
            host=settings.chromadb_host,
            port=settings.chromadb_port,
            clause_count=_clauses_collection.count(),
        )

    except Exception as exc:
        logger.error("chromadb_init_failed", error=str(exc))
        raise


def get_clauses_collection() -> Any:
    """Return the clauses collection. Raises if not initialised."""
    if _clauses_collection is None:
        raise RuntimeError("ChromaDB not initialised. Call initialise_chroma() first.")
    return _clauses_collection


def build_role_filter(
    role:                  str,
    org_id:                str,
    assigned_contract_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build a ChromaDB where filter enforcing RBAC.

    This is the core security control — role restrictions are applied
    at the data retrieval layer, not in the LLM prompt.
    Prompt injection cannot bypass this filter.

    Args:
        role:                  User's role (admin/reviewer/viewer)
        org_id:                Organisation ID — always scoped
        assigned_contract_ids: Required for reviewer role

    Returns:
        ChromaDB where filter dict
    """
    # All queries are org-scoped — no cross-tenant leakage
    base_filter: dict[str, Any] = {"org_id": {"$eq": org_id}}

    if role == UserRole.ADMIN.value:
        # Admin: full access to all org clauses
        return base_filter

    elif role == UserRole.REVIEWER.value:
        # Reviewer: only assigned contracts
        if not assigned_contract_ids:
            # No assignments — return empty result set safely
            return {**base_filter, "contract_id": {"$eq": "NO_ACCESS"}}
        return {
            "$and": [
                base_filter,
                {"contract_id": {"$in": assigned_contract_ids}},
            ]
        }

    else:
        # Viewer: summary-level chunks only (chunk_level = 0)
        return {
            "$and": [
                base_filter,
                {"chunk_level": {"$eq": ChunkLevel.DOCUMENT.value}},
            ]
        }


def upsert_clause_embeddings(
    clause_ids:  list[str],
    embeddings:  list[list[float]],
    documents:   list[str],
    metadatas:   list[dict[str, Any]],
) -> None:
    """
    Upsert clause embeddings into ChromaDB.
    Uses upsert (not add) — idempotent on reprocessing.
    """
    collection = get_clauses_collection()
    collection.upsert(
        ids=clause_ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    logger.info("clause_embeddings_upserted", count=len(clause_ids))


def query_clauses(
    query_embedding: list[float],
    where_filter:    dict[str, Any],
    n_results:       int = 10,
) -> dict[str, Any]:
    """
    Query the clauses collection with RBAC filter.

    Returns ChromaDB query result dict with:
      documents, metadatas, distances, ids
    """
    collection = get_clauses_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        where=where_filter,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


def delete_contract_embeddings(contract_id: str, org_id: str) -> None:
    """
    Remove all embeddings for a contract from ChromaDB.
    Called when a contract is deleted from the system.
    """
    collection = get_clauses_collection()
    collection.delete(
        where={
            "$and": [
                {"contract_id": {"$eq": contract_id}},
                {"org_id":      {"$eq": org_id}},
            ]
        }
    )
    logger.info("contract_embeddings_deleted", contract_id=contract_id)
