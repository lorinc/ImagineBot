# Architecture

This document covers only cross-cutting concerns: system topology, shared protocols,
cross-service invariants, and constraints that no single service owns. Every service
has its own `ARCHITECTURE.md` — start there for service-specific decisions.

**Do not duplicate service-level decisions here. Do not let this file drift from the code.**

---

## Module map

| Service | Type | Ingress | Status |
|---|---|---|---|
| `src/channel_web/` | Cloud Run service | public HTTPS | deployed |
| `src/gateway/` | Cloud Run service | public HTTPS | deployed |
| `src/knowledge/` | Cloud Run service | `--no-allow-unauthenticated`, ingress=all | deployed |
| `src/ingestion/` | Cloud Run Job | n/a (offline job) | Job stub built; not yet deployed |
| `src/auth/` | Cloud Run service | internal | not implemented |
| `src/access/` | Cloud Run service | internal | not implemented |
| `src/security/` | library (imported by gateway) | n/a | not implemented |
| `src/admin/` | Cloud Run service | separate ingress, admin auth | not implemented |

→ Each service's decisions: `src/<service>/ARCHITECTURE.md`

---

## System topology

```
Browser
  │  HTTPS (Google ID token in Authorization header)
  ▼
channel_web  (Cloud Run, public)
  │  HTTPS (Cloud Run identity token, service-to-service)
  ▼
gateway  (Cloud Run, public)
  │  HTTPS (Cloud Run identity token)           writes
  ├──────────────────────────────────────────▶  Firestore  traces/{trace_id}
  │  HTTPS (Cloud Run identity token, X-Trace-Id header)
  ▼
knowledge  (Cloud Run, no-allow-unauthenticated)
  │  gRPC / HTTPS
  ▼
Vertex AI  (Gemini 2.5 Flash / Flash Lite)
```

**Invariant: channel_web never calls knowledge directly.** All queries flow through
the gateway. If you find a direct channel_web → knowledge call, it is an architecture
violation.

**Stubs on the gateway's request path (not yet wired):**
```
gateway  →  auth service    (token validation — currently inline in channel_web)
        →  access service   (group_ids resolution — currently null)
        →  security library (rate limiting + input screening — currently absent)
```

---

## GCP project structure

Two projects:
```
img-dev   — all services, development + staging
img-prod  — all services, production (not yet provisioned)
```

One Cloud Run service per `src/` service. One service account per service, minimum
permissions. Services call each other via HTTPS (Cloud Run URL), never via shared databases.
Billing attribution via resource labels, not project splits.

Per-project resources: Cloud Run, Cloud Run Jobs, Firestore, Secret Manager,
Artifact Registry, Cloud Storage, Vertex AI, Workload Identity Federation.

**Deploy path: local Docker, not Cloud Build.** Cloud Build API is not enabled on
`img-dev`. Pattern: `docker build → docker push → gcloud run deploy`. All services
have a `deploy.sh`. Never use `gcloud builds submit`.

**Production deploy is always a manual trigger.** Automatic deploy to production is
prohibited — no CI pipeline, no merge hook, no script may deploy to `img-prod` without
an explicit human action.

---

## Dependency policy

This project is deliberately conservative on dependencies. Before adding any package:
1. State what problem it solves
2. State what the alternative without it would be
3. Get explicit approval

Never add a package to solve a problem that three lines of Python would solve.
Never add a Node.js toolchain dependency. The frontend must be serveable without a build step.

---

## Service-to-service authentication

All internal calls use **Cloud Run identity tokens** fetched via ADC:
```python
google.oauth2.id_token.fetch_id_token(auth_req, TARGET_SERVICE_URL)
```
The receiving service is protected with `--no-allow-unauthenticated`. Cloud Run IAM
validates the token; the service never validates it manually.

**Two distinct token flows — never confuse them:**

| Flow | Token type | Issued by | Validated by |
|---|---|---|---|
| Browser → channel_web | Google OAuth2 ID token | Google Sign-In | channel_web (`verify_oauth2_token`) |
| Service → service | Cloud Run identity token | ADC / service account | Cloud Run IAM |

