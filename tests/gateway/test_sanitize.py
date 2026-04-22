import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

from services.sanitize import sanitize


def test_strips_html():
    assert sanitize("<b>Hello</b> world") == "Hello world"


def test_normalizes_whitespace():
    assert sanitize("  too   many   spaces  ") == "too many spaces"


def test_strips_script_tag():
    result = sanitize("<script>alert('xss')</script>fire drill policy")
    assert "<script>" not in result
    assert "fire drill policy" in result


def test_max_length():
    long_query = "a" * 600
    result = sanitize(long_query)
    assert len(result) == 512


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
    assert sanitize(q) == q
