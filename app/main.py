import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import settings
from app.middleware.request_logging import RequestLoggingMiddleware

# Configure structured logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize Redis connection pool
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    yield
    # Shutdown: close Redis
    await app.state.redis.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="HyperSeek - Production-grade search engine with BM25, semantic search, hybrid ranking, and RAG.",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)

# --- Routers ---
from app.api.v1 import admin, analytics, autocomplete, crawl, documents, search  # noqa: E402

app.include_router(search.router, prefix="/api/v1", tags=["Search"])
app.include_router(crawl.router, prefix="/api/v1", tags=["Crawl"])
app.include_router(documents.router, prefix="/api/v1", tags=["Documents"])
app.include_router(autocomplete.router, prefix="/api/v1", tags=["Autocomplete"])
app.include_router(analytics.router, prefix="/api/v1", tags=["Analytics"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])


@app.get("/api/v1/health", tags=["Health"])
async def health_check():
    redis_ok = False
    try:
        redis_ok = await app.state.redis.ping()
    except Exception:
        pass

    return {
        "status": "healthy" if redis_ok else "degraded",
        "version": settings.app_version,
        "services": {
            "redis": "up" if redis_ok else "down",
        },
    }
