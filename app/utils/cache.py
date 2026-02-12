import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("hyperseek.cache")

DEFAULT_TTL = 300  # 5 minutes


async def cache_get(redis: aioredis.Redis, key: str) -> Any | None:
    """Get a value from cache. Returns None on miss."""
    try:
        raw = await redis.get(f"cache:{key}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("Cache get error for key=%s: %s", key, e)
        return None


async def cache_set(
    redis: aioredis.Redis, key: str, value: Any, ttl: int = DEFAULT_TTL
) -> None:
    """Set a value in cache with TTL."""
    try:
        await redis.set(f"cache:{key}", json.dumps(value), ex=ttl)
    except Exception as e:
        logger.warning("Cache set error for key=%s: %s", key, e)


async def cache_delete(redis: aioredis.Redis, key: str) -> None:
    """Delete a cache entry."""
    try:
        await redis.delete(f"cache:{key}")
    except Exception as e:
        logger.warning("Cache delete error for key=%s: %s", key, e)


async def cache_invalidate_pattern(redis: aioredis.Redis, pattern: str) -> int:
    """Delete all keys matching a pattern. Returns count deleted."""
    try:
        count = 0
        async for key in redis.scan_iter(f"cache:{pattern}"):
            await redis.delete(key)
            count += 1
        return count
    except Exception as e:
        logger.warning("Cache invalidate error for pattern=%s: %s", pattern, e)
        return 0