The user's Google ID token never leaves channel_web. It is never forwarded to the gateway.

---

## SSE event protocol (gateway → channel_web → browser)

Defined by the gateway. channel_web proxies verbatim — no rewriting.

```
event: progress   data: {"key": "received"|"contacting"|"querying_ai"|"processing"}
event: thinking   data: {"text": str, "ms": int|null}
event: answer     data: {"answer": str, "facts": [...], "session_id": str, "trace_id": str,
                          "warning": str|null}
event: error      data: {"error": str}
```

**`facts` shape (shared across gateway, knowledge, channel_web):**
```json
[{ "fact": str, "source_id": str, "valid_at": null }]
```
`valid_at` is always `null` until the structured citation feature is built.
Do not change this shape in any single service — all three must change atomically.

**`thinking` events** are emitted once per span, in arrival order. Gateway emits its own
spans. Knowledge spans arrive via `POST /search/stream` and are relayed verbatim by the
gateway — no rewriting, no aggregation delay.

---

## Observability: spans and traces

### Span model

Each service owns its own span emission. Spans are per-request, isolated by `ContextVar`.

**Knowledge service spans** (emitted via `indexer/observability.py`):
```
knowledge.routing, knowledge.selection, knowledge.synthesis_started, knowledge.synthesis_done
```

**Gateway spans** (emitted via `services/observability.py`):
```
gateway.classify, gateway.rewrite.skipped, gateway.topics, gateway.breadth.focused
(and others — see SpanCollector in gateway/services/observability.py)
```

Span wire format: `{ "service": str, "name": str, "attributes": dict, "duration_ms": int }`

**Display text for all spans lives in `gateway/services/step_messages.py`.** No service
other than gateway ever produces human-readable span labels. When adding a new span anywhere
in the pipeline, add its display text to `step_messages.py`.

### X-Trace-Id header

The gateway sets `X-Trace-Id: <trace_id>` on every call to the knowledge service.
The knowledge service reads it for correlation. No other service propagates this header yet.

### Firestore trace schema

Collection: `traces/{trace_id}`

```
trace_id        str       UUID, set by gateway at request start
session_id      str
timestamp       datetime
versions        { gateway: str, knowledge: str }   — git SHAs from deploy
pipeline_path   str       e.g. "classify→rewrite→topics→search"
input           { raw: str, sanitized: str }
classifier      { in_scope: bool, specific_enough: bool }
rewrite         { standalone: str } | null
topics          { l1_topics: [...] }
knowledge       { answer: str, facts: [...], selected_nodes: [...] }
output          { answer: str, facts: [...] }
feedback        { score: int, comment: str, updated_at: datetime } | null
spans           list[Span]
```

Traces are written **fire-and-forget**. A Firestore outage must never degrade query
response time or produce a user-visible error. If a trace write fails, it is dropped silently.

---

## Access control chain

The full enforcement chain when implemented:

```
auth service  →  validates token, returns user_id + tenant_id
access service  →  returns permitted_source_ids for user_id
gateway  →  passes permitted_source_ids as group_ids to knowledge service
knowledge service  →  enforces group_ids as pre-retrieval filter (not post-filter)
```

**Current state (partial stub):** auth is inline in channel_web. `group_ids` is always
`null`. Knowledge service accepts `group_ids` but ignores it.

**Invariant: no partial implementation.** Do not add group_ids enforcement to the
knowledge service in isolation. Do not add auth enforcement to the gateway without the
auth service. Any partial implementation creates auditable gaps with no corresponding
protection. The chain must be implemented end-to-end or not at all.

**Post-filter is never acceptable.** Access control must be a pre-filter on retrieval,
not a post-filter on results. Post-filtering silently degrades recall when top results
happen to be from unpermitted sources.

---

## Corpus and index lifecycle

```
Google Drive  →  ingestion pipeline (Steps 1–5)
                 → data/pipeline/<run_id>/02_ai_cleaned/<source_id>.md
              →  src/ingestion/build_index.py
                 → data/index/multi_index.json + per-doc index files
              →  GCS: gs://img-dev-index/<SOURCE_ID>/multi_index.json + index_*.json
              →  knowledge service downloads from GCS at startup (INDEX_GCS_PATH env var)
                 → holds in memory
```

