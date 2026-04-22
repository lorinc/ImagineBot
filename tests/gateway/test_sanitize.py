import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

from services.sanitize import sanitize


def test_strips_html_and_warns():
    text, warning = sanitize("<b>Hello</b> world")
    assert text == "Hello world"
    assert warning is not None
    assert "code injection attempt" in warning


def test_normalizes_whitespace():
    text, warning = sanitize("  too   many   spaces  ")
    assert text == "too many spaces"
    assert warning is None


def test_strips_script_tag_and_warns():
    text, warning = sanitize("<script>alert('xss')</script>fire drill policy")
    assert "alert" not in text          # script content removed, not just tags
    assert "fire drill policy" in text
    assert warning is not None
    assert "code injection attempt" in warning


def test_max_length():
    long_query = "a" * 600
    text, _ = sanitize(long_query)
    assert len(text) == 512


def test_empty_raises():
    with pytest.raises(ValueError):
        sanitize("")


def test_only_html_raises():
    with pytest.raises(ValueError):
        sanitize("<br><br>")


def test_only_whitespace_raises():
    with pytest.raises(ValueError):
        sanitize("   ")


def test_valid_query_passthrough():
    q = "What is the fire evacuation procedure?"
    text, warning = sanitize(q)
    assert text == q
    assert warning is None
