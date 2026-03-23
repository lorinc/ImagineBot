# src/gateway/ — Claude Code context

## Purpose
Single entry point for all channels. Routes requests after auth, access, and security
checks pass. Channels (web, WhatsApp, future) call this service only — they have no
direct access to knowledge, auth, or any other service.

## Module map
```
main.py             App factory. Wires together middleware and routers. No logic here.
routers/
  query.py          POST /query — the main user-facing endpoint
  health.py         GET /health — used by smoke tests and Cloud Run health checks
middleware/
  auth_middleware.py      Validates token. Attaches user_id to request state.
  access_middleware.py    Calls access service. Attaches permitted_source_ids to request state.
  security_middleware.py  Rate limiting + input screening. Rejects before any service call.
models/
  query.py          QueryRequest, QueryResponse — source of truth for API contract
services/
  knowledge_client.py   HTTP client for knowledge service. Thin wrapper.
  llm_client.py         LLM API call. Receives context from knowledge, returns answer.
config.py           Reads environment variables. Fails loudly on startup if missing.
```

## Request lifecycle (inside gateway)
```
POST /query
  → security_middleware (rate limit + screen input)
  → auth_middleware (validate token → user_id)
  → access_middleware (user_id → permitted_source_ids)
  → knowledge_client.retrieve(query, permitted_source_ids) → context
  → llm_client.answer(query, context) → answer
  → QueryResponse
```

Middleware runs in the order registered. Order matters. Do not reorder without understanding
the security implications: security checks must run before auth (to block before any DB hit),
auth must run before access (access needs user_id).

## API contract (QueryResponse fields)
| Field | Type | Notes |
|-------|------|-------|
| answer | str | LLM-generated answer |
| sources | list[SourceRef] | Sources used — id + title only, not content |
| session_id | str | For conversation continuity |
| [fields TBD] | | Update this table when models are finalised |

Contract tests live in `tests/contracts/test_query_contract.py`.
When any field changes here, update that file first.

## Key invariants
- The gateway never directly queries Firestore. It calls services.
- Permitted source IDs are attached by middleware and passed through — never derived inside a route handler.
- LLM is called only after knowledge retrieval completes. No LLM calls with empty context.
- All inter-service calls are HTTP. No shared in-process state between services.
- Config is read once at startup. `config.py` raises on missing required vars.

## Inter-service calls
All outbound calls go through dedicated client modules. Never use `httpx` directly
inside a route handler.

```python
# CORRECT
context = await knowledge_client.retrieve(query, permitted_source_ids)

# WRONG
resp = await httpx.post(settings.knowledge_url + "/retrieve", ...)
```

This makes mocking in tests straightforward and keeps route handlers readable.

## Environment variables
```
KNOWLEDGE_SERVICE_URL     Internal Cloud Run URL for knowledge service
AUTH_SERVICE_URL          Internal Cloud Run URL for auth service
ACCESS_SERVICE_URL        Internal Cloud Run URL for access service
LLM_API_KEY               LLM provider API key (never log this)
LLM_MODEL                 Model identifier string
RATE_LIMIT_RPM            Requests per minute per user (default: 20)
```

## Running locally
```bash
cd src/gateway
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Known issues
[Populate as work proceeds]
