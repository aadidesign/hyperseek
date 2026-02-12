"""Tests for the text processing pipeline."""

from app.services.indexer.text_processor import TextProcessor


def test_html_to_text_strips_tags():
    tp = TextProcessor()
    html = "<h1>Hello</h1><p>World</p><script>evil()</script>"
    result = tp.html_to_text(html)
    assert "Hello" in result
    assert "World" in result
    assert "evil" not in result
    assert "<h1>" not in result


def test_html_to_text_empty_input():
    tp = TextProcessor()
    assert tp.html_to_text("") == ""
    assert tp.html_to_text(None) == ""


def test_tokenize_basic():
    tp = TextProcessor()
    tokens = tp.tokenize("Hello World! This is a Test-123.")
    assert "hello" in tokens
    assert "world" in tokens
    assert "test" in tokens
    assert "123" in tokens


def test_tokenize_filters_short_tokens():
    tp = TextProcessor()
    tokens = tp.tokenize("I a am ok fine")
    assert "i" not in tokens
    assert "a" not in tokens
    assert "am" in tokens
    assert "ok" in tokens
    assert "fine" in tokens


def test_remove_stopwords():
    tp = TextProcessor()
    tokens = ["the", "search", "engine", "is", "very", "fast"]
    filtered = tp.remove_stopwords(tokens)
    assert "the" not in filtered
    assert "is" not in filtered
    assert "search" in filtered
    assert "engine" in filtered
    assert "fast" in filtered


def test_stem():
    tp = TextProcessor()
    tokens = ["running", "searched", "engines", "processing"]
    stemmed = tp.stem(tokens)
    assert "run" in stemmed
    assert "search" in stemmed
    assert "engin" in stemmed
    assert "process" in stemmed


def test_process_full_pipeline():
    tp = TextProcessor()
    text = "The search engine is processing queries very quickly."
    result = tp.process(text)
    # Should not contain stopwords
    assert "the" not in result
    assert "is" not in result
    # Should contain stemmed content words
    assert any("search" in t for t in result)
    assert any("engin" in t for t in result)
    assert any("queri" in t for t in result)


def test_process_with_positions():
    tp = TextProcessor()
    text = "search engine optimization techniques"
    result = tp.process_with_positions(text)
    # Should return (token, position) tuples
    assert len(result) > 0
    tokens = [t for t, p in result]
    positions = [p for t, p in result]
    # Positions should be sequential
    for i in range(1, len(positions)):
        assert positions[i] >= positions[i - 1]


def test_html_strips_nav_footer():
    tp = TextProcessor()
    html = "<nav>Menu</nav><main>Content here</main><footer>Copyright</footer>"
    result = tp.html_to_text(html)
    assert "Menu" not in result
    assert "Copyright" not in result
    assert "Content" in result
