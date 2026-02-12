import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.document import Document

router = APIRouter()


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    query = select(Document).order_by(Document.crawled_at.desc())
    count_query = select(func.count(Document.id))

    if source:
        query = query.where(Document.source == source)
        count_query = count_query.where(Document.source == source)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * size
    result = await db.execute(query.offset(offset).limit(size))
    docs = result.scalars().all()

    return {
        "page": page,
        "size": size,
        "total": total,
        "documents": [
            {
                "id": str(d.id),
                "url": d.url,
                "title": d.title,
                "source": d.source,
                "word_count": d.word_count,
                "crawled_at": d.crawled_at.isoformat() if d.crawled_at else None,
                "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
            }
            for d in docs
        ],
    }


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(doc.id),
        "url": doc.url,
        "title": doc.title,
        "clean_content": doc.clean_content,
        "source": doc.source,
        "source_metadata": doc.source_metadata,
        "word_count": doc.word_count,
        "language": doc.language,
        "crawled_at": doc.crawled_at.isoformat() if doc.crawled_at else None,
        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
    }


@router.post("/documents", status_code=201)
async def create_document(
    request: dict,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    url = request.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    # Check for duplicate
    existing = await db.execute(select(Document).where(Document.url == url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Document with this URL already exists")

    doc = Document(
        url=url,
        title=request.get("title"),
        raw_content=request.get("content"),
        clean_content=request.get("content"),
        source="custom",
        word_count=len(request.get("content", "").split()) if request.get("content") else 0,
    )
    db.add(doc)
    await db.flush()

    return {
        "id": str(doc.id),
        "url": doc.url,
        "title": doc.title,
        "source": doc.source,
        "message": "Document created. It will be indexed in the background.",
    }
