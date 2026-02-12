import hashlib
import logging
import re

from app.services.indexer.text_processor import TextProcessor

logger = logging.getLogger("hyperseek.search.query_processor")

text_processor = TextProcessor()


def process_query(query: str) -> dict:
    """Process a raw search query into structured search parameters.

    Returns:
        {
            "original": str,
            "cleaned": str,
            "tokens": list[str],       # stemmed tokens for BM25
            "raw_tokens": list[str],    # unstemmed tokens for display/highlight
            "cache_key": str,           # deterministic hash for caching
        }
    """
    # Basic cleaning
    cleaned = query.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Tokenize (stemmed for BM25 matching)
    tokens = text_processor.process(cleaned, stem=True)

    # Raw tokens (unstemmed, for highlighting and display)
    raw_tokens = text_processor.remove_stopwords(text_processor.tokenize(cleaned))

    # Cache key: deterministic hash of processed tokens
    token_str = " ".join(sorted(set(tokens)))
    cache_key = hashlib.md5(token_str.encode()).hexdigest()

    return {
        "original": query,
        "cleaned": cleaned,
        "tokens": tokens,
        "raw_tokens": raw_tokens,
        "cache_key": cache_key,
    }
