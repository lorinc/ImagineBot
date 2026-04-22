import re

_MAX_LEN = 512
_HTML_TAG = re.compile(r"<[^>]+>")
# Strip the entire content of script/style blocks, not just their tags
_SCRIPT_BLOCK = re.compile(r"<(script|style)[^>]*>.*?</(script|style)>", re.IGNORECASE | re.DOTALL)

_INJECTION_WARNING = (
    "This input has been identified as a code injection attempt and has been recorded. "
    "Reason: HTML tags detected in query. Your question has been answered using the sanitized input."
)


def sanitize(text: str) -> tuple[str, str | None]:
    """Strip HTML tags, normalize whitespace, enforce max length.

    Returns (cleaned_text, warning) where warning is set when HTML tags were detected.
    Raises ValueError if the result after stripping is empty.
    """
    text = text or ""
    warning = None
    if _HTML_TAG.search(text):
        warning = _INJECTION_WARNING
        text = _SCRIPT_BLOCK.sub("", text)   # remove <script>...</script> content entirely
        text = _HTML_TAG.sub("", text)        # strip remaining tags, keep their text
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("Query cannot be empty")
    return text[:_MAX_LEN], warning
