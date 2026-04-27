"""Smoke test for the full gateway /chat endpoint with mocked dependencies."""
import sys
import os
import json
import pytest
import unittest.mock as mock
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

# Mock vertexai.init before importing main to avoid credential requirement
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
    "selected_nodes": ["node1"],
}

_NO_EVIDENCE_RESULT = {
    "answer": "Some answer the LLM hallucinated.",
    "facts": [{"fact": "Spurious fact", "source_id": "policy1", "valid_at": None}],
    "selected_nodes": [],
}

# classify returns (in_scope, specific_enough)
_IN_SCOPE = (True, True)
_OUT_OF_SCOPE = (False, True)
_NOT_SPECIFIC = (True, False)


def _make_search_stream(result=None):
    """Return an async generator that yields a single answer event."""
    payload = result if result is not None else _KNOWLEDGE_RESULT

    async def _gen(*args, **kwargs):
        yield ("answer", payload, "test-version")

    return _gen


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_valid_school_question_returns_answer(client):
    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_IN_SCOPE),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream()),
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
    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_OUT_OF_SCOPE),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
    ):
        resp = client.post("/chat", json={"message": "How do I bake a cake?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert "school policies" in answer_events[0]["data"]["answer"]
    assert answer_events[0]["data"]["facts"] == []


def test_vague_question_returns_orientation(client):
    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_NOT_SPECIFIC),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
    ):
        resp = client.post("/chat", json={"message": "What are the rules?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0]["data"]["facts"] == []
    # orientation response should prompt user to be more specific
    assert "?" in answer_events[0]["data"]["answer"]


def test_empty_message_returns_error(client):
    resp = client.post("/chat", json={"message": "   "})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1


def test_broad_query_triggers_overview_mode(client):
    # 6 topics across 6 different docs — exceeds MAX_TOPIC_PATHS=5 after consolidation
    many_topics = [
        {"doc_id": f"doc_{i}", "id": "1", "title": f"Topic {i}"}
        for i in range(6)
    ]
    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured.update(kwargs)
        yield ("answer", _KNOWLEDGE_RESULT, "test-version")

    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_IN_SCOPE),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=many_topics),
        patch("services.knowledge_client.search_stream", _capture_stream),
    ):
        resp = client.post("/chat", json={"message": "What are all the school rules?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    # search_stream must be called with overview=True
    assert captured.get("overview") is True
    # answer should be prefixed with broad-query text
    assert "overview" in answer_events[0]["data"]["answer"].lower()


def test_expired_session_drops_history(client):
    import routers.chat as chat_mod
    import time

    # Manually insert a stale session
    stale_session_id = "stale-session-001"
    chat_mod._sessions[stale_session_id] = {
        "turns": [{"q": "old question", "a": "old answer"}],
        "last_active": time.monotonic() - chat_mod._SESSION_TTL - 1,
    }
    chat_mod._evict_expired_sessions()
    assert stale_session_id not in chat_mod._sessions


def test_session_id_persists_across_requests(client):
    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_IN_SCOPE),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream()),
    ):
        resp1 = client.post("/chat", json={"message": "What is the fire drill procedure?"})
        events1 = parse_sse(resp1.text)
        session_id = next(e["data"]["session_id"] for e in events1 if e["type"] == "answer")

        with patch("routers.chat.rewrite_standalone", new_callable=AsyncMock, return_value="What about students in the fire drill?") as mock_rewrite:
            resp2 = client.post("/chat", json={"message": "What about students?", "session_id": session_id})
            mock_rewrite.assert_called_once()

    assert resp2.status_code == 200
    events2 = parse_sse(resp2.text)
    answer2 = next(e["data"] for e in events2 if e["type"] == "answer")
    assert answer2["session_id"] == session_id


def test_gate1_override_bypasses_classify_and_retries_prior_query(client):
    """Prior OOS + trigger phrase → classify not called, prior query retried."""
    import routers.chat as chat_mod
    import time

    session_id = "override-test-001"
    prior_query = "What time does school start?"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "out_of_scope",
        "last_query": prior_query,
    }

    mock_classify = AsyncMock(return_value=_IN_SCOPE)

    with (
        patch("routers.chat.classify", mock_classify),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream()),
    ):
        resp = client.post("/chat", json={"message": "look it up", "session_id": session_id})

    assert resp.status_code == 200
    mock_classify.assert_not_called()
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0]["data"]["answer"]


