"""Contract tests for the gateway service API boundary.

Imports directly from src/gateway/models.py via importlib so that running
all contract tests in one pytest invocation does not cause sys.modules
collisions between services that share the module name 'models'.

A field rename or removal breaks this test immediately — that is the intent.
Do not relax assertions to make a test pass; fix the code or update the
contract intentionally.
"""
import importlib.util
import os

_path = os.path.join(os.path.dirname(__file__), "../../src/gateway/models.py")
_spec = importlib.util.spec_from_file_location("gateway.models", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ChatRequest = _mod.ChatRequest
FeedbackRequest = _mod.FeedbackRequest


# ---------------------------------------------------------------------------
# POST /chat — request
# ---------------------------------------------------------------------------

def test_chat_request_has_message():
    assert "message" in ChatRequest.model_fields


def test_chat_request_has_session_id():
    assert "session_id" in ChatRequest.model_fields


def test_chat_request_session_id_optional():
    req = ChatRequest(message="hello")
    assert req.session_id is None


# ---------------------------------------------------------------------------
# POST /feedback — request
# ---------------------------------------------------------------------------

def test_feedback_request_has_trace_id():
    assert "trace_id" in FeedbackRequest.model_fields


def test_feedback_request_has_rating():
    assert "rating" in FeedbackRequest.model_fields


def test_feedback_request_has_comment():
    assert "comment" in FeedbackRequest.model_fields


def test_feedback_request_comment_optional():
    req = FeedbackRequest(trace_id="abc", rating=1)
    assert req.comment is None
