from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.services.analytics import (
    get_ctr_stats,
    get_quality_metrics,
    get_query_stats,
    log_click,
)

router = APIRouter()


@router.post("/analytics/click")
async def track_click(
    request: dict,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Track a click on a search result for CTR analytics.

    Body:
      - query_id (str): The query log ID returned in search results
      - document_id (str): The document that was clicked
      - position (int): The rank position of the clicked result
    """
    query_id = request.get("query_id")
    document_id = request.get("document_id")
    position = request.get("position")

    if not all([query_id, document_id, position is not None]):
        raise HTTPException(
            status_code=400,
            detail="query_id, document_id, and position are required",
        )

    await log_click(query_id, document_id, int(position), db)
    return {"status": "recorded"}


@router.get("/analytics/queries")
async def query_analytics(
    period: str = Query("7d", pattern="^\\d+[dh]$"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Get search query analytics for a time period.

    Period format: '7d' (days) or '24h' (hours).
    Returns total queries, top queries, avg latency, zero-result rate.
    """
    stats = await get_query_stats(period, db)
    return stats


@router.get("/analytics/ctr")
async def ctr_analytics(
    period: str = Query("7d", pattern="^\\d+[dh]$"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Get Click-Through Rate analytics.

    Returns overall CTR and CTR broken down by result position.
    """
    stats = await get_ctr_stats(period, db)
    return stats


@router.get("/analytics/quality")
async def quality_metrics(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Get search quality metrics: NDCG, MRR, Precision@k.

    Computed from click data as implicit relevance signals over the last 30 days.
    """
    metrics = await get_quality_metrics(db)
    return metrics
