# knowledge — Architecture

## Role in the system

The knowledge service owns **retrieval and synthesis**. It has no opinion about whether
a question is in scope, whether a user is allowed to ask it, or how to display the result.
Given a query, it returns an answer grounded in the indexed corpus.

```
gateway  →  knowledge  →  Vertex AI (Gemini 2.5 Flash / Flash Lite)
                       ←  data/index/ (loaded at startup, immutable during runtime)
```

The service is not callable from the public internet. Ingress is `all` (not `internal`)
but `--no-allow-unauthenticated` is enforced — only callers with a valid Cloud Run
identity token and `roles/run.invoker` binding can reach it.

**Why `--ingress=all` and not `--ingress=internal`:** channel_web calls the knowledge
service directly in some configurations, and channel_web uses the public `*.run.app` URL.
Internal ingress blocks traffic from outside the GCP VPC, which includes Cloud Run
services calling each other over public URLs. This constraint is permanent until all
callers are co-located in the same VPC connector.

---

## Query pipeline (indexer/multi.py)

```
Stage 1 — Routing (structural model):
  Compact L1-only outline → LLM selects 1–2 doc IDs.

Stage 2 — Per-doc node selection (quality model, concurrent):
  Full outline of each selected doc → LLM selects leaf node IDs.
  Walks tree top-down until all selected nodes are leaves.
  Selection is recall-oriented: "err inclusive, missing content is worse than one extra section."

Stage 3 — Synthesis (quality model):
  Full text of selected nodes, scoped by doc:node ID → LLM synthesizes answer.
  0 nodes selected → short-circuit: return canned no-content response, NO LLM call.
```

Model assignment: `gemini-2.5-flash-lite` for structural tasks (routing, split boundaries).
`gemini-2.5-flash` for quality tasks (selection, synthesis). Rationale: routing requires
breadth recognition (cheap); selection and synthesis require precise reasoning (expensive).

---

## Endpoints

```
GET  /summary        Returns L1 routing outline for gateway's classifier prompt.
POST /topics         Routing + selection only; returns L1 ancestor nodes, no synthesis.
POST /search         Full pipeline; returns answer + facts + selected_nodes + spans.
POST /search/stream  Streaming variant: emits event:span in real time, then event:answer.
GET  /health         {"status": "healthy", "version": MODULE_GIT_REV}
```

`/search/stream` is the production path used by the gateway. `/search` is retained for
simpler callers and testing. Both paths initialize a `QueryContext` via ContextVar for
span isolation.

---

## Index lifecycle

The index is loaded from `KNOWLEDGE_INDEX_PATH` at startup and held in memory as a dict.
It is never refreshed during runtime — an index rebuild requires a redeploy.

Current deployment: index is baked into the Docker image at `COPY data/index/ index/`.
Planned: index downloaded from GCS at startup, enabling hot-reload without image rebuild.
**Do not change the startup load pattern until the GCS path is implemented.**

`multi_index.json` stores relative paths to per-doc index files. The startup code
resolves them relative to `multi_index.json`'s directory. Do not change this to absolute
paths — the portability is intentional.

---

## Span and observability model

Spans are per-request state stored in a `QueryContext` via `ContextVar` (`_QUERY_CTX`).
This makes span collection safe for concurrent requests in the same process.

Span emission: `emit_span(name, attributes, duration_ms)` in `indexer/observability.py`.
This appends to the context's span list AND, if `stream_cb` is set, calls it immediately
for real-time streaming. Do not call `emit_span` outside a live query context (the context
guard returns silently, not an error — so missing spans are silent).

Pattern for any new instrumentation point:
```python
emit_span("knowledge.my_step", {"key": "value"}, duration_ms=ms)
```

The corresponding display text must be added to `gateway/services/step_messages.py`.
The knowledge service itself never produces display text.

---

## group_ids: permanently stubbed until access service exists

`group_ids` is accepted in all request bodies and silently ignored. Every call to every
endpoint currently returns the full corpus regardless of what `group_ids` contains.

This is intentional. The access service (`src/access/`) is the owner of source filtering.
When it is implemented, the gateway will pass `permitted_source_ids` from the access
service as `group_ids`, and this service will enforce them.

