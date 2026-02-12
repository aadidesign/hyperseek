"""Seed the search engine with initial data.

Usage:
    python -m scripts.seed_data

This script:
1. Creates an API key for testing
2. Starts crawl jobs for each source
3. Waits for crawling to complete
4. Triggers indexing of all crawled documents
"""

import asyncio
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, ".")

from app.config import settings
from app.api.deps import hash_api_key
from app.models.api_key import ApiKey
from app.models.crawl_job import CrawlJob
from app.models.document import Document
from app.services.crawler.manager import execute_crawl
from app.services.indexer.inverted_index import index_document as do_inverted_index
from app.services.indexer.inverted_index import update_collection_stats
from app.services.autocomplete import populate_from_titles


async def main():
    print("=== HyperSeek Seeder ===\n")

    engine = create_async_engine(settings.database_url, pool_size=5)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as db:
        # 1. Create test API key
        print("[1/5] Creating test API key...")
        raw_key = f"sk-{secrets.token_urlsafe(32)}"
        existing = await db.execute(
            select(ApiKey).where(ApiKey.name == "seed-test-key")
        )
        if not existing.scalar_one_or_none():
            api_key = ApiKey(
                key_hash=hash_api_key(raw_key),
                name="seed-test-key",
                tier="pro",
                rate_limit=100,
                daily_quota=5000,
            )
            db.add(api_key)
            await db.commit()
            print(f"  API Key created: {raw_key}")
            print("  (Save this key - it won't be shown again)")
        else:
            print("  Test API key already exists, skipping")

        # 2. Crawl Wikipedia
        print("\n[2/5] Crawling Wikipedia (search engines topic)...")
        wiki_job = CrawlJob(source="wikipedia", config={"query": "search engine", "max_pages": 10})
        db.add(wiki_job)
        await db.flush()
        try:
            await execute_crawl(str(wiki_job.id), "wikipedia", wiki_job.config, db)
            print(f"  Wikipedia crawl done: {wiki_job.documents_indexed} docs")
        except Exception as e:
            print(f"  Wikipedia crawl error: {e}")

        # 3. Crawl Hacker News
        print("\n[3/5] Crawling Hacker News (top stories)...")
        hn_job = CrawlJob(source="hackernews", config={"list_type": "top", "max_pages": 10})
        db.add(hn_job)
        await db.flush()
        try:
            await execute_crawl(str(hn_job.id), "hackernews", hn_job.config, db)
            print(f"  HN crawl done: {hn_job.documents_indexed} docs")
        except Exception as e:
            print(f"  HN crawl error: {e}")

        # 4. Index all documents
        print("\n[4/5] Indexing all documents (inverted index)...")
        result = await db.execute(select(Document.id))
        doc_ids = [str(row[0]) for row in result.all()]
        indexed = 0
        for doc_id in doc_ids:
            try:
                await do_inverted_index(doc_id, db)
                indexed += 1
            except Exception as e:
                print(f"  Failed to index {doc_id}: {e}")
        await update_collection_stats(db)
        print(f"  Indexed {indexed}/{len(doc_ids)} documents")

        # 5. Populate autocomplete
        print("\n[5/5] Populating autocomplete from titles...")
        await populate_from_titles(db)
        print("  Autocomplete populated")

        # Summary
        total_docs = await db.execute(select(Document.id))
        count = len(total_docs.all())
        print("\n=== HyperSeek Seed Complete ===")
        print(f"Total documents in database: {count}")
        print(f"API base URL: http://localhost:8000/api/v1")
        print(f"OpenAPI docs: http://localhost:8000/docs")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
