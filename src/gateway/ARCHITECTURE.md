# gateway — Architecture

## Role in the system

The gateway is the **only entry point for user queries**. It owns the entire request
pipeline from sanitized input to streamed answer. No channel may call downstream
services directly — everything flows through here.

```
channel_web  →  gateway  →  knowledge
                         →  Firestore (traces, fire-and-forget)
```

Auth/access/security middleware stubs exist in the design but are not yet wired.
The gateway currently trusts any caller with a valid Cloud Run identity token.

---

## Pipeline (routers/chat.py)

```
POST /chat  →  sanitize  →  classify  →  rewrite?  →  topics  →  search/stream  →  SSE
                              ↓ out-of-scope     ↓ not-specific
                           answer (no KB)    answer (no KB)
```

Each step is implemented in a dedicated module under `services/`. Pipeline logic never
lives in `routers/chat.py` itself — the router only sequences the steps and assembles
the trace.

Step functions: `sanitize`, `classify`, `rewrite_standalone`, `knowledge_client.*`  
All LLM calls: `scope_gate.py`, `rewrite.py` — never raw Vertex AI in the router.  
All display text: `step_messages.py` — never inline strings in pipeline code.

---

## SSE event protocol

```
event: progress   data: {"key": "received"|"contacting"|"querying_ai"|"processing"}
event: thinking   data: {"text": str, "ms": int|null}
event: answer     data: {"answer": str, "facts": [...], "session_id": str, "trace_id": str,
                          "warning": str|null}
event: error      data: {"error": str}
```

`thinking` events are emitted once per span, in arrival order. The gateway emits its
own spans directly; knowledge spans arrive via `search_stream` and are relayed verbatim.

---

## Key design decisions

**Classifier fails open.** On classifier error: `in_scope=True, specific_enough=True`.
Rationale: a failed classifier is more dangerous as a refusal gate than as a pass-through.
The knowledge service is the last line of defence.

**Breadth detection via sibling consolidation.** When a doc contributes ≥ `SIBLING_COLLAPSE_THRESHOLD`
L1 sections, those siblings collapse to a single label. Overview mode triggers when
consolidated label count exceeds `MAX_TOPIC_PATHS`. This prevents a query spanning one
large multi-section document from being mis-classified as broad.

**`overview` flag, not a separate endpoint.** Overview mode is signalled via `overview=True`
on the knowledge `/search` call. The knowledge service chooses a different synthesis
prompt. The gateway never constructs prompts directly.

**Corpus summary cached forever.** `_corpus_summary` is a module-level variable, loaded
once on the first request. It is never expired. If the index is rebuilt and the gateway
is not restarted, the classifier will still use the old corpus outline. This is acceptable
while the index is baked into the Docker image and rebuilt deploys always restart the service.
**This will break when GCS-backed index is implemented — add a TTL at that point.**

**Sessions are in-memory.** `_sessions` is a dict on a single process. Multi-instance
Cloud Run scale-out means a user whose second request routes to a different instance
will receive a context-free response (no rewrite, first turn treated as new). Acceptable
at current scale. Firestore-backed sessions are the planned fix when multi-instance is
required.

**Trace is fire-and-forget.** `asyncio.create_task(write_trace(trace))` — trace writes
never block the SSE response. If Firestore is unavailable, traces are silently dropped.
This is intentional: tracing must not degrade user experience.

---

## Boundaries — what gateway owns vs. what it does NOT own

| Gateway owns | Gateway does NOT own |
|---|---|
| Request pipeline sequencing | Query understanding (that's classify/rewrite) |
| Session state (in-memory) | Retrieval (that's knowledge service) |
| Trace assembly and write | Index structure or document content |
| SSE protocol shape | LLM prompt construction (in services/) |
| Breadth detection + sibling consolidation | Display text (that's step_messages.py) |
| Feedback endpoint (forwards to Firestore) | Auth token validation (future: auth service) |
| `event: thinking` emission | Span computation (each service emits its own) |

---

## Guardrails

**Never construct LLM prompts in routers/.** Prompts belong in services modules.
`routers/chat.py` must only call functions, not format strings for LLM consumption.

**Never put display text in pipeline code.** All human-readable span labels live in
`services/step_messages.py`. New spans must add an entry there; the pipeline emits
structured data (span name + attributes), never prose.

**Patch imports at their binding site in tests.** `routers/chat.py` uses
`from services.scope_gate import classify` — patch `routers.chat.classify`, not
`services.scope_gate.classify`. The heuristics log has an entry on this exact failure.

**Do not use `gcloud builds submit`.** Cloud Build API is not enabled. Deploy path is:
`docker build → docker push → gcloud run deploy`. See `deploy.sh`.

**`KNOWLEDGE_SERVICE_URL` is required.** It defaults to `""` (empty string) in `config.py`,
which causes `httpx.InvalidURL` at call time with no clear error. If you add startup
validation, fail loudly when this is unset or empty.

**Identity token fetch blocks the event loop.** `knowledge_client._get_identity_token()`
calls `google.auth.transport.requests.Request()` — a synchronous HTTP call inside an
async handler. This is a latent performance issue under load. Fix with
`asyncio.get_event_loop().run_in_executor(None, ...)` before this service scales.

**Do not run gateway tests and channel_web tests in the same pytest invocation.**
Both services have a file named `main.py`. Python's module cache (`sys.modules`) will
serve the wrong `main` to whichever test suite loads second. Run suites separately:
`pytest tests/gateway/` and `pytest tests/channel_web/`.

**group_ids is always None.** Until the access service is implemented, all knowledge
calls pass `group_ids=None`. Do not add per-user source filtering at the gateway level —
that is the access service's responsibility. Keep the stub as-is.

**Secret volume mounts require unique parent directories.** Pattern:
`/secrets/my_secret/SECRET_NAME=SECRET_NAME:latest`. Never share a parent dir across
two secrets — Cloud Run rejects it. See HEURISTICS.log [2026-03-21 21:30].

---

## Dependencies

Runtime: `fastapi`, `httpx`, `vertexai`, `google-auth`, `requests`, `google-cloud-firestore`  
`requests` must be listed alongside `google-auth` — google-auth does not declare it as
a hard dependency but fails silently without it. See HEURISTICS.log [2026-03-21 23:00].

---

## Known gaps

| Gap | Impact | Fix |
|---|---|---|
| In-memory sessions | Lost on instance restart or scale-out | Firestore-backed sessions |
| Corpus summary never expires | Stale classifier after index rebuild without restart | Add TTL when GCS index lands |
| Synchronous identity token fetch in async path | Event loop stall under load | `run_in_executor` |
| No auth enforcement in gateway | Any `run.invoker`-bound SA can call gateway | Auth middleware (Sprint 3+) |
| No rate limiting | Abuse possible | Security library import (Sprint 3+) |
| `KNOWLEDGE_SERVICE_URL` defaults to empty string | Silent misconfiguration | Fail on startup if unset |
