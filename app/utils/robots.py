import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings

logger = logging.getLogger("hyperseek.robots")

# In-memory cache for robots.txt parsers
_robots_cache: dict[str, RobotFileParser] = {}


async def can_fetch(url: str) -> bool:
    """Check if our user agent is allowed to fetch the given URL per robots.txt."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in _robots_cache:
        parser = RobotFileParser()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # If robots.txt doesn't exist or errors, allow everything
                    parser.allow_all = True
        except Exception as e:
            logger.warning("Failed to fetch robots.txt from %s: %s", robots_url, e)
            parser.allow_all = True

        _robots_cache[robots_url] = parser

    parser = _robots_cache[robots_url]
    return parser.can_fetch(settings.user_agent, url)


def clear_robots_cache():
    """Clear the robots.txt cache."""
    _robots_cache.clear()
