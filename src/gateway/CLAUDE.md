# src/gateway/ — Claude Code context

## Read first
Read `ARCHITECTURE.md` in this directory before making any changes to this service.

## Purpose
Single entry point for all channels. Orchestrates the full request pipeline:
sanitize → classify → rewrite → retrieve → stream. Auth, access control, and
rate limiting are enforced here before any retrieval call. Channels have no
direct access to knowledge or any other backend service.

## Current structure
```
main.py             App factory. Wires vertexai init and chat router. No logic.
config.py           All tunable constants. Reads env vars at startup; raises on missing.
models.py           API boundary models: ChatRequest, FeedbackRequest
                    — contract-tested in tests/contracts/test_gateway_contract.py
routers/
  chat.py           POST /chat — full streaming pipeline (SSE)
services/
  sanitize.py       HTML stripping, whitespace normalization, 512-char limit
  scope_gate.py     LLM classifier: in_scope + specific_enough (one Gemini call)
  rewrite.py        Standalone query rewrite for session follow-ups
  knowledge_client.py  HTTP client for knowledge service (GET /topics, POST /search)
```

## Pipeline steps (all gateway-internal)
```
POST /chat
  1. sanitize          Strip HTML, normalize whitespace, enforce 512-char limit
  2. classify          LLM call → (in_scope, specific_enough)
  3. rewrite           If session history: rewrite follow-up as standalone question
  4. topics            Knowledge GET /topics → L1 topic list
  5. breadth check     Sibling consolidation → is query broad?
  6. search            Knowledge POST /search → {answer, facts}
  7. stream            Emit SSE events; prepend BROAD_QUERY_PREFIX if broad
```

Steps 3–7 are skipped when classify returns out-of-scope or not-specific-enough.

## What stays gateway-internal
Pipeline steps are stateless transforms tied to a single request. They scale with
the gateway and have no independent lifecycle:
- Input sanitization and HTML screening
- Scope + specificity classification (scope_gate.py)
- Session-based query rewriting (rewrite.py)
- Breadth detection (topic count + sibling collapse)
- BigQuery trace emission (planned — fire-and-forget after answer event)

## What is called over HTTP (separate services)
```
knowledge/    GET /topics, POST /search — retrieval and synthesis
auth/         POST /validate — token validation on every request (planned)
access/       GET /access/{user_id} — permitted source IDs (planned)
```

Rate limiting and input abuse detection are imported as a library from `src/security/`,
not called over HTTP — a round-trip before every request would add unacceptable latency.
See `src/security/CLAUDE.md`.

## API contract
```
POST /chat
  Request:  { "message": str, "session_id": str | null }
  Response: Server-Sent Events stream
    event: progress  data: {"key": "received" | "contacting" | "querying_ai" | "processing"}
    event: answer    data: {"answer": str, "facts": [...], "session_id": str, "warning": str|null}
    event: error     data: {"error": str}

GET /health
  Response: { "status": "healthy" }
```

`facts` is always present; empty when pipeline short-circuits (out-of-scope, vague).
`warning` is non-null only when HTML was stripped from the input.

## Routing tiers
| Tier | Condition | Knowledge call? |
|------|-----------|----------------|
| 3 — Out of scope | `in_scope = false` | No |
| 2 — Vague | `in_scope = true, specific_enough = false` | No |
| 1b — Broad | in scope, specific, `topic_count > MAX_TOPIC_PATHS` | Yes (overview prompt) |
| 1a — Focused | in scope, specific, `topic_count ≤ MAX_TOPIC_PATHS` | Yes (full synthesis) |

## Session management
In-memory: `session_id → {"turns": [{q, a}], "last_active": float}`. Lost on instance restart.
Max 10 turns per session. Sessions idle for 30+ minutes are evicted by a background sweeper
task (`start_session_sweeper()`, started in `main.py` lifespan, runs every 5 min).
Cloud Run may spin down idle instances. Firestore-backed sessions deferred until
multi-instance scaling requires it.

## Key invariants
- All inter-service calls go through dedicated client modules — never raw httpx in route handlers
- Permitted source IDs come from the access service middleware — never derived in a route handler
- LLM calls happen only inside dedicated service modules (scope_gate.py, rewrite.py)
- Config raises on startup for missing required vars — no silent defaults in production

## Configuration (config.py — all tunable via env vars)
| Variable | Default | Effect |
|----------|---------|--------|
| `GCP_PROJECT_ID` | `img-dev-490919` | GCP project for Vertex AI |
| `VERTEX_AI_LOCATION` | `europe-west1` | Vertex AI region |
| `KNOWLEDGE_SERVICE_URL` | *(required in prod)* | Knowledge service URL |
| `MAX_TOPIC_PATHS` | `5` | Topic count threshold for overview mode |
| `SIBLING_COLLAPSE_THRESHOLD` | `3` | L1 sections per doc before collapsing to doc-level |

## Running locally
```bash
cd src/gateway
pip install -r requirements.txt
export GCP_PROJECT_ID=img-dev-490919
export KNOWLEDGE_SERVICE_URL=https://knowledge-jeyczovqfa-ew.a.run.app
uvicorn main:app --reload --port 8000
# Requires: gcloud auth application-default login
```
