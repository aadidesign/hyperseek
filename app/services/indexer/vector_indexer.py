import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.embedding import DocumentEmbedding

logger = logging.getLogger("hyperseek.indexer.vector")

# Lazy-loaded embedding model (heavy resource, load once)
_model = None


def _get_embedding_model():
    """Lazy load the sentence-transformer model."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded successfully")
    return _model


def chunk_text(
    text: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Uses word boundaries to avoid splitting mid-word.
    chunk_size and chunk_overlap are in words (not tokens).
    """
    if chunk_size is None:
        chunk_size = settings.chunk_size
    if chunk_overlap is None:
        chunk_overlap = settings.chunk_overlap

    if not text:
        return []

    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - chunk_overlap

    return chunks


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts using sentence-transformers.

    Returns list of embedding vectors (each is a list of floats).
    """
    model = _get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def generate_single_embedding(text: str) -> list[float]:
    """Generate embedding for a single text. Used for query embedding."""
    model = _get_embedding_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


async def index_document_vectors(doc_id: str, db: AsyncSession) -> int:
    """Generate and store vector embeddings for a document.

    Steps:
    1. Load document content
    2. Chunk the text
    3. Generate embeddings for each chunk
    4. Store in document_embeddings table

    Returns the number of chunks indexed.
    """
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc or not doc.clean_content:
        logger.warning("Document %s not found or empty for vector indexing", doc_id)
        return 0

    # Chunk the document
    chunks = chunk_text(doc.clean_content)
    if not chunks:
        return 0

    # Generate embeddings
    try:
        embeddings = generate_embeddings(chunks)
    except Exception as e:
        logger.error("Failed to generate embeddings for doc %s: %s", doc_id, e)
        return 0

    # Delete existing embeddings for this document
    await db.execute(
        delete(DocumentEmbedding).where(DocumentEmbedding.document_id == doc_id)
    )

    # Insert new embeddings
    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        doc_embedding = DocumentEmbedding(
            document_id=doc_id,
            chunk_index=idx,
            chunk_text=chunk,
            embedding=embedding,
        )
        db.add(doc_embedding)

    await db.commit()
    logger.info("Indexed %d vector chunks for document %s", len(chunks), doc_id)
    return len(chunks)