**Trigger paths:**
- **Dev (manual):** `python3 -m src.ingestion.pipeline.run --all` + `python3 src/ingestion/build_index.py`
- **Prod (Cloud Run Job):** `src/ingestion/job/main.py` — polls Drive folder, detects DOCX changes via manifest diff, runs full rebuild, uploads index to GCS. Triggered by Cloud Scheduler (1-minute poll) once deployed.

**Knowledge service never calls ingestion.** They are coupled through GCS (prod) or the
local filesystem (dev).

**GCS index read:** knowledge service checks `INDEX_GCS_PATH` env var at startup. If set
(`gs://img-dev-index/tech_poc`), downloads `multi_index.json` + all per-doc `index_*.json`
to `/tmp/index/` and loads from there. Falls back to `KNOWLEDGE_INDEX_PATH` local path if
`INDEX_GCS_PATH` is not set.

**Drive is authoritative. `data/` and GCS index are derived.** Any artifact can be
regenerated from Drive. Do not treat GCS or `data/` as the canonical document store.

---

## Secret management

All secrets via Secret Manager volume mounts. Pattern:
```
/secrets/<secret_name>/<SECRET_NAME>  ←  mounted by Cloud Run
```

**Never share a parent directory across two secrets.** Cloud Run rejects it.
`/secrets/my_secret/SECRET_NAME=SECRET_NAME:latest` — each secret gets its own
parent directory.

**Secrets loaded at startup, not on each request.** Rotation requires a service restart
unless the service explicitly re-reads the file on a schedule. `ALLOWED_EMAILS` in
channel_web is the canonical example of a startup-only load. Document this limitation
in any service that loads a secret at startup.

**`google-auth` requires `requests` as a co-dependency.** Pin both in every service's
`requirements.txt`. google-auth does not declare `requests` as a hard dependency but
fails silently without it.

---

## Cross-service test isolation

**Never run gateway and channel_web tests in the same pytest invocation.** Both services
have a `main.py`. Python's module cache (`sys.modules`) serves the wrong `main` to
whichever suite loads second. Always run separately:
```
pytest tests/gateway/
pytest tests/channel_web/
```

**Patch imports at their binding site.** If `routers/chat.py` uses
`from services.scope_gate import classify`, the test must patch `routers.chat.classify`,
not `services.scope_gate.classify`.

---

## Coding agent guardrails

These rules cut across all services. Violating them creates cross-service breakage.

**API boundary models live in `src/<service>/models.py`.** Never define Pydantic request or
response models inline in router or `main.py` files. Contract tests in `tests/contracts/`
import directly from these files — an inline definition is invisible to them.

**Never construct LLM prompts outside `services/` modules.** Routers sequence steps;
services own prompts. This applies to the gateway; the same separation principle applies
everywhere.

**Never put display text in pipeline code.** Human-readable labels for spans, step names,
and user-facing error descriptions live in `gateway/services/step_messages.py`.
Pipeline code emits structured data (span name + attributes); display text is separate.

**Never expose stack traces to the browser.** All error responses are `{"error": str}`.
The error string is a safe message, never a Python traceback.

**Never write tenant, user, or source configuration directly to Firestore outside the
admin service.** When admin is implemented, it is the sole writer of those collections.
Direct writes from other services are an architecture violation.

**Do not implement partial access control.** See "Access control chain" above.

**Synchronous calls inside async handlers are latent bugs.** `verify_oauth2_token()`,
`fetch_id_token()`, and `google.auth.transport.requests.Request()` are all synchronous
and block the event loop. `fetch_id_token` in gateway is fixed (run_in_executor + TTL cache
in `knowledge_client.py`). `verify_oauth2_token` in channel_web is still a known issue.
Do not add new synchronous I/O in async paths.

**`ContextVar` contents must be mutated in-place, never reassigned.** A bare
reassignment inside a reset function returns a stale reference to any code that captured
the old value. See `knowledge/indexer/observability.py` for the reference pattern.
