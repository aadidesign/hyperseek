import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.embedding import DocumentEmbedding
from app.services.indexer.vector_indexer import generate_single_embedding

logger = logging.getLogger("hyperseek.search.semantic")


@dataclass
class SemanticResult:
    document_id: str
    score: float
    title: str
    url: str
    source: str
    snippet: str


async def semantic_search(
    query: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 10,
) -> tuple[list[SemanticResult], int]:
    """Vector similarity search using pgvector cosine distance.

    1. Embed the query text
    2. Find nearest neighbors in document_embeddings
    3. Deduplicate by document (take best chunk per doc)
    4. Return ranked results
    """
    # Generate query embedding
    try:
        query_embedding = generate_single_embedding(query)
    except Exception as e:
        logger.error("Failed to generate query embedding: %s", e)
        return [], 0

    # Convert to pgvector format
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Query pgvector for nearest neighbors
    # We fetch more than needed because we'll deduplicate by document
    fetch_limit = size * 5  # Fetch 5x to account for multiple chunks per doc

    # Use raw SQL for pgvector cosine similarity
    # 1 - cosine_distance gives similarity (higher = more similar)
    sql = text("""
        SELECT
            de.document_id,
            de.chunk_text,
            1 - (de.embedding <=> :query_embedding::vector) as similarity
        FROM document_embeddings de
        WHERE de.embedding IS NOT NULL
        ORDER BY de.embedding <=> :query_embedding::vector
        LIMIT :fetch_limit
    """)

    result = await db.execute(
        sql,
        {"query_embedding": embedding_str, "fetch_limit": fetch_limit},
    )
    rows = result.all()

    if not rows:
        return [], 0

    # Deduplicate: keep best chunk per document
    best_per_doc: dict[str, dict] = {}
    for row in rows:
        doc_id = str(row.document_id)
        similarity = float(row.similarity)
        if doc_id not in best_per_doc or similarity > best_per_doc[doc_id]["score"]:
            best_per_doc[doc_id] = {
                "score": similarity,
                "snippet": row.chunk_text[:250] + "..." if len(row.chunk_text) > 250 else row.chunk_text,
            }

    # Sort by score
    sorted_docs = sorted(best_per_doc.items(), key=lambda x: x[1]["score"], reverse=True)
    total = len(sorted_docs)

    # Paginate
    offset = (page - 1) * size
    page_docs = sorted_docs[offset : offset + size]

    if not page_docs:
        return [], total

    # Fetch document details
    doc_ids = [doc_id for doc_id, _ in page_docs]
    doc_result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
    docs_by_id = {str(d.id): d for d in doc_result.scalars().all()}

    results = []
    for doc_id, data in page_docs:
        doc = docs_by_id.get(doc_id)
        if not doc:
            continue
        results.append(
            SemanticResult(
                document_id=doc_id,
                score=round(data["score"], 4),
                title=doc.title or "",
                url=doc.url,
                source=doc.source,
                snippet=data["snippet"],
            )
        )

    return results, total