def test_gate1_override_does_not_fire_without_prior_oos(client):
    """No prior OOS in session → trigger phrase goes through normal classify."""
    import routers.chat as chat_mod
    import time

    session_id = "override-test-002"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "specific",
        "last_query": "What time does school start?",
    }

    mock_classify = AsyncMock(return_value=_OUT_OF_SCOPE)

    with (
        patch("routers.chat.classify", mock_classify),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
    ):
        resp = client.post("/chat", json={"message": "just check", "session_id": session_id})

    assert resp.status_code == 200
    mock_classify.assert_called_once()
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert "school policies" in answer_events[0]["data"]["answer"]


def test_gate1_override_does_not_fire_for_long_message(client):
    """Prior OOS but message > 14 words → no override, classify called normally."""
    import routers.chat as chat_mod
    import time

    session_id = "override-test-003"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "out_of_scope",
        "last_query": "What time does school start?",
    }

    mock_classify = AsyncMock(return_value=_IN_SCOPE)

    with (
        patch("routers.chat.classify", mock_classify),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream()),
    ):
        long_msg = "Actually I was asking about something that is definitely a school topic so please check"
        resp = client.post("/chat", json={"message": long_msg, "session_id": session_id})

    assert resp.status_code == 200
    mock_classify.assert_called_once()


def test_gate1_override_does_not_fire_for_unrelated_message(client):
    """Prior OOS but message has no trigger phrase → no override, classify called normally."""
    import routers.chat as chat_mod
    import time

    session_id = "override-test-004"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "out_of_scope",
        "last_query": "What time does school start?",
    }

    mock_classify = AsyncMock(return_value=_OUT_OF_SCOPE)

    with (
        patch("routers.chat.classify", mock_classify),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
    ):
        resp = client.post("/chat", json={"message": "How do I bake a cake?", "session_id": session_id})

    assert resp.status_code == 200
    mock_classify.assert_called_once()


def test_no_evidence_returns_canned_reply(client):
    with (
        patch("routers.chat.classify", new_callable=AsyncMock, return_value=_IN_SCOPE),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream(_NO_EVIDENCE_RESULT)),
    ):
        resp = client.post("/chat", json={"message": "What is the fee schedule?"})

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    data = answer_events[0]["data"]
    assert "contact the school office" in data["answer"]
    assert data["facts"] == []


def test_gate3a_override_active_calls_fallback_not_canned(client):
    """Override active + no selected_nodes → fallback_reply called; NO_EVIDENCE_REPLY not yielded."""
    import routers.chat as chat_mod
    import time

    session_id = "gate3a-fallback-001"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "out_of_scope",
        "last_query": "What is the fee schedule?",
    }

    mock_fallback = AsyncMock(return_value="I searched but found nothing. I can look up the right contact person for fees if you'd like.")

    with (
        patch("routers.chat.fallback_reply", mock_fallback),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream(_NO_EVIDENCE_RESULT)),
    ):
        resp = client.post("/chat", json={"message": "look it up", "session_id": session_id})

    assert resp.status_code == 200
    mock_fallback.assert_called_once()
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    data = answer_events[0]["data"]
    assert "contact the school office" not in data["answer"]
    assert data["facts"] == []


def test_gate3b_override_active_empty_synthesis_calls_fallback(client):
    """Override active + nodes selected but empty synthesis → fallback_reply called."""
    import routers.chat as chat_mod
    import time

    session_id = "gate3b-fallback-001"
    chat_mod._sessions[session_id] = {
        "turns": [],
        "last_active": time.monotonic(),
        "last_pipeline_path": "out_of_scope",
        "last_query": "What is the uniform policy?",
    }

    empty_synthesis_result = {
        "answer": "",
        "facts": [],
        "selected_nodes": ["node1"],
    }

    mock_fallback = AsyncMock(return_value="The search found some sections but couldn't extract an answer. I can look up who to contact about this.")

    with (
        patch("routers.chat.fallback_reply", mock_fallback),
        patch("services.knowledge_client.get_summary", new_callable=AsyncMock, return_value=""),
        patch("services.knowledge_client.get_topics", new_callable=AsyncMock, return_value=[]),
        patch("services.knowledge_client.search_stream", _make_search_stream(empty_synthesis_result)),
    ):
        resp = client.post("/chat", json={"message": "check", "session_id": session_id})

    assert resp.status_code == 200
    mock_fallback.assert_called_once()
    events = parse_sse(resp.text)
    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0]["data"]["facts"] == []
