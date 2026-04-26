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
Contract tests import actual model/schema classes from `src/<service>/models.py` and assert
every field by name. They cannot be faked. When a model field is renamed, they break immediately.

**Import pattern:** All three services have a file named `models.py`. Running all contract tests
in one pytest invocation would cause `sys.modules['models']` collision if the tests used
`sys.path.insert`. Instead, use `importlib.util.spec_from_file_location` with a unique
module name per service:

```python
import importlib.util, os

_path = os.path.join(os.path.dirname(__file__), "../../src/gateway/models.py")
_spec = importlib.util.spec_from_file_location("gateway.models", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ChatRequest = _mod.ChatRequest
```

Use `"gateway.models"`, `"knowledge.models"`, `"channel_web.models"` as the name argument
so each service's models live under a distinct key in `sys.modules`.

One contract test file per service. When you add a model field: add it to `models.py`,
then add an assertion to the contract test. When you rename a field: rename in `models.py`,
rename in the contract test, grep for all usages across all services.

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
