import re
import logging
from html import unescape

from bs4 import BeautifulSoup

logger = logging.getLogger("hyperseek.indexer.text_processor")

# Lazy-loaded NLTK resources
_stopwords: set[str] | None = None
_stemmer = None


def _get_stopwords() -> set[str]:
    global _stopwords
    if _stopwords is None:
        try:
            from nltk.corpus import stopwords
            _stopwords = set(stopwords.words("english"))
        except LookupError:
            import nltk
            nltk.download("stopwords", quiet=True)
            from nltk.corpus import stopwords
            _stopwords = set(stopwords.words("english"))
    return _stopwords


def _get_stemmer():
    global _stemmer
    if _stemmer is None:
        try:
            from nltk.stem import PorterStemmer
            _stemmer = PorterStemmer()
        except LookupError:
            import nltk
            nltk.download("punkt_tab", quiet=True)
            from nltk.stem import PorterStemmer
            _stemmer = PorterStemmer()
    return _stemmer


class TextProcessor:
    """Handles all text transformation: HTML stripping, tokenization,
    stop word removal, and stemming.

    This is the core NLP pipeline that prepares text for both the
    inverted index (BM25) and embedding generation.
    """

    # Regex for tokenization: splits on non-alphanumeric characters
    TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")
    # Min token length to keep
    MIN_TOKEN_LENGTH = 2
    # Max token length (skip absurdly long strings)
    MAX_TOKEN_LENGTH = 50

    def html_to_text(self, html: str) -> str:
        """Strip HTML tags, scripts, styles and return clean text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Unescape HTML entities
        text = unescape(text)
        return text

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase tokens."""
        if not text:
            return []
        text_lower = text.lower()
        tokens = self.TOKEN_PATTERN.findall(text_lower)
        return [
            t
            for t in tokens
            if self.MIN_TOKEN_LENGTH <= len(t) <= self.MAX_TOKEN_LENGTH
        ]

    def remove_stopwords(self, tokens: list[str]) -> list[str]:
        """Remove English stop words from token list."""
        stops = _get_stopwords()
        return [t for t in tokens if t not in stops]

    def stem(self, tokens: list[str]) -> list[str]:
        """Apply Porter stemming to tokens."""
        stemmer = _get_stemmer()
        return [stemmer.stem(t) for t in tokens]

    def process(self, text: str, stem: bool = True) -> list[str]:
        """Full pipeline: tokenize -> remove stopwords -> stem.

        Returns processed tokens ready for indexing.
        """
        tokens = self.tokenize(text)
        tokens = self.remove_stopwords(tokens)
        if stem:
            tokens = self.stem(tokens)
        return tokens

    def process_with_positions(self, text: str) -> list[tuple[str, int]]:
        """Tokenize and return (processed_token, original_position) pairs.

        Positions refer to the word's index in the original text,
        useful for phrase queries and snippet highlighting.
        """
        raw_tokens = self.tokenize(text)
        stops = _get_stopwords()
        stemmer = _get_stemmer()
        result = []
        for pos, token in enumerate(raw_tokens):
            if token not in stops:
                stemmed = stemmer.stem(token)
                result.append((stemmed, pos))
        return result
