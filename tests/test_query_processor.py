"""Tests for query processing."""

from app.services.search.query_processor import process_query


def test_process_query_basic():
    result = process_query("search engine architecture")
    assert result["original"] == "search engine architecture"
    assert result["cleaned"] == "search engine architecture"
    assert len(result["tokens"]) > 0
    assert len(result["raw_tokens"]) > 0
    assert result["cache_key"]  # non-empty hash


def test_process_query_whitespace():
    result = process_query("  hello   world  ")
    assert result["cleaned"] == "hello world"


def test_process_query_deterministic_cache():
    r1 = process_query("search engine")
    r2 = process_query("search engine")
    assert r1["cache_key"] == r2["cache_key"]


def test_process_query_different_queries():
    r1 = process_query("search engine")
    r2 = process_query("database optimization")
    assert r1["cache_key"] != r2["cache_key"]
