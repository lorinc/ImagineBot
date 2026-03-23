import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "europe-west1")


@pytest.fixture(autouse=True)
def patch_vertexai_init():
    with patch("src.knowledge.main.vertexai.init"):
        yield


@pytest.fixture(autouse=True)
def patch_firestore():
    with patch("src.knowledge.main.firestore.Client") as MockFirestore:
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {"cache_name": "projects/test/cachedContents/test-cache"}
        instance = MagicMock()
        instance.collection.return_value.document.return_value.get.return_value = doc
        MockFirestore.return_value = instance
        yield instance


@pytest.fixture(autouse=True)
def reset_cache_globals():
    """Ensure in-memory Firestore cache is cleared between tests."""
    import src.knowledge.main as m
    m._cache_name = None
    m._cache_checked_at = None
    yield
    m._cache_name = None
    m._cache_checked_at = None


@pytest.fixture()
def mock_cached_content():
    with patch("src.knowledge.main.CachedContent") as MockCC:
        MockCC.get.return_value = MagicMock()
        yield MockCC


def _make_model_mock(answer: str, citations: list[dict]) -> MagicMock:
    response = MagicMock()
    response.text = json.dumps({"answer": answer, "citations": citations})
    instance = MagicMock()
    instance.generate_content_async = AsyncMock(return_value=response)
    return instance


@pytest.fixture()
def mock_model():
    with patch("src.knowledge.main.GenerativeModel") as MockModel:  # patches vertexai.preview.generative_models.GenerativeModel
        MockModel.from_cached_content.return_value = _make_model_mock(
            answer="School starts at 9:00.",
            citations=[{"document": "en_family_manual_24_25", "excerpt": "School starts at 9:00."}],
        )
        yield MockModel


@pytest.fixture()
def client(mock_cached_content, mock_model):
    from src.knowledge.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_search_returns_expected_shape(client):
    resp = client.post("/search", json={"query": "When does school start?", "group_ids": None})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "School starts at 9:00."
    assert len(body["facts"]) == 1
    assert body["facts"][0]["fact"] == "School starts at 9:00."
    assert body["facts"][0]["source_id"] == "en_family_manual_24_25"
    assert body["facts"][0]["valid_at"] is None


def test_group_ids_appended_to_query(client, mock_model):
    client.post("/search", json={"query": "anything", "group_ids": ["en_policy1_child_protection"]})

    generate_call_args = mock_model.from_cached_content.return_value.generate_content_async.call_args
    query_sent = generate_call_args.args[0]
    assert "en_policy1_child_protection" in query_sent
    assert "Answer only from these documents" in query_sent


def test_no_group_ids_sends_bare_query(client, mock_model):
    client.post("/search", json={"query": "anything", "group_ids": None})

    generate_call_args = mock_model.from_cached_content.return_value.generate_content_async.call_args
    query_sent = generate_call_args.args[0]
    assert query_sent == "anything"


def test_empty_citations_returns_i_dont_know(client, mock_model):
    mock_model.from_cached_content.return_value = _make_model_mock(
        answer="I don't have that information in the school documents.",
        citations=[],
    )

    resp = client.post("/search", json={"query": "capital of France", "group_ids": None})

    assert resp.status_code == 200
    body = resp.json()
    assert "I don't have that information" in body["answer"]
    assert body["facts"] == []


def test_search_returns_503_when_no_cache_in_firestore(patch_firestore, mock_cached_content, mock_model):
    patch_firestore.collection.return_value.document.return_value.get.return_value = MagicMock(
        exists=False
    )

    from src.knowledge.main import app
    with TestClient(app) as c:
        resp = c.post("/search", json={"query": "anything", "group_ids": None})

    assert resp.status_code == 503
    assert "create_cache.py" in resp.json()["detail"]
