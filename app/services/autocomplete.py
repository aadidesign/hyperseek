import logging
from collections import defaultdict

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autocomplete import AutocompleteTerm

logger = logging.getLogger("hyperseek.autocomplete")


class TrieNode:
    """Node in a prefix trie for fast autocompletion."""

    __slots__ = ("children", "is_end", "term", "frequency")

    def __init__(self):
        self.children: dict[str, TrieNode] = {}
        self.is_end: bool = False
        self.term: str = ""
        self.frequency: int = 0


class AutocompleteTrie:
    """In-memory prefix trie for fast autocompletion.

    The trie is populated from the database and kept in memory.
    For very large term sets, the PostgreSQL trigram index is used
    as a fallback.
    """

    def __init__(self):
        self.root = TrieNode()
        self._size = 0

    def insert(self, term: str, frequency: int = 1):
        """Insert a term into the trie."""
        node = self.root
        for char in term.lower():
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True
        node.term = term
        node.frequency = frequency
        self._size += 1

    def search_prefix(self, prefix: str, limit: int = 5) -> list[dict]:
        """Find all terms matching a prefix, sorted by frequency.

        Returns list of {term, frequency} dicts.
        """
        node = self.root
        for char in prefix.lower():
            if char not in node.children:
                return []
            node = node.children[char]

        # DFS to find all terms under this prefix
        results: list[dict] = []
        self._dfs(node, results)

        # Sort by frequency descending, then alphabetically
        results.sort(key=lambda x: (-x["frequency"], x["term"]))
        return results[:limit]

    def _dfs(self, node: TrieNode, results: list[dict]):
        if node.is_end:
            results.append({"term": node.term, "frequency": node.frequency})
        for child in node.children.values():
            self._dfs(child, results)

    @property
    def size(self) -> int:
        return self._size


# Global trie instance (rebuilt periodically)
_trie: AutocompleteTrie | None = None


async def get_trie(db: AsyncSession) -> AutocompleteTrie:
    """Get or build the autocomplete trie from the database."""
    global _trie
    if _trie is None or _trie.size == 0:
        _trie = await _build_trie(db)
    return _trie


async def _build_trie(db: AsyncSession) -> AutocompleteTrie:
    """Build the trie from the autocomplete_terms table."""
    trie = AutocompleteTrie()
    result = await db.execute(
        select(AutocompleteTerm).order_by(AutocompleteTerm.frequency.desc()).limit(50000)
    )
    for term_obj in result.scalars().all():
        trie.insert(term_obj.term, term_obj.frequency)
    logger.info("Built autocomplete trie with %d terms", trie.size)
    return trie


def rebuild_trie():
    """Invalidate the trie so it gets rebuilt on next access."""
    global _trie
    _trie = None


async def autocomplete_search(
    prefix: str,
    db: AsyncSession,
    limit: int = 5,
) -> list[dict]:
    """Search for autocompletion suggestions.

    Tries the in-memory trie first, falls back to PostgreSQL trigram search.
    """
    # Try trie first
    trie = await get_trie(db)
    results = trie.search_prefix(prefix, limit)

    if results:
        return results

    # Fallback: PostgreSQL trigram similarity search
    return await _trigram_search(prefix, db, limit)


async def _trigram_search(
    prefix: str, db: AsyncSession, limit: int
) -> list[dict]:
    """Fallback autocomplete using PostgreSQL pg_trgm extension."""
    sql = text("""
        SELECT term, frequency
        FROM autocomplete_terms
        WHERE term ILIKE :pattern
        ORDER BY frequency DESC, term ASC
        LIMIT :limit
    """)
    result = await db.execute(
        sql, {"pattern": f"{prefix}%", "limit": limit}
    )
    return [{"term": row.term, "frequency": row.frequency} for row in result]


async def record_query_term(query: str, db: AsyncSession):
    """Record a search query as an autocomplete term.

    Upserts the term, incrementing frequency if it already exists.
    """
    term = query.strip().lower()
    if not term or len(term) < 2:
        return

    stmt = pg_insert(AutocompleteTerm).values(
        term=term, frequency=1, source="query"
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["term"],
        set_={"frequency": AutocompleteTerm.frequency + 1},
    )
    await db.execute(stmt)
    await db.commit()

    # Invalidate trie so it picks up new terms
    rebuild_trie()


async def populate_from_titles(db: AsyncSession):
    """Populate autocomplete terms from document titles.

    Called during reindexing to ensure titles are available for completion.
    """
    from app.models.document import Document

    result = await db.execute(select(Document.title).where(Document.title.isnot(None)))
    titles = [row[0] for row in result.all() if row[0]]

    for title in titles:
        term = title.strip().lower()
        if len(term) < 2 or len(term) > 255:
            continue
        stmt = pg_insert(AutocompleteTerm).values(
            term=term, frequency=5, source="title"  # titles get higher base frequency
        )
        stmt = stmt.on_conflict_do_nothing()
        await db.execute(stmt)

    await db.commit()
    rebuild_trie()
    logger.info("Populated autocomplete with %d document titles", len(titles))
