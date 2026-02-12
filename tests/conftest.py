import pytest


@pytest.fixture
def sample_document():
    return {
        "url": "https://en.wikipedia.org/wiki/Search_engine",
        "title": "Search engine",
        "content": "A search engine is a software system designed to carry out web searches.",
    }
