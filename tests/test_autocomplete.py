"""Tests for the autocomplete trie."""

from app.services.autocomplete import AutocompleteTrie


def test_trie_insert_and_search():
    trie = AutocompleteTrie()
    trie.insert("search engine", 10)
    trie.insert("search optimization", 5)
    trie.insert("sorting algorithms", 3)

    results = trie.search_prefix("search")
    assert len(results) == 2
    assert results[0]["term"] == "search engine"  # higher frequency first
    assert results[1]["term"] == "search optimization"


def test_trie_no_match():
    trie = AutocompleteTrie()
    trie.insert("hello world", 1)
    results = trie.search_prefix("xyz")
    assert results == []


def test_trie_case_insensitive():
    trie = AutocompleteTrie()
    trie.insert("Python Programming", 5)
    results = trie.search_prefix("python")
    assert len(results) == 1
    assert results[0]["term"] == "Python Programming"


def test_trie_limit():
    trie = AutocompleteTrie()
    for i in range(20):
        trie.insert(f"test term {i}", i)
    results = trie.search_prefix("test", limit=5)
    assert len(results) == 5


def test_trie_frequency_ordering():
    trie = AutocompleteTrie()
    trie.insert("apple", 1)
    trie.insert("application", 10)
    trie.insert("app store", 5)

    results = trie.search_prefix("app")
    assert results[0]["term"] == "application"
    assert results[1]["term"] == "app store"
    assert results[2]["term"] == "apple"


def test_trie_size():
    trie = AutocompleteTrie()
    assert trie.size == 0
    trie.insert("a", 1)
    trie.insert("b", 1)
    assert trie.size == 2
