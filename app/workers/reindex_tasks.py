import asyncio
import logging

from app.config import settings
from app.workers.celery_app import celery

logger = logging.getLogger("hyperseek.workers.reindex")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task(name="app.workers.reindex_tasks.full_reindex")
def full_reindex():
    """Full reindex: rebuild inverted index + vector embeddings for all documents."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models.document import Document
    from app.services.indexer.inverted_index import index_document as do_inverted_index
    from app.services.indexer.inverted_index import update_collection_stats
    from app.services.indexer.vector_indexer import index_document_vectors

    logger.info("Starting full reindex")

    async def _execute():
        engine = create_async_engine(settings.database_url, pool_size=5)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            try:
                result = await session.execute(select(Document.id))
                doc_ids = [str(row[0]) for row in result.all()]

                logger.info("Reindexing %d documents", len(doc_ids))

                success = 0
                for doc_id in doc_ids:
                    try:
                        await do_inverted_index(doc_id, session)
                        await index_document_vectors(doc_id, session)
                        success += 1
                    except Exception as e:
                        logger.error("Reindex failed for doc %s: %s", doc_id, e)

                await update_collection_stats(session)
                logger.info("Full reindex complete: %d/%d succeeded", success, len(doc_ids))
            finally:
                await engine.dispose()

    _run_async(_execute())
