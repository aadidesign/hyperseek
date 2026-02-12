import asyncio
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.workers.celery_app import celery

logger = logging.getLogger("hyperseek.workers.crawl")

# Sync engine for Celery workers (Celery tasks are synchronous)
_sync_engine = None


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.database_sync_url,
            pool_size=5,
            max_overflow=3,
            pool_pre_ping=True,
        )
    return _sync_engine


def _run_async(coro):
    """Run an async function from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task(name="app.workers.crawl_tasks.run_crawl_job", bind=True, max_retries=3)
def run_crawl_job(self, job_id: str, source: str, config: dict):
    """Execute a crawl job in the background via Celery.

    Since the crawl manager uses async code, we create an event loop
    and run it within the sync Celery worker.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.services.crawler.manager import execute_crawl

    logger.info("Starting crawl job %s (source=%s)", job_id, source)

    async def _execute():
        async_engine = create_async_engine(settings.database_url, pool_size=5)
        async_session_factory = async_sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session_factory() as session:
            try:
                await execute_crawl(job_id, source, config, session)
            except Exception as e:
                logger.error("Crawl job %s error: %s", job_id, e)
                raise
            finally:
                await async_engine.dispose()

    try:
        _run_async(_execute())
    except Exception as exc:
        logger.error("Crawl job %s failed, retrying: %s", job_id, exc)
        raise self.retry(exc=exc, countdown=60)
