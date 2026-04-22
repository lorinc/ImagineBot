"""Smoke test for the full gateway /chat endpoint with mocked dependencies."""
import sys
import os
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

# Mock vertexai.init before importing main to avoid credential requirement
import unittest.mock as mock
with mock.patch("vertexai.init"):
    import main  # noqa: E402


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        if data is not None:
            events.append({"type": event_type, "data": data})
    return events


_KNOWLEDGE_RESULT = {
    "answer": "After a fire drill, staff must complete a personnel headcount.",
    "facts": [{"fact": "Personnel check", "source_id": "policy1", "valid_at": None}],
}


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_valid_school_question_returns_answer(client):
    with (
        patch("routers.chat.is_in_scope", new_callable=AsyncMock, return_value=True),
        patch("services.knowledge_client.search", new_callable=AsyncMock, return_value=_KNOWLEDGE_RESULT),
    ):
        resp = client.post("/chat", json={"message": "What happens after a fire drill?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    data = answer_events[0]["data"]
    assert data["answer"]
    assert isinstance(data["facts"], list)
    assert data["session_id"]


def test_out_of_scope_returns_refusal(client):
    with patch("routers.chat.is_in_scope", new_callable=AsyncMock, return_value=False):
        resp = client.post("/chat", json={"message": "How do I bake a cake?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert "school policies" in answer_events[0]["data"]["answer"]
    assert answer_events[0]["data"]["facts"] == []


def test_empty_message_returns_error(client):
    resp = client.post("/chat", json={"message": "   "})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1


def test_session_id_persists_across_requests(client):
    with (
        patch("routers.chat.is_in_scope", new_callable=AsyncMock, return_value=True),
        patch("services.knowledge_client.search", new_callable=AsyncMock, return_value=_KNOWLEDGE_RESULT),
    ):
        resp1 = client.post("/chat", json={"message": "What is the fire drill procedure?"})
        events1 = parse_sse(resp1.text)
        session_id = next(e["data"]["session_id"] for e in events1 if e["type"] == "answer")

        with patch("routers.chat.rewrite_standalone", new_callable=AsyncMock, return_value="What about students in the fire drill?") as mock_rewrite:
            resp2 = client.post("/chat", json={"message": "What about students?", "session_id": session_id})
            # assert inside the with block while mock is still active
            mock_rewrite.assert_called_once()

    assert resp2.status_code == 200
    events2 = parse_sse(resp2.text)
    answer2 = next(e["data"] for e in events2 if e["type"] == "answer")
    assert answer2["session_id"] == session_id
