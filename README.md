# HyperSeek

A production-grade search engine backend with multi-source federated crawling, hybrid BM25+semantic ranking, RAG-powered answers, and real-time analytics.

Built to demonstrate systems-level backend engineering: data pipelines, information retrieval algorithms, vector search, LLM integration, and scalable infrastructure.

## Architecture

```
                                    +-------------------+
                                    |   FastAPI (8000)  |
                                    |  Search / Crawl / |
                                    |  RAG / Analytics  |
                                    +--------+----------+
                                             |
                    +------------------------+------------------------+
                    |                        |                        |
          +---------v--------+    +----------v---------+    +---------v--------+
          | PostgreSQL+pgvec |    |   Redis (6379)     |    |  Ollama (11434)  |
          | Documents, Index |    | Cache, Rate Limit  |    |  LLM (Llama 3)  |
          | Embeddings, Logs |    | Celery Broker      |    |                  |
          +------------------+    +----------+---------+    +------------------+
                                             |
                                   +---------v---------+
                                   | Celery Workers     |
                                   | Crawling, Indexing |
                                   | Reindexing (Beat)  |
                                   +-------------------+
```

## Features

### Core Search
- **BM25 Ranking** - Okapi BM25 with configurable k1/b parameters, computed from a custom inverted index
- **Semantic Search** - Vector similarity using sentence-transformers (`all-MiniLM-L6-v2`) and pgvector
- **Hybrid Search** - Reciprocal Rank Fusion (RRF) combining BM25 and semantic results
- **Query Processing** - Tokenization, stemming, stop word removal via NLTK
- **Result Caching** - Redis-backed query cache with 5-minute TTL

### Multi-Source Crawling
- **Wikipedia** - MediaWiki API integration, no scraping
- **Reddit** - Public JSON API (subreddit search, post + comment extraction)
- **Hacker News** - Firebase API + Algolia search, with linked page fetching
- **Custom URLs** - Depth-limited web crawler with robots.txt compliance
- **Background Processing** - Celery workers for non-blocking crawl jobs

### RAG (Retrieval-Augmented Generation)
- **Context Retrieval** - Hybrid BM25+semantic retrieval for LLM context
- **Ollama Integration** - Local LLM inference (Llama 3.1, Mistral 7B)
- **Recursive RAG** - Multi-round query generation for deeper answers
- **Streaming** - Token-by-token streaming responses
- **Fallback** - Graceful degradation when Ollama is unavailable

### Infrastructure
- **API Key Auth** - SHA-256 hashed keys with tiered rate limits (free/pro/enterprise)
- **Rate Limiting** - Redis sliding window algorithm, per-key and per-IP
- **Background Workers** - Celery for crawling, indexing, and nightly reindexing
- **Autocompletion** - In-memory trie + PostgreSQL trigram index fallback
- **Analytics** - Query logging, CTR tracking, NDCG/MRR/Precision@k metrics
- **Request Logging** - Structured logging with request IDs and response times

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI (async) |
| Database | PostgreSQL 16 + pgvector |
| Cache / Broker | Redis 7 |
| Task Queue | Celery |
| Embeddings | sentence-transformers |
| LLM | Ollama (local) |
| NLP | NLTK |
| HTTP Client | httpx + BeautifulSoup4 |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Containers | Docker Compose |

## Quick Start

### Prerequisites
- Docker and Docker Compose
- 4GB+ RAM (for embedding model and Ollama)
- GPU recommended for Ollama but not required

### 1. Clone and configure

```bash
git clone <repo-url> hyperseek
cd hyperseek
cp .env.example .env
```

### 2. Start all services

```bash
docker compose up -d
```

This starts:
- **app** (FastAPI) on port 8000
- **worker** (Celery) for background tasks
- **beat** (Celery Beat) for scheduled tasks
- **postgres** (PostgreSQL + pgvector) on port 5432
- **redis** on port 6379
- **ollama** on port 11434

### 3. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

### 4. Pull an LLM model (for RAG)

```bash
docker compose exec ollama ollama pull llama3.1
```

### 5. Seed initial data

```bash
docker compose exec app python -m scripts.seed_data
```

### 6. Verify

```bash
curl http://localhost:8000/api/v1/health
```

## API Reference

### Search

**GET** `/api/v1/search`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| q | string | required | Search query |
| type | string | hybrid | `bm25`, `semantic`, or `hybrid` |
| page | int | 1 | Page number |
| size | int | 10 | Results per page (max 100) |
| highlight | bool | false | Add `<mark>` tags to matches |

```bash
curl "http://localhost:8000/api/v1/search?q=search+engine+architecture&type=hybrid"
```

**POST** `/api/v1/search/rag`

```bash
curl -X POST http://localhost:8000/api/v1/search/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "How do search engines rank results?", "recursive": true, "max_depth": 2}'
```

### Crawling

**POST** `/api/v1/crawl`

