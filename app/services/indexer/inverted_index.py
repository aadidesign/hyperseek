import logging
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.index import CollectionStats, DocumentStats, InvertedIndex
from app.services.indexer.text_processor import TextProcessor

logger = logging.getLogger("hyperseek.indexer.inverted_index")

text_processor = TextProcessor()


async def index_document(doc_id: str, db: AsyncSession) -> None:
    """Build inverted index entries for a single document.

    Steps:
    1. Load document content
    2. Process text (tokenize, stem, remove stopwords)
    3. Calculate term frequencies and positions
    4. Upsert into inverted_index table
    5. Update document_stats
    6. Update collection_stats
    7. Mark document as indexed
    """
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        logger.warning("Document %s not found for indexing", doc_id)
        return
    if not doc.clean_content:
        logger.warning("Document %s has no clean content", doc_id)
        return

    # Process text with positions
    token_positions = text_processor.process_with_positions(doc.clean_content)
    if not token_positions:
        logger.warning("Document %s produced no tokens", doc_id)
        return

    # Calculate term frequencies and positions
    term_data: dict[str, dict] = {}
    for token, pos in token_positions:
        if token not in term_data:
            term_data[token] = {"frequency": 0, "positions": []}
        term_data[token]["frequency"] += 1
        term_data[token]["positions"].append(pos)

    total_terms = len(token_positions)
    unique_terms = len(term_data)

    # Delete existing index entries for this document (for reindexing)
    await db.execute(
        delete(InvertedIndex).where(InvertedIndex.document_id == doc_id)
    )

    # Batch insert inverted index entries
    entries = []
    for term, data in term_data.items():
        entries.append(
            {
                "term": term,
                "document_id": doc_id,
                "term_frequency": data["frequency"],
                "positions": data["positions"],
            }
        )

    if entries:
        # Use PostgreSQL upsert for idempotency
        stmt = pg_insert(InvertedIndex).values(entries)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_term_document",
            set_={
                "term_frequency": stmt.excluded.term_frequency,
                "positions": stmt.excluded.positions,
            },
        )
        await db.execute(stmt)

    # Upsert document stats
    stats_stmt = pg_insert(DocumentStats).values(
        document_id=doc_id,
        total_terms=total_terms,
        unique_terms=unique_terms,
    )
    stats_stmt = stats_stmt.on_conflict_do_update(
        index_elements=["document_id"],
        set_={
            "total_terms": total_terms,
            "unique_terms": unique_terms,
        },
    )
    await db.execute(stats_stmt)

    # Mark document as indexed
    await db.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(indexed_at=datetime.now(timezone.utc))
    )

    await db.commit()

    logger.info(
        "Indexed document %s: %d unique terms, %d total tokens",
        doc_id,
        unique_terms,
        total_terms,
    )


async def update_collection_stats(db: AsyncSession) -> None:
    """Recalculate collection-level statistics for BM25.

    Called after indexing a batch of documents.
    """
    # Count total indexed documents
    total_result = await db.execute(select(func.count(DocumentStats.document_id)))
    total_docs = total_result.scalar() or 0

    # Calculate average document length
    avg_result = await db.execute(select(func.avg(DocumentStats.total_terms)))
    avg_length = avg_result.scalar() or 0.0

    # Upsert collection stats
    stmt = pg_insert(CollectionStats).values(
        id=1,
        total_documents=total_docs,
        avg_document_length=float(avg_length),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "total_documents": total_docs,
            "avg_document_length": float(avg_length),
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(
        "Collection stats updated: %d docs, avg length=%.1f",
        total_docs,
        avg_length,
    )
