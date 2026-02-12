import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.search.bm25 import BM25Result, bm25_search
from app.services.search.semantic import SemanticResult, semantic_search

logger = logging.getLogger("hyperseek.search.hybrid")


@dataclass
class HybridResult:
    document_id: str
    score: float
    title: str
    url: str
    source: str
    snippet: str
    bm25_rank: int | None
    semantic_rank: int | None


async def hybrid_search(
    query: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 10,
) -> tuple[list[HybridResult], int]:
    """Hybrid search combining BM25 and semantic search using Reciprocal Rank Fusion.

    RRF formula: RRF_score(d) = sum(1 / (k + rank_i(d)))
    where k=60 (standard constant), across BM25 and semantic ranking lists.

    This gives robust results because:
    - Documents that rank high in both systems get the highest score
    - Documents in only one list still get considered
    - The k constant prevents extreme scores from dominating
    """
    k = settings.rrf_k

    # Fetch more results from each system than the user requested
    # so RRF has enough candidates to work with
    fetch_size = min(size * 3, settings.max_search_results)

    # Run both searches
    bm25_results, bm25_total = await bm25_search(query, db, page=1, size=fetch_size)
    semantic_results, semantic_total = await semantic_search(query, db, page=1, size=fetch_size)

    # Build rank maps (doc_id -> rank position, 1-indexed)
    bm25_ranks: dict[str, int] = {}
    bm25_data: dict[str, BM25Result] = {}
    for rank, result in enumerate(bm25_results, 1):
        bm25_ranks[result.document_id] = rank
        bm25_data[result.document_id] = result

    semantic_ranks: dict[str, int] = {}
    semantic_data: dict[str, SemanticResult] = {}
    for rank, result in enumerate(semantic_results, 1):
        semantic_ranks[result.document_id] = rank
        semantic_data[result.document_id] = result

    # Compute RRF scores
    all_doc_ids = set(bm25_ranks.keys()) | set(semantic_ranks.keys())
    rrf_scores: dict[str, float] = {}

    for doc_id in all_doc_ids:
        score = 0.0
        if doc_id in bm25_ranks:
            score += 1.0 / (k + bm25_ranks[doc_id])
        if doc_id in semantic_ranks:
            score += 1.0 / (k + semantic_ranks[doc_id])
        rrf_scores[doc_id] = score

    # Sort by RRF score
    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    total = len(sorted_docs)

    # Paginate
    offset = (page - 1) * size
    page_docs = sorted_docs[offset : offset + size]

    results = []
    for doc_id, rrf_score in page_docs:
        # Use BM25 data if available, else semantic
        bm25 = bm25_data.get(doc_id)
        sem = semantic_data.get(doc_id)
        source_data = bm25 or sem

        if source_data is None:
            continue

        # Prefer BM25 snippet (it has keyword-centered windowing)
        snippet = bm25.snippet if bm25 else sem.snippet

        results.append(
            HybridResult(
                document_id=doc_id,
                score=round(rrf_score, 6),
                title=source_data.title,
                url=source_data.url,
                source=source_data.source,
                snippet=snippet,
                bm25_rank=bm25_ranks.get(doc_id),
                semantic_rank=semantic_ranks.get(doc_id),
            )
        )

    logger.info(
        "Hybrid search: bm25=%d, semantic=%d, merged=%d, rrf_page=%d",
        len(bm25_results),
        len(semantic_results),
        total,
        len(results),
    )

    return results, total
