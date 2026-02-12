import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.crawl_job import CrawlJob

router = APIRouter()


@router.post("/crawl", status_code=202)
async def start_crawl(
    request: dict,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Start a new crawl job.

    Body:
      - source: wikipedia | reddit | hackernews | custom
      - config: source-specific configuration dict
        - wikipedia: {query: str, max_pages: int}
        - reddit: {subreddit: str, query: str, max_pages: int}
        - hackernews: {query: str, list_type: top|new|best, max_pages: int}
        - custom: {urls: [str], max_pages: int, max_depth: int}
    """
    from app.services.crawler.manager import CRAWLERS, get_crawler
    from app.workers.crawl_tasks import run_crawl_job

    source = request.get("source")
    config = request.get("config", {})

    if not source or source not in CRAWLERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source. Must be one of: {list(CRAWLERS.keys())}",
        )

    # Validate config before creating the job
    crawler = get_crawler(source)
    try:
        validated_config = await crawler.validate_config(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create crawl job record
    job = CrawlJob(source=source, config=validated_config)
    db.add(job)
    await db.flush()

    # Dispatch to Celery
    run_crawl_job.delay(str(job.id), source, validated_config)

    return {
        "job_id": str(job.id),
        "source": source,
        "status": "pending",
        "message": f"Crawl job queued for {source}",
    }


@router.get("/crawl/jobs")
async def list_crawl_jobs(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    result = await db.execute(
        select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(50)
    )
    jobs = result.scalars().all()
    return {
        "jobs": [
            {
                "id": str(j.id),
                "source": j.source,
                "status": j.status,
                "documents_found": j.documents_found,
                "documents_indexed": j.documents_indexed,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    }


@router.get("/crawl/jobs/{job_id}")
async def get_crawl_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return {
        "id": str(job.id),
        "source": job.source,
        "status": job.status,
        "config": job.config,
        "documents_found": job.documents_found,
        "documents_indexed": job.documents_indexed,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }


@router.post("/crawl/jobs/{job_id}/cancel")
async def cancel_crawl_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Job is not cancellable")
    job.status = "cancelled"
    return {"id": str(job.id), "status": "cancelled"}
