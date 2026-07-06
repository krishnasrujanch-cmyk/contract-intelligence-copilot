"""
ChromaDB client — embedded persistent mode (no separate server needed).

Embedded mode: ChromaDB runs in-process, stores data to disk.
Production upgrade path: switch to HttpClient pointing to dedicated ChromaDB container.

RBAC enforcement:
  admin    → no filter         (all org clauses)
  reviewer → contract_id filter (assigned contracts only)
  viewer   → chunk_level=0     (document summaries only)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.enums import ChunkLevel, UserRole

logger = get_logger(__name__)

# ── Module-level singletons ───────────────────────────────────────────────────
_client:               chromadb.ClientAPI | None = None
_clauses_collection:   Any = None
_templates_collection: Any = None

# Persistent storage path inside the container / workspace
_CHROMA_PATH = Path("/workspaces/contract-intelligence-copilot/backend/chroma_data")


async def initialise_chroma() -> None:
    """
    Initialise embedded ChromaDB client.
    Called once at FastAPI startup via lifespan.
    """
    global _client, _clauses_collection, _templates_collection

    try:
        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)

        _client = chromadb.PersistentClient(
            path=str(_CHROMA_PATH),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        _clauses_collection = _client.get_or_create_collection(
            name=settings.chromadb_collection_clauses,
            metadata={"hnsw:space": "cosine"},
        )
        _templates_collection = _client.get_or_create_collection(
            name=settings.chromadb_collection_templates,
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "chromadb_embedded_initialised",
            path=str(_CHROMA_PATH),
            clause_count=_clauses_collection.count(),
        )

    except Exception as exc:
        logger.error("chromadb_init_failed", error=str(exc))
        raise


def get_clauses_collection() -> Any:
    if _clauses_collection is None:
        raise RuntimeError("ChromaDB not initialised. Call initialise_chroma() first.")
    return _clauses_collection


def build_role_filter(
    role:                  str,
    org_id:                str,
    assigned_contract_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build ChromaDB where filter enforcing RBAC at data layer.
    Role restrictions applied before LLM sees any data — injection-proof.
    """
    base: dict[str, Any] = {"org_id": {"$eq": org_id}}

    if role == UserRole.ADMIN.value:
        return base

    elif role == UserRole.REVIEWER.value:
        if not assigned_contract_ids:
            return {**base, "contract_id": {"$eq": "NO_ACCESS"}}
        return {
            "$and": [
                base,
                {"contract_id": {"$in": assigned_contract_ids}},
            ]
        }

    else:  # viewer
        return {
            "$and": [
                base,
                {"chunk_level": {"$eq": ChunkLevel.DOCUMENT.value}},
            ]
        }


def upsert_clause_embeddings(
    clause_ids: list[str],
    embeddings: list[list[float]],
    documents:  list[str],
    metadatas:  list[dict[str, Any]],
) -> None:
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
    collection = get_clauses_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        where=where_filter,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


def delete_contract_embeddings(contract_id: str, org_id: str) -> None:
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
