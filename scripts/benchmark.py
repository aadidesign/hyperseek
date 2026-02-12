"""Search quality benchmark.

Usage:
    python -m scripts.benchmark

Runs a set of test queries and measures:
- Latency (p50, p95, p99)
- Result count
- Overlap between BM25 and semantic results (to validate hybrid is useful)
"""

import asyncio
import statistics
import sys
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, ".")

from app.config import settings
from app.services.search.bm25 import bm25_search

# Semantic search import will fail if model not loaded; that's OK
try:
    from app.services.search.semantic import semantic_search
    SEMANTIC_AVAILABLE = True
except Exception:
    SEMANTIC_AVAILABLE = False

TEST_QUERIES = [
    "search engine architecture",
    "web crawler design",
    "information retrieval",
    "machine learning",
    "distributed systems",
    "database indexing",
    "natural language processing",
    "vector embeddings",
    "recommendation systems",
    "API design best practices",
]


async def main():
    print("=== HyperSeek Benchmark ===\n")

    engine = create_async_engine(settings.database_url, pool_size=5)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    bm25_latencies = []
    semantic_latencies = []
    bm25_counts = []
    overlaps = []

    async with session_factory() as db:
        print("Running BM25 benchmark...")
        for query in TEST_QUERIES:
            start = time.time()
            results, total = await bm25_search(query, db, page=1, size=10)
            elapsed = (time.time() - start) * 1000
            bm25_latencies.append(elapsed)
            bm25_counts.append(total)
            print(f"  [{elapsed:6.1f}ms] q='{query}' -> {total} results")

        if SEMANTIC_AVAILABLE:
            print("\nRunning Semantic benchmark...")
            for query in TEST_QUERIES:
                start = time.time()
                results, total = await semantic_search(query, db, page=1, size=10)
                elapsed = (time.time() - start) * 1000
                semantic_latencies.append(elapsed)
                print(f"  [{elapsed:6.1f}ms] q='{query}' -> {total} results")

            # Measure overlap
            print("\nMeasuring BM25/Semantic overlap...")
            for query in TEST_QUERIES:
                bm25_res, _ = await bm25_search(query, db, page=1, size=10)
                sem_res, _ = await semantic_search(query, db, page=1, size=10)
                bm25_ids = {r.document_id for r in bm25_res}
                sem_ids = {r.document_id for r in sem_res}
                if bm25_ids or sem_ids:
                    overlap = len(bm25_ids & sem_ids) / max(len(bm25_ids | sem_ids), 1)
                    overlaps.append(overlap)
                    print(f"  q='{query}': overlap={overlap:.1%} (bm25={len(bm25_ids)}, sem={len(sem_ids)})")

    await engine.dispose()

    # Report
    print("\n=== Results ===\n")
    print("BM25 Latency:")
    if bm25_latencies:
        sorted_lat = sorted(bm25_latencies)
        print(f"  p50:  {sorted_lat[len(sorted_lat)//2]:6.1f} ms")
        print(f"  p95:  {sorted_lat[int(len(sorted_lat)*0.95)]:6.1f} ms")
        print(f"  p99:  {sorted_lat[-1]:6.1f} ms")
        print(f"  mean: {statistics.mean(bm25_latencies):6.1f} ms")

    if semantic_latencies:
        print("\nSemantic Latency:")
        sorted_lat = sorted(semantic_latencies)
        print(f"  p50:  {sorted_lat[len(sorted_lat)//2]:6.1f} ms")
        print(f"  p95:  {sorted_lat[int(len(sorted_lat)*0.95)]:6.1f} ms")
        print(f"  p99:  {sorted_lat[-1]:6.1f} ms")
        print(f"  mean: {statistics.mean(semantic_latencies):6.1f} ms")

    if overlaps:
        print(f"\nBM25/Semantic Overlap: {statistics.mean(overlaps):.1%} avg")
        print("  (Low overlap = hybrid search adds value over either alone)")

    zero_result = sum(1 for c in bm25_counts if c == 0)
    print(f"\nZero-result queries: {zero_result}/{len(TEST_QUERIES)}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
