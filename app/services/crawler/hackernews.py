import asyncio
import logging
from typing import AsyncIterator

import httpx

from app.config import settings
from app.services.crawler.base import BaseCrawler, CrawledPage

logger = logging.getLogger("hyperseek.crawler.hackernews")

HN_API = "https://hacker-news.firebaseio.com/v0"
HN_SEARCH_API = "https://hn.algolia.com/api/v1"


class HackerNewsCrawler(BaseCrawler):
    """Crawl Hacker News stories using the Firebase API + Algolia search.

    Supports two modes:
    - query search via Algolia API (for topic-based crawling)
    - top/new/best stories via Firebase API (for general crawling)

    For each story, fetches the linked page content when possible,
    falls back to the HN comments as content.
    """

    source = "hackernews"

    async def validate_config(self, config: dict) -> dict:
        max_pages = min(int(config.get("max_pages", 30)), 100)
        return {
            "query": config.get("query"),
            "list_type": config.get("list_type", "top"),  # top, new, best
            "max_pages": max_pages,
        }

    async def crawl(self, config: dict) -> AsyncIterator[CrawledPage]:
        config = await self.validate_config(config)
        max_pages = config["max_pages"]

        async with httpx.AsyncClient(timeout=30) as client:
            if config.get("query"):
                stories = await self._search_stories(client, config["query"], max_pages)
            else:
                stories = await self._fetch_story_list(
                    client, config["list_type"], max_pages
                )

            logger.info("HackerNews returned %d stories", len(stories))

            for story in stories:
                try:
                    title = story.get("title", "")
                    story_url = story.get("url", "")
                    hn_id = story.get("objectID") or story.get("id")
                    hn_url = f"https://news.ycombinator.com/item?id={hn_id}"

                    # Use the story URL as the document URL, fallback to HN link
                    doc_url = story_url or hn_url

                    # Build content from story text + comments
                    html_parts = [f"<h1>{title}</h1>"]

                    story_text = story.get("story_text") or story.get("text") or ""
                    if story_text:
                        html_parts.append(f"<div>{story_text}</div>")

                    # If it's an external link, try to fetch its content
                    if story_url:
                        page_content = await self._fetch_page(client, story_url)
                        if page_content:
                            html_parts.append(page_content)

                    raw_html = "\n".join(html_parts)

                    yield CrawledPage(
                        url=doc_url,
                        title=title,
                        raw_html=raw_html,
                        source="hackernews",
                        metadata={
                            "hn_id": hn_id,
                            "hn_url": hn_url,
                            "points": story.get("points") or story.get("score", 0),
                            "author": story.get("author") or story.get("by", ""),
                            "num_comments": story.get("num_comments")
                            or story.get("descendants", 0),
                            "created_at": story.get("created_at_i")
                            or story.get("time", 0),
                        },
                    )

                    await asyncio.sleep(settings.crawl_delay_seconds)

                except Exception as e:
                    logger.error("Failed to process HN story: %s", e)
                    continue

    async def _search_stories(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[dict]:
        """Search stories via Algolia HN Search API."""
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": limit,
        }
        resp = await client.get(f"{HN_SEARCH_API}/search", params=params)
        resp.raise_for_status()
        return resp.json().get("hits", [])

    async def _fetch_story_list(
        self, client: httpx.AsyncClient, list_type: str, limit: int
    ) -> list[dict]:
        """Fetch story IDs from Firebase, then fetch each story's details."""
        resp = await client.get(f"{HN_API}/{list_type}stories.json")
        resp.raise_for_status()
        story_ids = resp.json()[:limit]

        stories = []
        for story_id in story_ids:
            try:
                detail_resp = await client.get(f"{HN_API}/item/{story_id}.json")
                detail_resp.raise_for_status()
                story = detail_resp.json()
                if story and story.get("type") == "story":
                    stories.append(story)
            except Exception:
                continue
            await asyncio.sleep(0.1)  # Light delay for Firebase
        return stories

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Try to fetch the actual linked page content. Returns HTML or None."""
        try:
            resp = await client.get(
                url,
                follow_redirects=True,
                timeout=15,
                headers={"User-Agent": settings.user_agent},
            )
            if resp.status_code == 200 and "text/html" in resp.headers.get(
                "content-type", ""
            ):
                return resp.text
        except Exception:
            pass
        return None