**Do not implement partial group_ids filtering here.** Any access control logic added
to the knowledge service in isolation cannot be audited and creates a false sense of
security. Wait for the full flow: auth → access → gateway → knowledge.

---

## Facts: derived from selected nodes, not extracted citations

`_facts_from_result()` builds the `facts` list from the nodes *sent to synthesis*, not
from the synthesized answer text. Each fact is the section title + doc_id of a selected
node. This is a proxy for citation, not a true citation.

The planned fix: restructure the synthesis prompt to return JSON with explicit
per-claim citations. See `TODO.md`. Do not change the `facts` field shape in
`SearchResponse` without updating the gateway's `trace["knowledge"]["facts"]` and
channel_web's rendering — all three must change atomically.

---

## Boundaries — what knowledge owns vs. what it does NOT own

| Knowledge owns | Knowledge does NOT own |
|---|---|
| Index loading and in-memory representation | Who may query (that's access service) |
| All three pipeline stages (routing/selection/synthesis) | Whether query is in scope (that's gateway classifier) |
| Span emission within query pipeline | Span display text (that's gateway step_messages.py) |
| Canned no-content response on 0 chunks | Session state |
| Model selection (structural vs quality) | Trace writes (gateway writes traces) |

---

## Guardrails

**0-chunk short-circuit is mandatory.** When `section_parts` is empty after node
selection, return the canned response immediately without calling the synthesis LLM.
The routing outline must NEVER be passed as fallback context — the LLM will answer from
training data and produce plausible-but-hallucinated output. This was the production bug
fixed 2026-04-26.

**Never reassign ContextVar contents using `=`.** `QueryContext` must be mutated in place
(`.append()`, etc.). A bare reassignment in a reset function hands out a stale reference
to any code that captured the old value. The heuristics log has an entry on this exact
failure mode in the build context (same pattern).

**Recall over precision in selection prompts.** The selection stage uses recall-oriented
framing: "err inclusive; missing relevant content is worse than one extra section."
Do not tighten the selection prompt for precision without running the eval suite
(`poc/poc1_single_doc/eval/`). Prior iterations proved that precision-tightening causes
compound query recall failures that the lossy topic index cannot recover from.

**Hierarchical selection, never flat.** Node selection walks the tree top-down at each
level, presenting O(10-15) siblings per call. Never show the entire flat outline to the
selection LLM — 83-node flat outlines caused documented quality degradation. See
HEURISTICS.log [2026-04-15].

**Model constants are in `indexer/config.py`.** Never hardcode model names in
`multi.py`, `pageindex.py`, or `main.py`. The models are tunable parameters.

**`init_query_context` / `reset_query_context` must be called in a `try/finally` pair.**
If an exception escapes between init and reset, the ContextVar is left in a dirty state
for any subsequent request on the same asyncio task. See `main.py`'s usage of
`ctx_token` in the search handler for the reference pattern.

**Do not add synchronous I/O inside async handlers.** All Vertex AI calls go through
`indexer/llm.py`'s async `llm_call()`. If you add a new LLM call, it must be async.

**Exponential backoff on ResourceExhausted.** Any `asyncio.gather` over LLM calls must
handle `ResourceExhausted` with exponential backoff. Large documents trigger 429s when
all concurrent calls fire simultaneously. See HEURISTICS.log [2026-04-13].

**Deploy path: local Docker, not Cloud Build.** Cloud Build API is not enabled on
`img-dev-490919`. Use `bash src/knowledge/deploy.sh`. See HEURISTICS.log [2026-03-25].

---

## Known gaps

| Gap | Impact | Fix |
|---|---|---|
| Index baked into Docker image | Corpus updates require full image rebuild and redeploy | GCS-backed index download at startup (Phase 3.1) |
| group_ids ignored | No per-user source filtering | Access service implementation |
| Facts derived from node metadata, not citations | Citations are section names, not actual quoted text | Structured synthesis JSON output |
| No index hot-reload | Stale corpus until redeploy | GCS index + startup refresh on version change |
| `/search` (non-streaming) duplicates pipeline | Two code paths to maintain | Deprecate in favour of `/search/stream` once all callers migrated |
