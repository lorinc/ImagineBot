import re

_MAX_LEN = 512
_HTML_TAG = re.compile(r"<[^>]+>")


def sanitize(text: str) -> str:
    """Strip HTML tags, normalize whitespace, enforce max length.

    Raises ValueError if the result is empty.
    """
    text = _HTML_TAG.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("Query cannot be empty")
    return text[:_MAX_LEN]
