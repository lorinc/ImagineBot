import sys
import os

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Allow importing from src/channel_web
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/channel_web"))

import main  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    """TestClient with static + template dirs pointing at real assets."""
    static_dir   = os.path.join(os.path.dirname(__file__), "../../src/channel_web/static")
    template_dir = os.path.join(os.path.dirname(__file__), "../../src/channel_web/templates")

    main.app.state_static   = static_dir
    main.templates          = main.Jinja2Templates(directory=template_dir)

    # Mount static with real path so TestClient can find files
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


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Montessori" in resp.text


@patch("main._get_identity_token", return_value="test-token")
def test_chat_proxies_to_knowledge_service(mock_token, authed_client):
    client = authed_client
    knowledge_response = {
        "answer": "School starts at 8:30 AM.",
        "facts": [{"fact": "School starts at 8:30 AM.", "source_id": "family-manual", "valid_at": None}],
    }

    with patch("main.httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = knowledge_response
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__  = AsyncMock(return_value=False)

        resp = client.post("/chat", json={"message": "What time does school start?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "School starts at 8:30 AM."
    assert len(data["facts"]) == 1
    assert data["facts"][0]["source_id"] == "family-manual"

    # Assert query forwarded correctly
    mock_http.post.assert_called_once()
    call_kwargs = mock_http.post.call_args
    assert call_kwargs.kwargs["json"]["query"] == "What time does school start?"
    assert call_kwargs.kwargs["json"]["group_ids"] is None
    assert "Bearer test-token" in call_kwargs.kwargs["headers"]["Authorization"]


@patch("main._get_identity_token", return_value="test-token")
def test_chat_error_from_knowledge_service_returns_502(mock_token, authed_client):
    client = authed_client
    import httpx as real_httpx

    with patch("main.httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(
            side_effect=real_httpx.HTTPStatusError(
                "500", request=MagicMock(), response=mock_resp
            )
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__  = AsyncMock(return_value=False)

        resp = client.post("/chat", json={"message": "test"})

    assert resp.status_code == 502
    assert "error" in resp.json()


@patch("main._get_identity_token", return_value="test-token")
def test_chat_connection_error_returns_500(mock_token, authed_client):
    client = authed_client
    with patch("main.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__  = AsyncMock(return_value=False)

        resp = client.post("/chat", json={"message": "test"})

    assert resp.status_code == 500
    assert "error" in resp.json()


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
    with patch("main.ALLOWED_EMAILS", ["allowed@example.com"]):
        knowledge_response = {
            "answer": "School starts at 9 AM.",
            "facts": [{"fact": "School starts at 9 AM.", "source_id": "family-manual", "valid_at": None}],
        }
        with patch("main.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = knowledge_response
            mock_resp.raise_for_status = MagicMock()

            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_client_cls.return_value.__aexit__  = AsyncMock(return_value=False)

            resp = client.post("/chat", json={"message": "hi"},
                               headers={"Authorization": "Bearer valid-token"})

    assert resp.status_code == 200
    assert resp.json()["answer"] == "School starts at 9 AM."
