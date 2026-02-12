import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_job import CrawlJob
from app.models.document import Document
from app.services.crawler.base import BaseCrawler, CrawledPage
from app.services.crawler.generic import GenericCrawler
from app.services.crawler.hackernews import HackerNewsCrawler
from app.services.crawler.reddit import RedditCrawler
from app.services.crawler.wikipedia import WikipediaCrawler
from app.services.indexer.text_processor import TextProcessor

logger = logging.getLogger("hyperseek.crawler.manager")

# Registry of available crawlers
CRAWLERS: dict[str, type[BaseCrawler]] = {
    "wikipedia": WikipediaCrawler,
    "reddit": RedditCrawler,
    "hackernews": HackerNewsCrawler,
    "custom": GenericCrawler,
}

text_processor = TextProcessor()


def get_crawler(source: str) -> BaseCrawler:
    """Get a crawler instance for the given source."""
    crawler_cls = CRAWLERS.get(source)
    if not crawler_cls:
        raise ValueError(f"Unknown source: {source}. Available: {list(CRAWLERS.keys())}")
    return crawler_cls()


async def execute_crawl(job_id: str, source: str, config: dict, db: AsyncSession):
    """Execute a crawl job: fetch pages, clean text, store documents.

    This is the main orchestration function called by Celery tasks.
    It updates the CrawlJob row as it progresses.
    """
    crawler = get_crawler(source)

    # Mark job as running
    await db.execute(
        update(CrawlJob)
        .where(CrawlJob.id == job_id)
        .values(status="running", started_at=datetime.now(timezone.utc))
    )
    await db.commit()

    docs_found = 0
    docs_indexed = 0

    try:
        async for page in crawler.crawl(config):
            docs_found += 1

            # Update progress periodically
            if docs_found % 10 == 0:
                await db.execute(
                    update(CrawlJob)
                    .where(CrawlJob.id == job_id)
                    .values(documents_found=docs_found)
                )
                await db.commit()

            # Check if document already exists
            existing = await db.execute(
                select(Document).where(Document.url == page.url)
            )
            if existing.scalar_one_or_none():
                logger.debug("Skipping duplicate URL: %s", page.url)
                continue

            # Clean text
            clean_text = text_processor.html_to_text(page.raw_html)
            if not clean_text or len(clean_text.strip()) < 50:
                logger.debug("Skipping low-content page: %s", page.url)
                continue

            word_count = len(clean_text.split())

            doc = Document(
                url=page.url,
                title=page.title,
                raw_content=page.raw_html,
                clean_content=clean_text,
                source=page.source,
                source_metadata=page.metadata,
                word_count=word_count,
            )
            db.add(doc)
            docs_indexed += 1

            # Batch commit every 10 documents
            if docs_indexed % 10 == 0:
                await db.commit()

        # Final commit
        await db.commit()

        # Mark job complete
        await db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                status="completed",
                documents_found=docs_found,
                documents_indexed=docs_indexed,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        logger.info(
            "Crawl job %s completed: found=%d, indexed=%d",
            job_id,
            docs_found,
            docs_indexed,
        )

    except Exception as e:
        logger.error("Crawl job %s failed: %s", job_id, e)
        await db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                status="failed",
                error_message=str(e),
                documents_found=docs_found,
                documents_indexed=docs_indexed,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        raise
