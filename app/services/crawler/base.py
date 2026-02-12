from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class CrawledPage:
    """A single page returned by a crawler."""

    url: str
    title: str
    raw_html: str
    source: str  # wikipedia, reddit, hackernews, custom
    metadata: dict = field(default_factory=dict)


class BaseCrawler(ABC):
    """Abstract base for all crawlers.

    Each crawler must implement `crawl()` which yields CrawledPage objects.
    This design allows backpressure-friendly async iteration: the consumer
    (indexing pipeline) can process pages as they arrive rather than waiting
    for the entire crawl to finish.
    """

    source: str  # must be set by subclass

    @abstractmethod
    async def crawl(self, config: dict) -> AsyncIterator[CrawledPage]:
        """Yield pages from the source based on config.

        Config is source-specific. Common keys:
          - query (str): search/topic to crawl
          - max_pages (int): limit on pages to fetch
        """
        ...

    @abstractmethod
    async def validate_config(self, config: dict) -> dict:
        """Validate and normalize crawler config. Raise ValueError on bad input."""
        ...
