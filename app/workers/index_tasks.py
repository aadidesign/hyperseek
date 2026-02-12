import asyncio
import logging

from app.config import settings
from app.workers.celery_app import celery

logger = logging.getLogger("hyperseek.workers.index")


def _run_async(coro):
    """Run an async function from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task(name="app.workers.index_tasks.index_document", bind=True, max_retries=3)
def index_document(self, document_id: str):
    """Index a single document: build inverted index + generate vector embeddings."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.services.indexer.inverted_index import index_document as do_inverted_index
    from app.services.indexer.inverted_index import update_collection_stats
    from app.services.indexer.vector_indexer import index_document_vectors

    logger.info("Indexing document %s", document_id)

    async def _execute():
        engine = create_async_engine(settings.database_url, pool_size=3)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            try:
                # Build inverted index (BM25)
                await do_inverted_index(document_id, session)

                # Generate vector embeddings (semantic search)
                chunks = await index_document_vectors(document_id, session)
                logger.info("Document %s: inverted index + %d vector chunks", document_id, chunks)

                # Update collection stats
                await update_collection_stats(session)
            except Exception as e:
                logger.error("Index document %s error: %s", document_id, e)
                raise
            finally:
                await engine.dispose()

    try:
        _run_async(_execute())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)


@celery.task(name="app.workers.index_tasks.index_batch")
def index_batch(document_ids: list[str]):
    """Index a batch of documents (inverted index + vectors), then update collection stats."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.services.indexer.inverted_index import index_document as do_inverted_index
    from app.services.indexer.inverted_index import update_collection_stats
    from app.services.indexer.vector_indexer import index_document_vectors

    logger.info("Batch indexing %d documents", len(document_ids))

    async def _execute():
        engine = create_async_engine(settings.database_url, pool_size=5)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            try:
                for doc_id in document_ids:
                    try:
                        await do_inverted_index(doc_id, session)
                        await index_document_vectors(doc_id, session)
                    except Exception as e:
                        logger.error("Failed to index doc %s: %s", doc_id, e)
                        continue
                await update_collection_stats(session)
            finally:
                await engine.dispose()

    _run_async(_execute())
