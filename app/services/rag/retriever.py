import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.embedding import DocumentEmbedding
from app.services.indexer.vector_indexer import generate_single_embedding
from app.services.search.bm25 import bm25_search

logger = logging.getLogger("hyperseek.rag.retriever")


@dataclass
class RetrievedContext:
    """A chunk of text retrieved for RAG context."""

    document_id: str
    chunk_text: str
    title: str
    url: str
    source: str
    relevance_score: float


async def retrieve_context(
    query: str,
    db: AsyncSession,
    top_k: int = 5,
    method: str = "hybrid",
) -> list[RetrievedContext]:
    """Retrieve the most relevant text chunks for RAG context.

    Uses a combination of BM25 (for keyword relevance) and semantic search
    (for meaning-based relevance) to find the best context chunks.

    Returns ordered list of context chunks, most relevant first.
    """
    contexts: list[RetrievedContext] = []

    if method in ("semantic", "hybrid"):
        semantic_contexts = await _retrieve_semantic(query, db, top_k)
        contexts.extend(semantic_contexts)

    if method in ("bm25", "hybrid"):
        bm25_contexts = await _retrieve_bm25(query, db, top_k)
        # Merge BM25 results, avoiding duplicates
        seen_docs = {c.document_id for c in contexts}
        for ctx in bm25_contexts:
            if ctx.document_id not in seen_docs:
                contexts.append(ctx)
                seen_docs.add(ctx.document_id)

    # Sort by relevance score descending, take top_k
    contexts.sort(key=lambda c: c.relevance_score, reverse=True)
    return contexts[:top_k]


async def _retrieve_semantic(
    query: str, db: AsyncSession, top_k: int
) -> list[RetrievedContext]:
    """Retrieve context chunks using vector similarity."""
    try:
        query_embedding = generate_single_embedding(query)
    except Exception as e:
        logger.error("Failed to generate query embedding for RAG: %s", e)
        return []

    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    sql = text("""
        SELECT
            de.document_id,
            de.chunk_text,
            1 - (de.embedding <=> :query_embedding::vector) as similarity,
            d.title,
            d.url,
            d.source
        FROM document_embeddings de
        JOIN documents d ON d.id = de.document_id
        WHERE de.embedding IS NOT NULL
        ORDER BY de.embedding <=> :query_embedding::vector
        LIMIT :top_k
    """)

    result = await db.execute(
        sql, {"query_embedding": embedding_str, "top_k": top_k * 2}
    )

    contexts = []
    seen_docs = set()
    for row in result:
        doc_id = str(row.document_id)
        # Keep best chunk per document
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)

        contexts.append(
            RetrievedContext(
                document_id=doc_id,
                chunk_text=row.chunk_text,
                title=row.title or "",
                url=row.url,
                source=row.source,
                relevance_score=float(row.similarity),
            )
        )

    return contexts[:top_k]


async def _retrieve_bm25(
    query: str, db: AsyncSession, top_k: int
) -> list[RetrievedContext]:
    """Retrieve context from BM25 search results."""
    results, _ = await bm25_search(query, db, page=1, size=top_k)

    contexts = []
    for r in results:
        # Fetch full clean_content for the document (BM25 only returns snippets)
        doc_result = await db.execute(
            select(Document.clean_content).where(Document.id == r.document_id)
        )
        content = doc_result.scalar()

        # Use first 1000 chars as context if full content is available
        chunk = content[:1000] if content else r.snippet

        contexts.append(
            RetrievedContext(
                document_id=r.document_id,
                chunk_text=chunk,
                title=r.title,
                url=r.url,
                source=r.source,
                relevance_score=r.score,
            )
        )

    return contexts
