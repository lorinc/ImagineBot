import json
import sys
import os

import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Allow importing from src/channel_web
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/channel_web"))

import main  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_sse_events(text):
    """Parse SSE stream text into list of {type, data} dicts."""
    events = []
    for block in text.split('\n\n'):
        if not block.strip():
            continue
        event_type = 'message'
        data = None
        for line in block.split('\n'):
            if line.startswith('event: '):
                event_type = line[7:].strip()
            elif line.startswith('data: '):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        if data is not None:
            events.append({'type': event_type, 'data': data})
    return events


def make_sse_stream_mock(sse_lines):
    """
    Build a patch target for httpx.AsyncClient that streams the given SSE lines.
    sse_lines: list of strings (lines without trailing newline; empty string = blank line).
    Returns (mock_cls, stream_calls) where stream_calls is populated after use.
    """
    stream_calls = []

    async def _aiter_lines():
        for line in sse_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.aiter_lines = _aiter_lines

    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        stream_calls.append({'args': args, 'kwargs': kwargs})
        yield mock_resp

    mock_http = MagicMock()
    mock_http.stream = _stream_ctx

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_cls, stream_calls


def make_sse_error_mock(exception):
    """Build a patch target for httpx.AsyncClient whose stream() raises exception."""
    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        raise exception
        yield  # noqa: unreachable — required to make this an async generator

    mock_http = MagicMock()
    mock_http.stream = _stream_ctx

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_cls


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path):
    """TestClient with static + template dirs pointing at real assets."""
    static_dir   = os.path.join(os.path.dirname(__file__), "../../src/channel_web/static")
    template_dir = os.path.join(os.path.dirname(__file__), "../../src/channel_web/templates")

    main.app.state_static   = static_dir
    main.templates          = main.Jinja2Templates(directory=template_dir)

    from fastapi.staticfiles import StaticFiles
    main.app.mount("/static", StaticFiles(directory=static_dir), name="static")

    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def authed_client(client):
    """TestClient with auth dependency bypassed (for testing /chat business logic)."""
    async def _mock_user():
        return {"email": "test@example.com"}

    main.app.dependency_overrides[main._get_current_user] = _mock_user
    yield client
    main.app.dependency_overrides.clear()


# ── Basic routes ──────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Montessori" in resp.text


# ── /chat streaming ───────────────────────────────────────────────────────────

@patch("main._get_identity_token", return_value="test-token")
def test_chat_proxies_to_knowledge_service(mock_token, authed_client):
    knowledge_response = {
        "answer": "School starts at 8:30 AM.",
        "facts": [{"fact": "School starts at 8:30 AM.", "source_id": "family-manual", "valid_at": None}],
    }
    sse_lines = [
        'event: progress', 'data: {"key": "cache_lookup"}', '',
        'event: answer', f'data: {json.dumps(knowledge_response)}', '',
    ]
    mock_cls, stream_calls = make_sse_stream_mock(sse_lines)

    with patch("main.httpx.AsyncClient", mock_cls):
        resp = authed_client.post("/chat", json={"message": "What time does school start?"})

    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    answer_events = [e for e in events if e['type'] == 'answer']
    assert len(answer_events) == 1
    assert answer_events[0]['data']['answer'] == "School starts at 8:30 AM."
    assert answer_events[0]['data']['facts'][0]['source_id'] == "family-manual"

    # Assert message forwarded correctly to gateway
    assert len(stream_calls) == 1
    call = stream_calls[0]
    assert call['kwargs']['json']['message'] == "What time does school start?"
    assert "Bearer test-token" in call['kwargs']['headers']['Authorization']


@patch("main._get_identity_token", return_value="test-token")
def test_chat_error_from_knowledge_service_emits_error_event(mock_token, authed_client):
    import httpx as real_httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    exc = real_httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
    mock_cls = make_sse_error_mock(exc)

    with patch("main.httpx.AsyncClient", mock_cls):
        resp = authed_client.post("/chat", json={"message": "test"})

    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    error_events = [e for e in events if e['type'] == 'error']
    assert len(error_events) == 1
    assert "error" in error_events[0]['data']


@patch("main._get_identity_token", return_value="test-token")
def test_chat_connection_error_emits_error_event(mock_token, authed_client):
    mock_cls = make_sse_error_mock(Exception("timeout"))

    with patch("main.httpx.AsyncClient", mock_cls):
        resp = authed_client.post("/chat", json={"message": "test"})

    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    error_events = [e for e in events if e['type'] == 'error']
    assert len(error_events) == 1
    assert "error" in error_events[0]['data']


@patch("main._get_identity_token", return_value="test-token")
def test_chat_emits_progress_events_before_answer(mock_token, authed_client):
    knowledge_response = {"answer": "9 AM.", "facts": []}
    sse_lines = [
        'event: progress', 'data: {"key": "querying_ai"}', '',
        'event: answer', f'data: {json.dumps(knowledge_response)}', '',
    ]
    mock_cls, _ = make_sse_stream_mock(sse_lines)

    with patch("main.httpx.AsyncClient", mock_cls):
        resp = authed_client.post("/chat", json={"message": "start time?"})

    events = parse_sse_events(resp.text)
    types = [e['type'] for e in events]

    # progress events must precede answer
    assert 'answer' in types
    assert types.index('progress') < types.index('answer')


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_chat_rejects_missing_token(client):
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 401


@patch("main._verify_google_token", side_effect=Exception("invalid token"))
def test_chat_rejects_invalid_token(mock_verify, client):
    resp = client.post("/chat", json={"message": "hi"},
                       headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401


@patch("main._verify_google_token", return_value={"email": "other@example.com"})
def test_chat_rejects_unlisted_email(mock_verify, client):
    with patch("main.ALLOWED_EMAILS", ["allowed@example.com"]):
        resp = client.post("/chat", json={"message": "hi"},
                           headers={"Authorization": "Bearer valid-token"})
    assert resp.status_code == 403


@patch("main._get_identity_token", return_value="sa-token")
@patch("main._verify_google_token", return_value={"email": "allowed@example.com"})
def test_chat_accepts_valid_token_and_listed_email(mock_verify, mock_sa_token, client):
    knowledge_response = {
        "answer": "School starts at 9 AM.",
        "facts": [{"fact": "School starts at 9 AM.", "source_id": "family-manual", "valid_at": None}],
    }
    sse_lines = [
        'event: answer', f'data: {json.dumps(knowledge_response)}', '',
    ]
    mock_cls, _ = make_sse_stream_mock(sse_lines)

    with patch("main.ALLOWED_EMAILS", ["allowed@example.com"]):
        with patch("main.httpx.AsyncClient", mock_cls):
            resp = client.post("/chat", json={"message": "hi"},
                               headers={"Authorization": "Bearer valid-token"})

    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    answer_events = [e for e in events if e['type'] == 'answer']
    assert answer_events[0]['data']['answer'] == "School starts at 9 AM."
