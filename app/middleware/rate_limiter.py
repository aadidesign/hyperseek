import time

from fastapi import HTTPException, Request, status


async def check_rate_limit(
    request: Request,
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    """Sliding window rate limiter using Redis sorted sets."""
    redis = request.app.state.redis
    now = time.time()
    window_start = now - window_seconds
    pipe_key = f"ratelimit:{key}"

    pipe = redis.pipeline()
    # Remove expired entries
    pipe.zremrangebyscore(pipe_key, 0, window_start)
    # Count current window
    pipe.zcard(pipe_key)
    # Add current request
    pipe.zadd(pipe_key, {str(now): now})
    # Set expiry on the key
    pipe.expire(pipe_key, window_seconds)
    results = await pipe.execute()

    request_count = results[1]
    if request_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after_seconds": window_seconds,
            },
        )
