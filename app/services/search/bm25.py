import logging
import math
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.index import CollectionStats, DocumentStats, InvertedIndex
from app.services.indexer.text_processor import TextProcessor

logger = logging.getLogger("hyperseek.search.bm25")

text_processor = TextProcessor()


@dataclass
class BM25Result:
    document_id: str
    score: float
    title: str
    url: str
    source: str
    snippet: str


async def bm25_search(
    query: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 10,
) -> tuple[list[BM25Result], int]:
    """Execute BM25 search against the inverted index.

    Implements Okapi BM25 scoring:
      score(D,Q) = sum over qi in Q of:
        IDF(qi) * (tf(qi,D) * (k1 + 1)) / (tf(qi,D) + k1 * (1 - b + b * |D| / avgdl))

    Returns (results, total_count).
    """
    k1 = settings.bm25_k1
    b = settings.bm25_b

    # Process query through the same pipeline as indexing
    query_terms = text_processor.process(query)
    if not query_terms:
        return [], 0

    # Get collection stats
    coll_result = await db.execute(
        select(CollectionStats).where(CollectionStats.id == 1)
    )
    coll_stats = coll_result.scalar_one_or_none()
    if not coll_stats or coll_stats.total_documents == 0:
        return [], 0

    N = coll_stats.total_documents
    avgdl = coll_stats.avg_document_length

    # Get document frequency for each query term (how many docs contain this term)
    df_result = await db.execute(
        select(
            InvertedIndex.term,
            func.count(InvertedIndex.document_id).label("doc_freq"),
        )
        .where(InvertedIndex.term.in_(query_terms))
        .group_by(InvertedIndex.term)
    )
    doc_frequencies = {row.term: row.doc_freq for row in df_result}

    # Calculate IDF for each query term
    idf_scores = {}
    for term in query_terms:
        df = doc_frequencies.get(term, 0)
        if df == 0:
            idf_scores[term] = 0
        else:
            # Standard BM25 IDF formula
            idf_scores[term] = math.log((N - df + 0.5) / (df + 0.5) + 1)

    # Skip terms with zero IDF (not in any document)
    active_terms = [t for t in query_terms if idf_scores.get(t, 0) > 0]
    if not active_terms:
        return [], 0

    # Fetch matching inverted index entries for all active terms
    # Join with document_stats to get document length
    idx_result = await db.execute(
        select(
            InvertedIndex.document_id,
            InvertedIndex.term,
            InvertedIndex.term_frequency,
            DocumentStats.total_terms,
        )
        .join(
            DocumentStats,
            DocumentStats.document_id == InvertedIndex.document_id,
        )
        .where(InvertedIndex.term.in_(active_terms))
    )

    # Calculate BM25 scores per document
    doc_scores: dict[str, float] = {}
    for row in idx_result:
        doc_id = str(row.document_id)
        term = row.term
        tf = row.term_frequency
        doc_len = row.total_terms

        idf = idf_scores[term]
        tf_component = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avgdl))
        score = idf * tf_component

        doc_scores[doc_id] = doc_scores.get(doc_id, 0) + score

    if not doc_scores:
        return [], 0

    # Sort by score descending
    sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    total = len(sorted_docs)

    # Paginate
    offset = (page - 1) * size
    page_docs = sorted_docs[offset : offset + size]

    if not page_docs:
        return [], total

    # Fetch document details for the page
    doc_ids = [doc_id for doc_id, _ in page_docs]
    doc_result = await db.execute(
        select(Document).where(Document.id.in_(doc_ids))
    )
    docs_by_id = {str(d.id): d for d in doc_result.scalars().all()}

    results = []
    for doc_id, score in page_docs:
        doc = docs_by_id.get(doc_id)
        if not doc:
            continue

        snippet = _generate_snippet(doc.clean_content or "", query_terms)

        results.append(
            BM25Result(
                document_id=doc_id,
                score=round(score, 4),
                title=doc.title or "",
                url=doc.url,
                source=doc.source,
                snippet=snippet,
            )
        )

    return results, total


def _generate_snippet(content: str, query_terms: list[str], max_length: int = 250) -> str:
    """Generate a snippet around the first occurrence of query terms.

    Finds the earliest position of any query term in the content,
    then extracts a window of text around it.
    """
    if not content:
        return ""

    content_lower = content.lower()
    best_pos = len(content)

    for term in query_terms:
        pos = content_lower.find(term)
        if pos != -1 and pos < best_pos:
            best_pos = pos

    if best_pos == len(content):
        # No term found, return start of content
        return content[:max_length] + ("..." if len(content) > max_length else "")

    # Window around the match
    start = max(0, best_pos - 50)
    end = min(len(content), start + max_length)

    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


def highlight_terms(text: str, query_terms: list[str]) -> str:
    """Add <mark> tags around matching terms for highlighting."""
    if not text:
        return ""
    result = text
    for term in query_terms:
        # Case-insensitive replacement
        import re
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub(f"<mark>{term}</mark>", result)
    return result
