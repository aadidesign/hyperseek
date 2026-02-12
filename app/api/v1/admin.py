import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import hash_api_key, require_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.crawl_job import CrawlJob
from app.models.document import Document

router = APIRouter(prefix="/admin")


@router.post("/api-keys", status_code=201)
async def create_api_key(
    request: dict,
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. Returns the raw key only once."""
    name = request.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    tier = request.get("tier", "free")
    if tier not in ("free", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="tier must be free, pro, or enterprise")

    tier_limits = {
        "free": {"rate_limit": 30, "daily_quota": 500},
        "pro": {"rate_limit": 100, "daily_quota": 5000},
        "enterprise": {"rate_limit": 500, "daily_quota": 50000},
    }

    raw_key = f"sk-{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        key_hash=key_hash,
        name=name,
        tier=tier,
        rate_limit=tier_limits[tier]["rate_limit"],
        daily_quota=tier_limits[tier]["daily_quota"],
    )
    db.add(api_key)
    await db.flush()

    return {
        "id": str(api_key.id),
        "name": api_key.name,
        "tier": api_key.tier,
        "key": raw_key,
        "rate_limit": api_key.rate_limit,
        "daily_quota": api_key.daily_quota,
        "warning": "Store this key securely. It will not be shown again.",
    }


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    keys = result.scalars().all()
    return {
        "keys": [
            {
                "id": str(k.id),
                "name": k.name,
                "tier": k.tier,
                "rate_limit": k.rate_limit,
                "daily_quota": k.daily_quota,
                "is_active": k.is_active,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ]
    }


@router.post("/reindex")
async def trigger_reindex(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
):
    from app.workers.reindex_tasks import full_reindex

    full_reindex.delay()
    return {"message": "Full reindex triggered", "status": "queued"}


@router.get("/stats")
async def system_stats(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(require_api_key),
):
    from app.models.index import CollectionStats, DocumentStats, InvertedIndex

    doc_count = await db.execute(select(func.count(Document.id)))
    indexed_count = await db.execute(
        select(func.count(Document.id)).where(Document.indexed_at.isnot(None))
    )
    job_count = await db.execute(
        select(func.count(CrawlJob.id)).where(CrawlJob.status == "running")
    )
    term_count = await db.execute(
        select(func.count(func.distinct(InvertedIndex.term)))
    )

    # Get collection stats
    coll_result = await db.execute(select(CollectionStats).where(CollectionStats.id == 1))
    coll_stats = coll_result.scalar_one_or_none()

    return {
        "total_documents": doc_count.scalar() or 0,
        "indexed_documents": indexed_count.scalar() or 0,
        "active_crawl_jobs": job_count.scalar() or 0,
        "unique_terms": term_count.scalar() or 0,
        "avg_document_length": coll_stats.avg_document_length if coll_stats else 0.0,
    }
