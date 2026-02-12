from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key
from app.database import get_db
from app.models.api_key import ApiKey
from app.services.autocomplete import autocomplete_search

router = APIRouter()


@router.get("/autocomplete")
async def autocomplete(
    request: Request,
    prefix: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey | None = Depends(get_api_key),
):
    """Get autocompletion suggestions for a search prefix.

    Uses an in-memory trie for fast prefix matching, with PostgreSQL
    trigram index as fallback. Suggestions are ranked by frequency.
    """
    suggestions = await autocomplete_search(prefix, db, limit)
    return {
        "prefix": prefix,
        "suggestions": suggestions,
    }
