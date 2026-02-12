import time

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.services.search.bm25 import bm25_search, highlight_terms
from app.services.search.query_processor import process_query
from app.utils.cache import cache_get, cache_set

router = APIRouter()


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    type: str = Query("hybrid", pattern="^(bm25|semantic|hybrid)$"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    highlight: bool = Query(False, description="Add <mark> tags to matching terms"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Search indexed documents.

    Search types:
    - bm25: Traditional keyword search using BM25 ranking
    - semantic: Vector similarity search using embeddings (Phase 5)
    - hybrid: Combined BM25 + semantic with Reciprocal Rank Fusion (Phase 5)
    """
    start_time = time.time()

    # Process query
    processed = process_query(q)

    # Check cache
    cache_key = f"search:{type}:{processed['cache_key']}:p{page}:s{size}"
    redis = request.app.state.redis
    cached = await cache_get(redis, cache_key)
    if cached:
        cached["cached"] = True
        return cached

    # Execute search based on type
    if type == "bm25":
        results, total = await bm25_search(q, db, page, size)
    elif type == "semantic":
        # Semantic search - implemented in Phase 5
        from app.services.search.semantic import semantic_search
        results, total = await semantic_search(q, db, page, size)
    elif type == "hybrid":
        # Try hybrid, fall back to BM25 if semantic not ready
        try:
            from app.services.search.hybrid import hybrid_search
            results, total = await hybrid_search(q, db, page, size)
        except Exception:
            results, total = await bm25_search(q, db, page, size)
    else:
        results, total = await bm25_search(q, db, page, size)

    latency_ms = (time.time() - start_time) * 1000

    # Format results
    formatted_results = []
    for r in results:
        entry = {
            "document_id": r.document_id,
            "score": r.score,
            "title": r.title,
            "url": r.url,
            "source": r.source,
            "snippet": r.snippet,
        }
        if highlight and hasattr(r, "snippet"):
            entry["snippet"] = highlight_terms(r.snippet, processed["raw_tokens"])
            entry["title"] = highlight_terms(r.title, processed["raw_tokens"])
        formatted_results.append(entry)

    # Log query for analytics + autocomplete
    from app.services.analytics import log_query
    from app.services.autocomplete import record_query_term

    query_log_id = await log_query(
        query_text=q,
        search_type=type,
        results_count=total,
        latency_ms=round(latency_ms, 1),
        db=db,
        api_key_id=str(api_key.id) if api_key else None,
    )
    await record_query_term(q, db)

    response = {
        "query": q,
        "query_id": query_log_id,
        "type": type,
        "page": page,
        "size": size,
        "total": total,
        "latency_ms": round(latency_ms, 1),
        "cached": False,
        "results": formatted_results,
    }

    # Cache successful results for 5 minutes
    if total > 0:
        await cache_set(redis, cache_key, response, ttl=300)

    return response


@router.post("/search/rag")
async def search_rag(
    request_body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """RAG-powered search: retrieve context and generate an LLM answer.

    Body:
      - query (str): The search query
      - recursive (bool): Enable recursive multi-query RAG (default: false)
      - max_depth (int): Max recursion depth (default: 2, max: 3)
      - stream (bool): Stream the response token by token (default: false)
    """
    from fastapi.responses import StreamingResponse

    from app.services.rag.generator import generate_answer, generate_answer_stream
    from app.services.rag.recursive import recursive_rag
    from app.services.rag.retriever import retrieve_context

    start_time = time.time()

    query = request_body.get("query", "")
    if not query:
        return {"error": "query is required"}

    recursive = request_body.get("recursive", False)
    max_depth = min(int(request_body.get("max_depth", 2)), 3)
    stream = request_body.get("stream", False)

    if recursive:
        # Recursive RAG: multiple rounds of retrieval + generation
        result = await recursive_rag(query, db, max_depth=max_depth)
        latency_ms = (time.time() - start_time) * 1000
        return {
            "query": query,
            "search_type": "recursive_rag",
            "latency_ms": round(latency_ms, 1),
            **result,
        }

    # Standard RAG: single retrieval + generation
    contexts = await retrieve_context(query, db, top_k=5)

    if stream:
        # Streaming response
        async def event_stream():
            async for token in generate_answer_stream(query, contexts):
                yield token

        return StreamingResponse(
            event_stream(),
            media_type="text/plain",
            headers={"X-Search-Type": "rag_stream"},
        )

    # Non-streaming response
    result = await generate_answer(query, contexts)
    latency_ms = (time.time() - start_time) * 1000

    return {
        "query": query,
        "search_type": "rag",
        "latency_ms": round(latency_ms, 1),
        **result,
    }
