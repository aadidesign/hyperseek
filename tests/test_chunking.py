"""Tests for document chunking."""

from app.services.indexer.vector_indexer import chunk_text


def test_chunk_short_text():
    text = "This is a short text."
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_long_text():
    words = ["word"] * 200
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=10)
    assert len(chunks) > 1
    # Each chunk should be at most ~50 words
    for chunk in chunks:
        assert len(chunk.split()) <= 50


def test_chunk_overlap():
    words = [f"w{i}" for i in range(100)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=30, chunk_overlap=10)
    # Check that consecutive chunks share some words
    if len(chunks) >= 2:
        first_words = set(chunks[0].split())
        second_words = set(chunks[1].split())
        overlap = first_words & second_words
        assert len(overlap) > 0, "Chunks should have overlapping words"


def test_chunk_empty():
    assert chunk_text("") == []
    assert chunk_text("", chunk_size=10) == []
