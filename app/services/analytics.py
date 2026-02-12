import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import ClickEvent, QueryLog

logger = logging.getLogger("hyperseek.analytics")


async def log_query(
    query_text: str,
    search_type: str,
    results_count: int,
    latency_ms: float,
    db: AsyncSession,
    api_key_id: str | None = None,
) -> str:
    """Log a search query for analytics. Returns the query log ID."""
    log = QueryLog(
        query_text=query_text,
        api_key_id=api_key_id,
        search_type=search_type,
        results_count=results_count,
        latency_ms=latency_ms,
    )
    db.add(log)
    await db.flush()
    return str(log.id)


async def log_click(
    query_log_id: str,
    document_id: str,
    position: int,
    db: AsyncSession,
) -> None:
    """Log a click event for CTR tracking."""
    click = ClickEvent(
        query_log_id=query_log_id,
        document_id=document_id,
        position=position,
    )
    db.add(click)
    await db.commit()


def _parse_period(period: str) -> datetime:
    """Parse a period string like '7d', '30d', '24h' into a start datetime."""
    now = datetime.now(timezone.utc)
    if period.endswith("d"):
        days = int(period[:-1])
        return now - timedelta(days=days)
    elif period.endswith("h"):
        hours = int(period[:-1])
        return now - timedelta(hours=hours)
    else:
        return now - timedelta(days=7)


async def get_query_stats(period: str, db: AsyncSession) -> dict:
    """Get aggregated query statistics for a time period."""
    start = _parse_period(period)

    # Total queries
    total = await db.execute(
        select(func.count(QueryLog.id)).where(QueryLog.created_at >= start)
    )
    total_queries = total.scalar() or 0

    # Average latency
    avg_lat = await db.execute(
        select(func.avg(QueryLog.latency_ms)).where(QueryLog.created_at >= start)
    )
    avg_latency = round(avg_lat.scalar() or 0, 1)

    # Top queries
    top_q = await db.execute(
        select(
            QueryLog.query_text,
            func.count(QueryLog.id).label("count"),
            func.avg(QueryLog.latency_ms).label("avg_latency"),
        )
        .where(QueryLog.created_at >= start)
        .group_by(QueryLog.query_text)
        .order_by(func.count(QueryLog.id).desc())
        .limit(20)
    )
    top_queries = [
        {
            "query": row.query_text,
            "count": row.count,
            "avg_latency_ms": round(row.avg_latency or 0, 1),
        }
        for row in top_q
    ]

    # Queries by search type
    by_type = await db.execute(
        select(
            QueryLog.search_type,
            func.count(QueryLog.id).label("count"),
        )
        .where(QueryLog.created_at >= start)
        .group_by(QueryLog.search_type)
    )
    queries_by_type = {row.search_type or "unknown": row.count for row in by_type}

    # Zero-result queries
    zero_results = await db.execute(
        select(func.count(QueryLog.id)).where(
            QueryLog.created_at >= start,
            QueryLog.results_count == 0,
        )
    )
    zero_result_count = zero_results.scalar() or 0

    return {
        "period": period,
        "total_queries": total_queries,
        "avg_latency_ms": avg_latency,
        "zero_result_queries": zero_result_count,
        "zero_result_rate": round(zero_result_count / max(total_queries, 1) * 100, 1),
        "queries_by_type": queries_by_type,
        "top_queries": top_queries,
    }


async def get_ctr_stats(period: str, db: AsyncSession) -> dict:
    """Calculate Click-Through Rate statistics."""
    start = _parse_period(period)

    # Total queries with results
    queries_with_results = await db.execute(
        select(func.count(QueryLog.id)).where(
            QueryLog.created_at >= start,
            QueryLog.results_count > 0,
        )
    )
    total_with_results = queries_with_results.scalar() or 0

    # Total queries that received at least one click
    clicked_queries = await db.execute(
        select(func.count(func.distinct(ClickEvent.query_log_id))).where(
            ClickEvent.created_at >= start
        )
    )
    total_clicked = clicked_queries.scalar() or 0

    # Overall CTR
    overall_ctr = total_clicked / max(total_with_results, 1)

    # CTR by position
    position_clicks = await db.execute(
        select(
            ClickEvent.position,
            func.count(ClickEvent.id).label("clicks"),
        )
        .where(ClickEvent.created_at >= start)
        .group_by(ClickEvent.position)
        .order_by(ClickEvent.position)
        .limit(10)
    )
    by_position = [
        {"position": row.position, "clicks": row.clicks}
        for row in position_clicks
    ]

    return {
        "period": period,
        "queries_with_results": total_with_results,
        "queries_with_clicks": total_clicked,
        "overall_ctr": round(overall_ctr, 4),
        "by_position": by_position,
    }


async def get_quality_metrics(db: AsyncSession) -> dict:
    """Calculate search quality metrics: NDCG, MRR, Precision@k.

    These are computed from click data as implicit relevance signals.
    - A click at position k implies relevance for that result.
    - Higher position clicks are weighted more heavily.
    """
    # Get recent click data (last 30 days)
    start = _parse_period("30d")

    # Mean Reciprocal Rank (MRR): average of 1/position for first click per query
    first_clicks = await db.execute(
        text("""
            SELECT query_log_id, MIN(position) as first_click_position
            FROM click_events
            WHERE created_at >= :start
            GROUP BY query_log_id
        """),
        {"start": start},
    )
    positions = [row.first_click_position for row in first_clicks]

    mrr = 0.0
    if positions:
        mrr = sum(1.0 / max(p, 1) for p in positions) / len(positions)

    # Precision@k (how many results in top-k were clicked)
    precision_at_k = {}
    for k in [1, 3, 5, 10]:
        clicks_at_k = await db.execute(
            select(func.count(ClickEvent.id)).where(
                ClickEvent.created_at >= start,
                ClickEvent.position <= k,
            )
        )
        total_opportunities = await db.execute(
            select(func.count(func.distinct(ClickEvent.query_log_id))).where(
                ClickEvent.created_at >= start
            )
        )
        clicks = clicks_at_k.scalar() or 0
        opportunities = total_opportunities.scalar() or 1
        precision_at_k[f"p@{k}"] = round(clicks / (opportunities * k), 4)

    # NDCG (Normalized Discounted Cumulative Gain)
    # Using clicks as binary relevance signals
    query_clicks = await db.execute(
        text("""
            SELECT query_log_id, array_agg(position ORDER BY position) as positions
            FROM click_events
            WHERE created_at >= :start
            GROUP BY query_log_id
            LIMIT 1000
        """),
        {"start": start},
    )

    ndcg_scores = []
    for row in query_clicks:
        clicked_positions = row.positions
        if not clicked_positions:
            continue

        # DCG: sum of 1/log2(position+1) for clicked positions
        dcg = sum(1.0 / math.log2(p + 1) for p in clicked_positions if p > 0)

        # Ideal DCG: if all clicks were at positions 1, 2, 3, ...
        ideal_positions = list(range(1, len(clicked_positions) + 1))
        idcg = sum(1.0 / math.log2(p + 1) for p in ideal_positions)

        if idcg > 0:
            ndcg_scores.append(dcg / idcg)

    avg_ndcg = sum(ndcg_scores) / max(len(ndcg_scores), 1) if ndcg_scores else 0.0

    return {
        "period": "30d",
        "mrr": round(mrr, 4),
        "ndcg": round(avg_ndcg, 4),
        "precision_at_k": precision_at_k,
        "sample_size": len(positions),
    }
