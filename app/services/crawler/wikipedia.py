import logging
from typing import AsyncIterator

import httpx

from app.services.crawler.base import BaseCrawler, CrawledPage

logger = logging.getLogger("hyperseek.crawler.wikipedia")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


class WikipediaCrawler(BaseCrawler):
    """Crawl Wikipedia articles using the MediaWiki API.

    Uses the search API to find articles, then fetches full HTML content
    for each result. No scraping: pure API usage, respects rate limits.
    """

    source = "wikipedia"

    async def validate_config(self, config: dict) -> dict:
        query = config.get("query")
        if not query or not isinstance(query, str):
            raise ValueError("Wikipedia crawler requires a 'query' string")
        max_pages = min(int(config.get("max_pages", 20)), 100)
        return {"query": query, "max_pages": max_pages}

    async def crawl(self, config: dict) -> AsyncIterator[CrawledPage]:
        config = await self.validate_config(config)
        query = config["query"]
        max_pages = config["max_pages"]

        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Search for articles
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_pages,
                "format": "json",
            }
            resp = await client.get(WIKIPEDIA_API, params=search_params)
            resp.raise_for_status()
            search_results = resp.json().get("query", {}).get("search", [])

            logger.info(
                "Wikipedia search for '%s' returned %d results",
                query,
                len(search_results),
            )

            # Step 2: Fetch full content for each article
            for result in search_results:
                page_id = result["pageid"]
                title = result["title"]

                content_params = {
                    "action": "parse",
                    "pageid": page_id,
                    "prop": "text|categories|langlinks",
                    "format": "json",
                }
                try:
                    content_resp = await client.get(
                        WIKIPEDIA_API, params=content_params
                    )
                    content_resp.raise_for_status()
                    data = content_resp.json().get("parse", {})
                    html = data.get("text", {}).get("*", "")
                    categories = [
                        c["*"] for c in data.get("categories", [])
                    ]

                    url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

                    yield CrawledPage(
                        url=url,
                        title=title,
                        raw_html=html,
                        source="wikipedia",
                        metadata={
                            "page_id": page_id,
                            "categories": categories,
                            "snippet": result.get("snippet", ""),
                        },
                    )
                except Exception as e:
                    logger.error(
                        "Failed to fetch Wikipedia page %s (id=%s): %s",
                        title,
                        page_id,
                        e,
                    )
                    continue
