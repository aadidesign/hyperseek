import asyncio
import logging
from typing import AsyncIterator

import httpx

from app.config import settings
from app.services.crawler.base import BaseCrawler, CrawledPage

logger = logging.getLogger("hyperseek.crawler.reddit")

REDDIT_BASE = "https://www.reddit.com"


class RedditCrawler(BaseCrawler):
    """Crawl Reddit posts using the public JSON API (no OAuth needed).

    Fetches posts from a subreddit or search results. Each post's
    selftext (for text posts) or linked content becomes a document.
    Top comments are included in metadata for richer context.
    """

    source = "reddit"

    async def validate_config(self, config: dict) -> dict:
        subreddit = config.get("subreddit")
        query = config.get("query")
        if not subreddit and not query:
            raise ValueError("Reddit crawler requires 'subreddit' or 'query'")
        max_pages = min(int(config.get("max_pages", 25)), 100)
        sort = config.get("sort", "relevance")
        time_filter = config.get("time_filter", "all")
        return {
            "subreddit": subreddit,
            "query": query,
            "max_pages": max_pages,
            "sort": sort,
            "time_filter": time_filter,
        }

    async def crawl(self, config: dict) -> AsyncIterator[CrawledPage]:
        config = await self.validate_config(config)
        max_pages = config["max_pages"]

        headers = {"User-Agent": settings.user_agent}

        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            posts = await self._fetch_posts(client, config)

            logger.info("Reddit returned %d posts", len(posts))

            for post_data in posts[:max_pages]:
                try:
                    post = post_data.get("data", {})
                    title = post.get("title", "")
                    selftext = post.get("selftext", "")
                    permalink = post.get("permalink", "")
                    url = f"{REDDIT_BASE}{permalink}"

                    # Build HTML-like content from the post
                    html_parts = [f"<h1>{title}</h1>"]
                    if selftext:
                        html_parts.append(f"<div>{selftext}</div>")

                    # Fetch top comments for extra context
                    comments = await self._fetch_comments(client, permalink)
                    for comment in comments[:5]:
                        body = comment.get("data", {}).get("body", "")
                        if body:
                            html_parts.append(f"<blockquote>{body}</blockquote>")

                    raw_html = "\n".join(html_parts)

                    yield CrawledPage(
                        url=url,
                        title=title,
                        raw_html=raw_html,
                        source="reddit",
                        metadata={
                            "subreddit": post.get("subreddit", ""),
                            "author": post.get("author", ""),
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "created_utc": post.get("created_utc", 0),
                            "is_self": post.get("is_self", False),
                        },
                    )

                    # Be polite to Reddit's servers
                    await asyncio.sleep(settings.crawl_delay_seconds)

                except Exception as e:
                    logger.error("Failed to process Reddit post: %s", e)
                    continue

    async def _fetch_posts(
        self, client: httpx.AsyncClient, config: dict
    ) -> list[dict]:
        """Fetch posts from subreddit or search."""
        if config.get("query"):
            url = f"{REDDIT_BASE}/search.json"
            params = {
                "q": config["query"],
                "sort": config["sort"],
                "t": config["time_filter"],
                "limit": config["max_pages"],
            }
            if config.get("subreddit"):
                url = f"{REDDIT_BASE}/r/{config['subreddit']}/search.json"
                params["restrict_sr"] = "on"
        else:
            url = f"{REDDIT_BASE}/r/{config['subreddit']}/hot.json"
            params = {"limit": config["max_pages"]}

        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("children", [])

    async def _fetch_comments(
        self, client: httpx.AsyncClient, permalink: str
    ) -> list[dict]:
        """Fetch top-level comments for a post."""
        try:
            url = f"{REDDIT_BASE}{permalink}.json"
            resp = await client.get(url, params={"limit": 5, "sort": "best"})
            resp.raise_for_status()
            data = resp.json()
            if len(data) > 1:
                return data[1].get("data", {}).get("children", [])
        except Exception as e:
            logger.warning("Failed to fetch comments for %s: %s", permalink, e)
        return []
