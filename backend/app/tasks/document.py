"""
Celery task: process_contract_task
Triggered by POST /contracts/upload.
Runs the full parser → PII mask → chunk → embed → pipeline flow.
"""
from __future__ import annotations
import asyncio
from app.tasks import worker
from app.core.logging import get_logger

logger = get_logger(__name__)

@worker.task(
    name="app.tasks.document.process_contract_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="document_processing",
    acks_late=True,
)
def process_contract_task(self, contract_id: str, org_id: str) -> dict:
    """
    Full document processing pipeline (synchronous Celery wrapper around async code).

    Steps:
      1. Load file bytes from storage
      2. Detect file type + parse (PDFParser / ScannedPDFParser / DOCXParser)
      3. PII masking via Presidio
      4. Legal chunking
      5. Embedding via sentence-transformers
      6. Upsert to ChromaDB
      7. Run LangGraph pipeline (Safety → Extractor → Reasoner → Judge → Answerer)
      8. Persist clauses + obligations to PostgreSQL
      9. Update contract status → ANALYZED
    """
    try:
        result = asyncio.run(_run_pipeline(contract_id, org_id))
        return result
    except Exception as exc:
        logger.error("document_task_failed", contract_id=contract_id, error=str(exc))
        asyncio.run(_mark_failed(contract_id, str(exc)))
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))


async def _run_pipeline(contract_id: str, org_id: str) -> dict:
    """Async implementation of the full processing pipeline."""
    from pathlib import Path
    from sqlalchemy import select, update

    from app.agents.pipeline import PipelineState, build_document_pipeline
    from app.core.config import settings
    from app.domain.enums import ContractStatus
    from app.domain.models import Clause, Contract, Obligation
    from app.infrastructure.chunking import LegalChunker
    from app.infrastructure.database.session import AsyncSessionLocal
    from app.infrastructure.parsers import ParserFactory
    from app.infrastructure.pii.presidio_engine import anonymize_text, initialise_pii_engine
    from app.infrastructure.vector_store.chroma_client import initialise_chroma, upsert_clause_embeddings

    import uuid as _uuid

    await initialise_pii_engine()
    await initialise_chroma()

    async with AsyncSessionLocal() as db:
        # Load contract record
        result = await db.execute(
            select(Contract).where(
                Contract.id == _uuid.UUID(contract_id),
                Contract.org_id == _uuid.UUID(org_id),
            )
        )
        contract = result.scalar_one_or_none()
        if not contract:
            raise ValueError(f"Contract {contract_id} not found")

        file_bytes = Path(contract.file_path).read_bytes()

        # Parse
        parser = ParserFactory.get_parser(file_bytes)
        parse_result = parser.parse(file_bytes, contract.original_filename)

        # PII mask
        masked_text, mask_map = anonymize_text(parse_result.text, session_id=contract_id)

        # Chunk
        chunker = LegalChunker()
        chunks  = chunker.chunk(masked_text, contract_id, org_id, parse_result.tables)

        # Embed
        from sentence_transformers import SentenceTransformer
        embed_model = SentenceTransformer(settings.embedding_model)
        embeddings  = embed_model.encode([c.text for c in chunks]).tolist()

        # Upsert to ChromaDB
        upsert_clause_embeddings(
            clause_ids  =[c.id for c in chunks],
            embeddings  =embeddings,
            documents   =[c.text for c in chunks],
            metadatas   =[{
                "contract_id":  contract_id,
                "org_id":       org_id,
                "chunk_level":  c.chunk_level.value,
                "section_path": c.section_path,
                "is_table":     c.is_table,
            } for c in chunks],
        )

        # Run LangGraph pipeline
        pipeline = build_document_pipeline()
        state: PipelineState = {
            "contract_id":     contract_id,
            "org_id":          org_id,
            "content_stream":  masked_text,
            "effective_date":  contract.effective_date.isoformat() if contract.effective_date else "",
            "metadata":        {},
            "safety_verdict":  "",
            "safety_reason":   "",
            "extracted_clauses": [],
            "risk_assessments":  [],
            "judge_verdict":   "",
            "judge_feedback":  "",
            "judge_retry_count": 0,
            "final_clauses":   [],
            "obligations":     [],
            "pipeline_errors": [],
            "trace_id":        contract_id,
        }
        final_state = await pipeline.ainvoke(state)

        # Persist clauses
        for clause_data in final_state.get("final_clauses", []):
            clause = Clause(
                contract_id=_uuid.UUID(contract_id),
                org_id=_uuid.UUID(org_id),
                clause_type=clause_data.get("clause_type", "other"),
                title=clause_data.get("title"),
                raw_text=clause_data.get("raw_text", ""),
                summary=clause_data.get("summary"),
                page_number=clause_data.get("page_start"),
                risk_score=clause_data.get("risk_score"),
                risk_level=clause_data.get("risk_level"),
                risk_reason=clause_data.get("risk_reason"),
                extraction_confidence=clause_data.get("confidence"),
                flagged_for_review=clause_data.get("flagged_for_review", False),
                extracted_data=clause_data.get("extracted_data", {}),
            )
            db.add(clause)

        # Persist obligations
        for obl_data in final_state.get("obligations", []):
            from datetime import date
            obl = Obligation(
                contract_id=_uuid.UUID(contract_id),
                org_id=_uuid.UUID(org_id),
                title=obl_data.get("title", ""),
                description=obl_data.get("description"),
                party=obl_data.get("party", "both"),
                status="pending",
            )
            if due := obl_data.get("due_date"):
                try:
                    obl.due_date = date.fromisoformat(due)
                except ValueError:
                    pass
            db.add(obl)

        # Update contract record
        await db.execute(
            update(Contract)
            .where(Contract.id == _uuid.UUID(contract_id))
            .values(
                status=ContractStatus.ANALYZED.value,
                page_count=parse_result.page_count,
                has_images=parse_result.has_images,
                has_tables=parse_result.has_tables,
                ocr_confidence=parse_result.ocr_confidence,
                file_type=parse_result.file_type,
            )
        )
        await db.commit()

    logger.info("document_pipeline_complete", contract_id=contract_id)
    return {"status": "analyzed", "contract_id": contract_id}


async def _mark_failed(contract_id: str, error: str) -> None:
    from sqlalchemy import update
    import uuid as _uuid
    from app.domain.models import Contract
    from app.domain.enums import ContractStatus
    from app.infrastructure.database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == _uuid.UUID(contract_id))
            .values(status=ContractStatus.FAILED.value, error_message=error[:500])
        )
        await db.commit()
