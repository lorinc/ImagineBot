---
name: contract-test
description: Write a contract test for a new model or API resource. Use when a new Pydantic model is created or an existing one is changed.
---

# Skill: Write a contract test

Contract tests assert that model field names are exactly what they should be.
They are the cheapest tests to write and catch the most expensive bugs (field name drift
between services causes silent data corruption, not exceptions).

## When to use this skill
- A new Pydantic model has been created in any `models/` directory
- An existing model field has been renamed or added
- The PostToolUse hook warned "model file changed — running contract tests"

## Steps

### 1. Identify the model
Find the model class in `src/[service]/models/[resource].py`.
Note every field name exactly as it appears in `model_fields`.

### 2. Find or create the contract test file
Path: `tests/contracts/test_[service]_[resource]_contract.py`

If the file exists, add to it. Never create a second contract test file for the same resource.

### 3. Write the test
```python
# tests/contracts/test_gateway_query_contract.py
from src.gateway.models.query import QueryRequest, QueryResponse

def test_query_request_fields():
    """Gateway QueryRequest must have exactly these fields."""
    fields = QueryRequest.model_fields
    # Required fields — failure here means a rename broke the API contract
    assert 'query' in fields, "field 'query' missing from QueryRequest"
    assert 'session_id' in fields, "field 'session_id' missing from QueryRequest"

def test_query_response_fields():
    """Gateway QueryResponse must have exactly these fields."""
    fields = QueryResponse.model_fields
    assert 'answer' in fields, "field 'answer' missing from QueryResponse"
    assert 'sources' in fields, "field 'sources' missing from QueryResponse"
    assert 'session_id' in fields, "field 'session_id' missing from QueryResponse"
```

Rules:
- Assert the field EXISTS. Do not assert its type (that's a unit test).
- Include the field name in the assertion message. Make failures readable.
- Cover every field the gateway exposes externally. Internal implementation fields: optional.

### 4. Run the contract tests
```bash
pytest tests/contracts/ -v
```

All must pass. If one fails, the model was changed without updating the contract.
Fix the model, not the test.

### 5. Update the field contract table
In the relevant service CLAUDE.md, under "API field name contracts":
add the new field to the table.

## One rule
Contract tests are assertions about what the API promises.
If the API promise changes, update the contract test and document the breaking change
in DELIVERY.md. Do not silently change field names.