```bash
# Crawl Wikipedia
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"source": "wikipedia", "config": {"query": "machine learning", "max_pages": 20}}'

# Crawl Reddit
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"source": "reddit", "config": {"subreddit": "programming", "query": "search engines", "max_pages": 15}}'

# Crawl Hacker News
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"source": "hackernews", "config": {"query": "database", "max_pages": 20}}'

# Crawl custom URLs
curl -X POST http://localhost:8000/api/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"source": "custom", "config": {"urls": ["https://example.com"], "max_pages": 10, "max_depth": 2}}'
```

**GET** `/api/v1/crawl/jobs` - List all crawl jobs

**GET** `/api/v1/crawl/jobs/{id}` - Get job status

### Autocomplete

**GET** `/api/v1/autocomplete?prefix=sear&limit=5`

### Analytics

**POST** `/api/v1/analytics/click` - Track a result click

**GET** `/api/v1/analytics/queries?period=7d` - Query stats

**GET** `/api/v1/analytics/ctr?period=7d` - Click-through rates

**GET** `/api/v1/analytics/quality` - NDCG, MRR, Precision@k

### Admin

**POST** `/api/v1/admin/api-keys` - Create API key

**POST** `/api/v1/admin/reindex` - Trigger full reindex (requires API key)

**GET** `/api/v1/admin/stats` - System statistics (requires API key)

### Authentication

Pass API key via header:

```bash
curl -H "X-API-Key: sk-your-key-here" http://localhost:8000/api/v1/search?q=test
```

Anonymous access is allowed with stricter rate limits (30 req/min vs 100+ for authenticated).

## Key Algorithms

### BM25 (Okapi BM25)

```
score(D,Q) = SUM[ IDF(qi) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * |D| / avgdl)) ]
```

Parameters: k1=1.2, b=0.75 (configurable via `BM25_K1`, `BM25_B` env vars).

### Reciprocal Rank Fusion (RRF)

```
RRF_score(d) = SUM[ 1 / (k + rank_i(d)) ]  for each ranking list i
```

k=60 (standard constant). Combines BM25 and semantic rankings into a single score.

### Recursive RAG

1. Retrieve context for query
2. Generate answer with LLM
3. LLM produces follow-up sub-queries
4. Retrieve more context for sub-queries
5. Synthesize final answer from all context
6. Repeat up to `max_depth` times

## Development

### Run locally (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Download NLTK data
python -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords'); nltk.download('wordnet')"

# Start PostgreSQL and Redis (must be running)
# Run migrations
alembic upgrade head

# Start the API
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A app.workers.celery_app worker --loglevel=info

# Start Celery beat (separate terminal)
celery -A app.workers.celery_app beat --loglevel=info
```

### Run tests

```bash
pytest tests/ -v
```

### Run benchmark

```bash
python -m scripts.benchmark
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgresql+asyncpg://... | Async database URL |
| `DATABASE_SYNC_URL` | postgresql://... | Sync database URL (Alembic) |
| `REDIS_URL` | redis://localhost:6379/0 | Redis connection |
| `CELERY_BROKER_URL` | redis://localhost:6379/1 | Celery broker |
| `CELERY_RESULT_BACKEND` | redis://localhost:6379/2 | Celery results |
| `OLLAMA_BASE_URL` | http://localhost:11434 | Ollama server |
| `LLM_MODEL` | llama3.1 | Ollama model name |
| `EMBEDDING_MODEL` | all-MiniLM-L6-v2 | Sentence transformer model |
| `BM25_K1` | 1.2 | BM25 k1 parameter |
| `BM25_B` | 0.75 | BM25 b parameter |
| `DEFAULT_RATE_LIMIT` | 100 | Requests per minute |
| `CRAWL_DELAY_SECONDS` | 1.0 | Delay between crawl requests |

## Project Structure

```
hyperseek/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py             # Pydantic settings
│   ├── database.py           # SQLAlchemy async engine
│   ├── models/               # Database models (SQLAlchemy)
│   ├── api/v1/               # API route handlers
│   ├── api/deps.py           # Auth + rate limiting dependencies
│   ├── services/
│   │   ├── crawler/          # Multi-source crawlers
│   │   ├── indexer/          # Text processing + indexing
│   │   ├── search/           # BM25, semantic, hybrid search
│   │   ├── rag/              # RAG retriever + generator
│   │   ├── autocomplete.py   # Trie + trigram autocomplete
│   │   └── analytics.py      # Query/CTR/quality analytics
│   ├── workers/              # Celery tasks
│   ├── middleware/            # Rate limiting, request logging
│   └── utils/                # Cache helpers, robots.txt
├── alembic/                  # Database migrations
├── tests/                    # Unit tests
├── scripts/                  # Seed data, benchmarks
├── docker-compose.yml        # Full stack orchestration
├── Dockerfile                # Python app container
└── requirements.txt          # Python dependencies
```

## License

MIT
