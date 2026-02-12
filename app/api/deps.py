import hashlib

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limiter import check_rate_limit
from app.models.api_key import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_api_key(
    request: Request,
    raw_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> ApiKey | None:
    """Validate API key if provided. Apply rate limiting based on tier."""
    if raw_key is None:
        # Anonymous access: apply default rate limit by IP
        client_ip = request.client.host if request.client else "unknown"
        await check_rate_limit(request, key=f"anon:{client_ip}", limit=30)
        return None

    key_hash = hash_api_key(raw_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None or not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    # Apply per-key rate limit
    await check_rate_limit(
        request,
        key=f"key:{str(api_key.id)}",
        limit=api_key.rate_limit,
    )

    return api_key


async def require_api_key(
    api_key: ApiKey | None = Depends(get_api_key),
) -> ApiKey:
    """Require a valid API key (for admin endpoints)."""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    return api_key
