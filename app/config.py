from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://searchengine:searchengine@localhost:5432/searchengine"
    database_sync_url: str = "postgresql://searchengine:searchengine@localhost:5432/searchengine"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Search defaults
    default_search_type: str = "hybrid"
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    rrf_k: int = 60
    max_search_results: int = 100

    # Rate limiting
    default_rate_limit: int = 100  # requests per minute
    default_daily_quota: int = 1000

    # Crawling
    crawl_delay_seconds: float = 1.0
    max_crawl_depth: int = 3
    max_pages_per_crawl: int = 500
    user_agent: str = "HyperSeekBot/1.0 (+https://github.com/hyperseek)"

    # App
    app_name: str = "HyperSeek API"
    app_version: str = "1.0.0"
    debug: bool = False


settings = Settings()
