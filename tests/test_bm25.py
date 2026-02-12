"""Tests for BM25 search logic (unit tests, no DB required)."""

from app.services.search.bm25 import _generate_snippet, highlight_terms


def test_generate_snippet_with_match():
    content = "This is a long document about search engines. " * 20
    snippet = _generate_snippet(content, ["search"])
    assert "search" in snippet.lower()
    assert len(snippet) <= 300  # max_length + prefix/suffix


def test_generate_snippet_no_match():
    content = "This document has no matching terms at all."
    snippet = _generate_snippet(content, ["xyz123"])
    # Should return start of content
    assert snippet.startswith("This document")


def test_generate_snippet_empty():
    assert _generate_snippet("", ["test"]) == ""


def test_highlight_terms():
    text = "The search engine processes queries fast"
    result = highlight_terms(text, ["search", "fast"])
    assert "<mark>search</mark>" in result
    assert "<mark>fast</mark>" in result
    assert "engine" in result  # non-matching words untouched


def test_highlight_empty():
    assert highlight_terms("", ["test"]) == ""
    assert highlight_terms("hello", []) == "hello"
