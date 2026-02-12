import asyncio
import logging
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.crawler.base import BaseCrawler, CrawledPage
from app.utils.robots import can_fetch

logger = logging.getLogger("hyperseek.crawler.generic")


class GenericCrawler(BaseCrawler):
    """Crawl arbitrary URLs with depth-limited link following.

    Starts from a seed URL, fetches HTML, extracts links, and follows
    them up to max_depth. Respects robots.txt and rate limits.
    """

    source = "custom"

    async def validate_config(self, config: dict) -> dict:
        urls = config.get("urls")
        if not urls or not isinstance(urls, list):
            raise ValueError("Generic crawler requires 'urls' (list of seed URLs)")
        max_pages = min(int(config.get("max_pages", 50)), 500)
        max_depth = min(int(config.get("max_depth", 2)), settings.max_crawl_depth)
        return {
            "urls": urls,
            "max_pages": max_pages,
            "max_depth": max_depth,
        }

    async def crawl(self, config: dict) -> AsyncIterator[CrawledPage]:
        config = await self.validate_config(config)
        seed_urls = config["urls"]
        max_pages = config["max_pages"]
        max_depth = config["max_depth"]

        visited: set[str] = set()
        # Queue: (url, depth)
        queue: list[tuple[str, int]] = [(url, 0) for url in seed_urls]
        pages_yielded = 0

        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            while queue and pages_yielded < max_pages:
                url, depth = queue.pop(0)

                # Normalize URL
                normalized = self._normalize_url(url)
                if normalized in visited:
                    continue
                visited.add(normalized)

                # Check robots.txt
                if not await can_fetch(normalized):
                    logger.info("Blocked by robots.txt: %s", normalized)
                    continue

                try:
                    resp = await client.get(normalized)
                    if resp.status_code != 200:
                        continue
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        continue

                    html = resp.text
                    soup = BeautifulSoup(html, "lxml")

                    title = ""
                    title_tag = soup.find("title")
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                    yield CrawledPage(
                        url=normalized,
                        title=title,
                        raw_html=html,
                        source="custom",
                        metadata={
                            "depth": depth,
                            "content_length": len(html),
                        },
                    )
                    pages_yielded += 1

                    # Extract links for next depth level
                    if depth < max_depth:
                        links = self._extract_links(soup, normalized)
                        for link in links:
                            if link not in visited:
                                queue.append((link, depth + 1))

                    await asyncio.sleep(settings.crawl_delay_seconds)

                except Exception as e:
                    logger.error("Failed to crawl %s: %s", normalized, e)
                    continue

        logger.info(
            "Generic crawl complete. Visited %d pages, yielded %d",
            len(visited),
            pages_yielded,
        )

    def _normalize_url(self, url: str) -> str:
        """Strip fragments, normalize scheme."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract same-domain links from HTML."""
        base_domain = urlparse(base_url).netloc
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            # Same domain only, skip non-http
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if normalized not in links:
                    links.append(normalized)
        return links[:50]  # Cap to avoid explosion
