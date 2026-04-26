"""Contract tests for the knowledge service API boundary.

Imports directly from src/knowledge/models.py via importlib so that running
all contract tests in one pytest invocation does not cause sys.modules
collisions between services that share the module name 'models'.

A field rename or removal breaks this test immediately — that is the intent.
Do not relax assertions to make a test pass; fix the code or update the
contract intentionally.
"""
import importlib.util
import os

_path = os.path.join(os.path.dirname(__file__), "../../src/knowledge/models.py")
_spec = importlib.util.spec_from_file_location("knowledge.models", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SearchRequest = _mod.SearchRequest
SearchResponse = _mod.SearchResponse
Fact = _mod.Fact
TopicsRequest = _mod.TopicsRequest
TopicsResponse = _mod.TopicsResponse
TopicNode = _mod.TopicNode


# ---------------------------------------------------------------------------
# POST /search — request
# ---------------------------------------------------------------------------

def test_search_request_has_query():
    assert "query" in SearchRequest.model_fields


def test_search_request_has_group_ids():
    assert "group_ids" in SearchRequest.model_fields


def test_search_request_has_overview():
    assert "overview" in SearchRequest.model_fields


def test_search_request_group_ids_optional():
    req = SearchRequest(query="test")
    assert req.group_ids is None


def test_search_request_overview_defaults_false():
    req = SearchRequest(query="test")
    assert req.overview is False


# ---------------------------------------------------------------------------
# POST /search — response / Fact
# ---------------------------------------------------------------------------

def test_fact_has_fact():
    assert "fact" in Fact.model_fields


def test_fact_has_source_id():
    assert "source_id" in Fact.model_fields


def test_fact_has_valid_at():
    assert "valid_at" in Fact.model_fields


def test_fact_valid_at_defaults_none():
    f = Fact(fact="x", source_id="y")
    assert f.valid_at is None


def test_search_response_has_answer():
    assert "answer" in SearchResponse.model_fields


def test_search_response_has_facts():
    assert "facts" in SearchResponse.model_fields


def test_search_response_has_selected_nodes():
    assert "selected_nodes" in SearchResponse.model_fields


def test_search_response_has_spans():
    assert "spans" in SearchResponse.model_fields


def test_search_response_selected_nodes_defaults_empty():
    r = SearchResponse(answer="a", facts=[])
    assert r.selected_nodes == []


def test_search_response_spans_defaults_empty():
    r = SearchResponse(answer="a", facts=[])
    assert r.spans == []


# ---------------------------------------------------------------------------
# POST /topics — request and response
# ---------------------------------------------------------------------------

def test_topics_request_has_query():
    assert "query" in TopicsRequest.model_fields


def test_topics_request_has_group_ids():
    assert "group_ids" in TopicsRequest.model_fields


def test_topic_node_has_doc_id():
    assert "doc_id" in TopicNode.model_fields


def test_topic_node_has_id():
    assert "id" in TopicNode.model_fields


def test_topic_node_has_title():
    assert "title" in TopicNode.model_fields


def test_topics_response_has_l1_topics():
    assert "l1_topics" in TopicsResponse.model_fields
