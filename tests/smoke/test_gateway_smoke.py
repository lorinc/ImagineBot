"""
Smoke test: verify deployed gateway returns a valid SSE stream.

Required env vars:
  SMOKE_GATEWAY_URL   e.g. https://gateway-jeyczovqfa-ew.a.run.app
  SMOKE_ID_TOKEN      valid Google ID token for an allowed test user
  SMOKE_QUERY         known in-corpus query (default: "What happens after a fire drill?")

Writes trace_id to /tmp/imaginebot_smoke_trace_id for use by test_trace_firestore.py.
"""
import json
import os
import time

import httpx
import pytest

GATEWAY_URL = os.environ.get("SMOKE_GATEWAY_URL", "").rstrip("/")
ID_TOKEN = os.environ.get("SMOKE_ID_TOKEN", "")
QUERY = os.environ.get("SMOKE_QUERY", "What happens after a fire drill?")
TRACE_ID_FILE = "/tmp/imaginebot_smoke_trace_id"
TIMEOUT_S = 60


def _required_env():
    missing = [v for v in ("SMOKE_GATEWAY_URL", "SMOKE_ID_TOKEN") if not os.environ.get(v)]
    if missing:
        pytest.skip(f"Missing env vars: {', '.join(missing)}")


def _parse_sse_line(line: str) -> tuple[str | None, str | None]:
    """Return (field, value) for a single SSE line, or (None, None) for blank/comment."""
    if not line or line.startswith(":"):
        return None, None
    if ":" in line:
        field, _, value = line.partition(":")
        return field.strip(), value.lstrip(" ")
    return line.strip(), ""


def test_gateway_smoke():
    _required_env()

    events: list[tuple[str, dict]] = []  # [(event_name, data_dict)]
    current_event: str | None = None
    current_data: str = ""

    headers = {
        "Authorization": f"Bearer {ID_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"message": QUERY, "session_id": None}

    start = time.monotonic()
    with httpx.Client(timeout=TIMEOUT_S) as client:
        with client.stream("POST", f"{GATEWAY_URL}/chat", headers=headers, json=payload) as resp:
            # Assert 1: HTTP 200 + SSE content type
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct, f"Expected text/event-stream, got: {ct}"

            for raw_line in resp.iter_lines():
                assert time.monotonic() - start < TIMEOUT_S, "Stream exceeded 60s timeout"

                field, value = _parse_sse_line(raw_line)
                if field is None:
                    # blank line = end of event
                    if current_event and current_data:
                        try:
                            events.append((current_event, json.loads(current_data)))
                        except json.JSONDecodeError:
                            events.append((current_event, {"_raw": current_data}))
                    current_event = None
                    current_data = ""
                elif field == "event":
                    current_event = value
                elif field == "data":
                    current_data = value

            # flush last event if stream closed without trailing blank line
            if current_event and current_data:
                try:
                    events.append((current_event, json.loads(current_data)))
                except json.JSONDecodeError:
                    events.append((current_event, {"_raw": current_data}))

    event_names = [e for e, _ in events]

    # Assert 4: no error event
    error_events = [(e, d) for e, d in events if e == "error"]
    assert not error_events, f"Received error event(s): {error_events}"

    # Assert 2: at least one progress before answer
    answer_idx = next((i for i, (e, _) in enumerate(events) if e == "answer"), None)
    assert answer_idx is not None, f"No answer event received. Events: {event_names}"
    progress_before = any(e == "progress" for e, _ in events[:answer_idx])
    assert progress_before, f"No progress event before answer. Events: {event_names}"

    # Assert 3: answer shape
    _, answer_data = events[answer_idx]
    assert answer_data.get("answer"), f"answer.answer is empty: {answer_data}"
    facts = answer_data.get("facts")
    assert isinstance(facts, list) and len(facts) > 0, f"answer.facts is empty or missing: {answer_data}"
    assert answer_data.get("session_id"), f"answer.session_id missing: {answer_data}"
    trace_id = answer_data.get("trace_id")
    assert trace_id, f"answer.trace_id missing: {answer_data}"

    # Persist trace_id for test_trace_firestore.py
    with open(TRACE_ID_FILE, "w") as f:
        f.write(trace_id)

    # Assert 5: completed within timeout (guaranteed by the loop assertion above)
    elapsed = time.monotonic() - start
    assert elapsed < TIMEOUT_S, f"Stream took {elapsed:.1f}s, exceeded {TIMEOUT_S}s"
