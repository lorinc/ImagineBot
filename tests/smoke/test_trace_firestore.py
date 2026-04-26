"""
Trace verifier: assert a smoke query's trace landed in Firestore with all required fields.

Dependencies:
  - ADC configured (gcloud auth application-default login)
  - GCP_PROJECT_ID env var (default: img-dev-490919)
  - /tmp/imaginebot_smoke_trace_id written by test_gateway_smoke.py

Run after test_gateway_smoke.py:
  pytest tests/smoke/test_gateway_smoke.py tests/smoke/test_trace_firestore.py -v -s
"""
import os
import time

import pytest

TRACE_ID_FILE = "/tmp/imaginebot_smoke_trace_id"
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
POLL_INTERVAL_S = 1
POLL_TIMEOUT_S = 10

REQUIRED_TOP_LEVEL_FIELDS = {
    "trace_id", "session_id", "timestamp", "versions",
    "pipeline_path", "input", "output",
}


def _load_trace_id() -> str:
    if not os.path.exists(TRACE_ID_FILE):
        pytest.skip(
            f"No trace_id file at {TRACE_ID_FILE} — run test_gateway_smoke.py first"
        )
    with open(TRACE_ID_FILE) as f:
        trace_id = f.read().strip()
    if not trace_id:
        pytest.skip("trace_id file is empty")
    return trace_id


def test_trace_in_firestore():
    try:
        from google.cloud import firestore
    except ImportError:
        pytest.skip("google-cloud-firestore not installed")

    trace_id = _load_trace_id()

    db = firestore.Client(project=GCP_PROJECT_ID)
    doc_ref = db.collection("traces").document(trace_id)

    doc = None
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        snapshot = doc_ref.get()
        if snapshot.exists:
            doc = snapshot.to_dict()
            break
        time.sleep(POLL_INTERVAL_S)

    # Assert 1: document exists within 10s
    assert doc is not None, (
        f"traces/{trace_id} not found in Firestore after {POLL_TIMEOUT_S}s"
    )

    # Assert 2: all required top-level fields present
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(doc.keys())
    assert not missing, f"Missing top-level fields: {missing}. Got: {set(doc.keys())}"

    # Assert 3: output shape
    output = doc["output"]
    assert output.get("answer"), f"output.answer is empty: {output}"
    assert isinstance(output.get("facts"), list), (
        f"output.facts is not a list: {output}"
    )

    # Assert 4: spans non-empty
    spans = doc.get("spans")
    assert isinstance(spans, list) and len(spans) > 0, (
        f"spans is empty or missing: {spans}"
    )

    # Assert 5: feedback absent or null
    feedback = doc.get("feedback")
    assert feedback is None, f"feedback is pre-populated (should be null): {feedback}"
