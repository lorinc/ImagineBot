# tests/ — Claude Code context

## Test pyramid
```
contracts/      Field name and shape assertions. Fast. No external deps.
                Run these first — they catch the cheapest class of bugs.
                One file per API resource per service.

unit/           Isolated logic. Mocked dependencies. Fast (<100ms each).
                No database, no network, no filesystem.

integration/    Real Firestore emulator. Tests full request-response cycles.
                Requires: Firestore emulator running on localhost:8080.

smoke/          Non-destructive tests against a live deployed environment.
                Run after every staging deploy. Must clean up own test data.
```

## What requires external dependencies
Needs nothing:
- `tests/contracts/`
- `tests/unit/`

Needs Firestore emulator (`gcloud emulators firestore start`):
- `tests/integration/`

Needs live staging URL:
- `tests/smoke/`

## Running tests
```bash
# Contracts + unit (no setup)
pytest tests/contracts/ tests/unit/ -v

# Integration (start emulator first)
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080
export GCP_PROJECT_ID=test-project
pytest tests/integration/ -v

# Smoke (against staging)
export STAGING_URL=https://[your-staging-url]
export STAGING_TOKEN=[valid test user token]
pytest tests/smoke/ -v

# Everything except smoke
pytest tests/contracts/ tests/unit/ tests/integration/ -v
```

## Contract tests — what they are and why
Contract tests import actual model/schema classes and assert field names and types exist.
They cannot be faked. When a model field is renamed, they break immediately.

```python
# tests/contracts/test_query_contract.py
from src.gateway.models.query import QueryRequest, QueryResponse
from src.knowledge.models.chunk import Chunk

def test_query_request_fields():
    fields = QueryRequest.model_fields
    assert 'query' in fields
    assert 'session_id' in fields

def test_query_response_fields():
    fields = QueryResponse.model_fields
    assert 'answer' in fields
    assert 'sources' in fields
    assert 'session_id' in fields

def test_chunk_fields():
    fields = Chunk.model_fields
    assert 'chunk_id' in fields
    assert 'source_id' in fields
    assert 'content' in fields
    assert 'score' in fields
```

One contract test file per API boundary the gateway exposes.
When you add a field: add it to the model, then add it to the contract test.
When you rename a field: rename in model, rename in contract test, find all usages.

## Test isolation rules
- Each test is independent. No shared state between tests.
- Integration tests use unique IDs (UUID) to avoid state pollution between runs.
- Each integration test cleans up in teardown (or uses Firestore emulator reset).
- Smoke tests must leave no permanent state in staging.

## What a real test looks like
"Tests pass" is not an acceptance criterion.
A real test:
1. Sets up a known state
2. Calls the actual code path (not a mock of it)
3. Asserts a specific observable outcome — not just status 200
4. Fails if the outcome is wrong

Bad: `assert response.status_code == 200`
Good: `assert response.json()["answer"] != "" and response.json()["sources"] != []`

## What NOT to do
- Do not modify test assertions to make a test pass if the code is wrong
- Do not mock the thing you're testing
- Do not write tests that only run in CI
- Do not `try/except` inside tests to swallow failures
- Do not assert on implementation details — assert on observable outputs
