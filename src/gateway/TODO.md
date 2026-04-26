# TODO — gateway open questions and next steps

_Append-only. Resolve items by striking through and noting the outcome._

Priority order for next implementation cycle at the bottom.

---

## Stage 0 — Query understanding

The current pipeline sanitizes, gates, and rewrites. No intent classification,
no vocabulary bridging, no completeness check, no multi-hop detection.

- **Pseudo-Relevance Feedback (PRF) reformulation** — When the scope gate passes
  _(Note: a lighter-weight alternative — vocabulary-normalization query expansion fired
  in parallel with routing, entirely inside the knowledge service — is tracked in
  `src/knowledge/TODO.md` §5c. Evaluate that first before adding gateway-side PRF.)_
  but the query uses informal vocabulary, do a preliminary keyword pass against the
  knowledge index outline and feed the raw hits to the LLM: "Given this query and
  these available index labels, rewrite the query to strictly use the terminology found
  in the index." Keeps expansion grounded in actual corpus vocabulary rather than
  world-model assumptions.

  UX risk: silent reformulation creates a frustrating loop. Two mitigations:
  1. **Inline reformulation line** — Begin every answer with one short line showing
     the interpreted query: "Searching for: evacuation procedure, post-drill personnel
     check." Inline and unavoidable; gives the user a correction handle.
  2. **Repetition = negative feedback** — If the same (or near-identical) query appears
     again within the same session, suppress PRF and run the literal query.

- **Query completeness check** — Before retrieval, a single LLM prompt asks: "Is this
  query complete enough to answer, or is a required parameter missing?" If below threshold,
  ask a clarifying question rather than silently retrieving on an underspecified query.
  No separate classifier model needed — a prompt-based judge is sufficient at this corpus scale.

- **Multi-question decomposition** — A single message can contain multiple distinct questions.
  Example: "My son lost his hat, who can I call?" contains two questions: (1) what is the
  lost-items policy, and (2) who is the person responsible for lost items. The current pipeline
  treats the message as one query and typically answers whichever sub-question the retrieval
  selects — the second is silently dropped.

  Mitigation: after the scope gate passes, run a decomposition prompt: "Does this message
  contain more than one distinct question? If so, list each as a standalone query." If the
  result is a list, run each sub-query through the Stage A → Stage B pipeline independently
  and concatenate the answers in order. Single-question messages pass straight through with
  no added latency. A cheap structural model (Flash Lite) is sufficient for decomposition.

- **Multi-hop detection** — When knowledge synthesis returns "see other policy / see separate
  section", there is no follow-up retrieval pass. A post-synthesis check for these phrases
  could trigger a second retrieval round. See Stage 4 cross-reference item.

- **Language detection and response language enforcement** — The LLM currently chooses the
  response language on its own and makes mistakes. Detect whether the question is Spanish or
  English, then explicitly instruct synthesis to respond in that language.

  Cheapest implementation: extend the existing classifier call in `scope_gate.py` to also
  return `"language": "es" | "en" | "other"` — zero extra LLM cost since the classifier
  already reads the full query. Thread `language` through to the knowledge search request
  and inject `"Respond in Spanish." / "Respond in English."` into the synthesis prompt.

  Edge cases to handle:
  - `"other"`: fall back to English (or the corpus language) — do not leave it to the LLM.
  - Canned responses (`ORIENTATION_RESPONSE`, `OUT_OF_SCOPE_REPLY`, `BROAD_QUERY_PREFIX`)
    are hardcoded strings and must be localized. Add `_ES` / `_EN` variants in `config.py`
    and select by detected language.
  - Mixed-language queries: treat the dominant language as authoritative; if truly ambiguous,
    default to English.

- **Corpus-grounded glossary** (low priority — PRF is strictly more general) — One offline
  LLM job over the index that produces a term→label mapping (e.g. "fire drill" → "evacuation
  procedure; personnel check"). Inject the mapping into the reformulation prompt at query time.
  Advantage over PRF: deterministic and auditable. Implement only if PRF misses systematic,
  recurring patterns.

---

## Stage 1 — Access control and rate limiting

- **Rate limiting** — Identity-based quotas to prevent DoS and resource exhaustion.
  Storage backend options: Firestore (durable across restarts, ~5ms latency per check)
  vs in-memory dict (zero latency, resets on restart, not shared across instances).
  Recommendation: Firestore counter with sliding window; implement when scaling beyond
  single instance. Target: 20 RPM per user.

- **group_ids filtering** — The knowledge service accepts `group_ids` but ignores them
  (stub). The gateway should pass the user's permitted source IDs here once the access
  service is implemented.

- **PII redaction** — Automatically mask or block sensitive PII (emails, credit card
  numbers, Hungarian ID numbers) before it enters logs or the LLM. Can use regex patterns
  for high-confidence cases; LLM-based detection for subtler cases.

---

## Stage 2 — Retrieval hint forwarding

The gateway currently forwards the raw (rewritten) query to knowledge. It could also
forward retrieval hints derived from the query understanding stage.

- **Intent tag forwarding** — Pass a structured intent tag to knowledge: `{type: "procedural",
  topic: "evacuation"}`. Lets the knowledge service adjust its prompting without the gateway
  needing to know retrieval internals.

- **Two-stage selection hint** — Forward the scope gate's classification reasoning as a
  "focus hint" to knowledge: "User is asking about post-event procedures, not pre-event
  preparation." Knowledge can inject this into the discriminate prompt.

---

## Bugs

- ~~**`KNOWLEDGE_SERVICE_URL` defaults to empty string** — silent misconfiguration: the service
  starts and all knowledge calls silently fail. Add a startup assertion:
  `if not KNOWLEDGE_SERVICE_URL: raise RuntimeError("KNOWLEDGE_SERVICE_URL is not set")`.
  One line in `config.py` or `main.py` startup.~~ DONE 2026-04-26.

- **Synchronous identity token fetch in async path** — `google.auth.transport.requests`
  token refresh is blocking I/O called from an async handler, stalling the event loop
  under concurrent load. Wrap with `asyncio.run_in_executor(None, ...)` or switch to
  `google.auth.transport.aiohttp`.

- ~~**Corpus summary never expires**~~ DONE 2026-04-26. 10-minute TTL added to
  `_get_corpus_summary()` in `routers/chat.py`. Falls back to stale value (not fallback string)
  if refresh fails while a cached value exists.

- **Feedback buttons missing on short-circuit exits** — Out-of-scope and vague (Tier 2/3)
  responses do not emit a `trace_id` in the SSE stream, so the frontend never renders thumb
  buttons. This is wrong: feedback is most valuable when the classifier made the wrong call.
  Fix: write the trace doc and emit `trace_id` in the `answer` event for *all* pipeline exits,
  including short-circuits. The trace doc will have `pipeline_path: "out_of_scope"` or
  `"vague"` and empty `knowledge.*` fields.

- **Citation/source list mismatch** — Query: "What should a teacher do if a student is injured?"
  Every block in the answer cited `[en_policy3_health_safety_reporting:2.4]`, but the `sources`
  field listed 3 chunks from that document and 3 chunks from a different document. Either the
  synthesis prompt is pinning all citations to the first retrieved chunk while still consuming
  content from the others, or the sources list is returning more chunks than the LLM actually
  used. The two fields must agree: every cited chunk must appear in sources, and every source
  must be cited at least once.

---

## Stage 3 — Output quality checks

- **Numbered citations** — The sources list should be numbered (1, 2, 3…) and in-text
  references should use only that number (`[1]`, `[2]`), not the full chunk ID like
  `[en_policy3_health_safety_reporting:2.4]`. The synthesis prompt should assign numbers
  to retrieved chunks before generating the answer and instruct the LLM to cite by number only.



- **NLI faithfulness post-check** — After synthesis, run a second LLM prompt: "Does this
  answer contradict or omit any condition present in the retrieved sections?" Flag as a
  silent failure if yes. Catches the "but not if high-risk" drop.

  Lightweight implementation: same LLM (Gemini Flash), prompt-based judge, no external
  NLI model (DeBERTa etc) required. One extra LLM call per query.

- **Citation verification** — Check that every source_id in the facts list corresponds
  to a real document in the index. Prevents hallucinated citations. Pure string match,
  no LLM call needed.

- **Confidence threshold / "I don't know"** — If the knowledge service returns an answer
  with zero facts, treat it as low-confidence and add a disclaimer or return a structured
  "I cannot answer this from the available documents" response.

---

## Stage 4 — Multi-hop and cross-reference handling

- **ReAct cross-reference loop** — When synthesis returns "see other policy / see separate
  section", no follow-up retrieval occurs. Implement a loop: the gateway detects cross-reference
  phrases in the answer, issues a second knowledge call with the referenced section/policy,
  and synthesizes again. Hardcode `max_iterations = 3`.

  Note: if Stage 5 embedding-based cross-references are implemented in knowledge, this
  becomes less necessary — keep as fallback for in-document cross-refs.

---

## Stage 5 — Moderation and safety

- **Moderation gate** — Use an LLM-based or API-based classifier to detect toxic, hateful,
  or self-harm content before the scope gate. Route sensitive topics (e.g. mental health
  crisis mentions) to a hardcoded response or human handoff workflow rather than policy RAG.

- **Prompt injection detection** — Detect and block inputs that attempt to override system
  instructions ("ignore previous instructions", "you are now", etc.). Current sanitizer only
  strips HTML; prompt injection requires semantic detection.

---

## Session management

- **Session expiry** — Current in-memory sessions never expire; they accumulate until container
  restart. Add a TTL: evict sessions older than N minutes (default: 30 min). Simple: store
  `{turns, last_active}` per session, sweep in a background task.

- **Persistent sessions** — For multi-instance deployments, in-memory sessions are not shared
  across containers. Firestore-backed sessions would fix this. Defer until scaling requires it.

---

## Observability — full pipeline trace to BigQuery

Every request produces a complete trace: all LLM inputs and outputs verbatim, all
inter-service calls, token counts, latencies, and the final answer. Traces are written
to BigQuery for SQL analytics. Firestore holds only the lightweight feedback record
(rating + comment, keyed by `trace_id`).

**Why BigQuery, not ELK or OpenTelemetry:**
OpenTelemetry is the right choice for latency/span tracing and we may add it later,
but it does not support analytical queries over payload content. ELK requires
self-managed infrastructure. BigQuery is GCP-native, serverless, pay-per-query, and
handles semi-structured JSON natively — the right fit for "which chunks appear most"
or "questions with no answers".

### Trace schema (BigQuery table: `traces.pipeline_v1`)

```
trace_id                STRING    — uuid, generated at pipeline start
session_id              STRING
timestamp               TIMESTAMP — UTC
pipeline_path           STRING    — "out_of_scope" | "orientation" | "specific" | "broad"

input.raw_message       STRING
input.sanitized_query   STRING
input.sanitize_warning  STRING    NULLABLE

classifier.corpus_summary     STRING    — full outline fed to the prompt
classifier.prompt             STRING    — verbatim prompt as sent
classifier.raw_response       STRING    — response.text from the model
classifier.in_scope           BOOL
classifier.specific_enough    BOOL
classifier.latency_ms         INT64

rewrite.history               JSON      — list of {q, a} turns used as context
rewrite.original_query        STRING
rewrite.rewritten_query       STRING    NULLABLE
rewrite.latency_ms            INT64     NULLABLE

topics.request_query          STRING
topics.l1_topics              JSON      — raw list[{doc_id, id, title}]
topics.topic_count            INT64
topics.labels                 JSON      — consolidated label list
topics.overview               BOOL
topics.latency_ms             INT64     NULLABLE

knowledge_search.request_query   STRING
knowledge_search.overview        BOOL
knowledge_search.answer          STRING    — raw answer before BROAD_QUERY_PREFIX
knowledge_search.facts           JSON      — list[{fact, source_id, valid_at}]
knowledge_search.selected_nodes  JSON      — synthesis.selected_nodes verbatim
knowledge_search.latency_ms      INT64     NULLABLE

output.answer                 STRING    — final answer shown to user
output.facts                  JSON

feedback.rating               INT64     NULLABLE  — +1 or -1; written later by POST /feedback
feedback.comment              STRING    NULLABLE
feedback.rated_at             TIMESTAMP NULLABLE
```

### Implementation notes

- Gateway accumulates the trace dict in a local variable during `generate()`.
- After the `answer` SSE event is yielded, fire-and-forget
  `asyncio.create_task(write_trace(trace))` — does not block the response.
- `write_trace` calls the BigQuery streaming insert API (`insert_rows_json`).
  One row per request. No batching needed at this scale.
- `trace_id` is added to the `answer` SSE event payload so channel_web can
  attach it to the feedback POST.
- `POST /feedback` (channel_web) updates `feedback.*` fields in the same BigQuery
  row via a DML `UPDATE` — or appends a second row with the same `trace_id` and
  a `_feedback_only` flag if DML latency is a concern. Decide at implementation time.

### Prerequisite: knowledge service must expose selected_nodes

`POST /search` currently reads `synthesis.selected_nodes` internally in
`_facts_from_result` but does not return it to callers. Add it to `SearchResponse`
so the gateway can log it. See `src/knowledge/TODO.md`.

### What this enables

- Questions with zero facts returned → unanswerable query detection
- Per-chunk appearance frequency → identify overloaded or underloaded index nodes
- Classifier accuracy → compare `in_scope`/`specific_enough` against feedback ratings
- Rewrite quality → compare `original_query` vs `rewritten_query` vs user rating
- Latency breakdown per stage → identify bottlenecks before optimizing

---

## Evaluation

- **Reformulation logging** — Log every rewrite: original query, rewritten query, session_id.
  Lets us audit whether rewrites are helping or hurting. Ship before PRF.
  _(Superseded by full trace — reformulation is a subset of the trace schema above.)_

- **Scope gate accuracy** — Build a small test set (20-30 examples: in-scope and out-of-scope)
  and measure precision/recall. Run against `gemini-2.5-flash-lite` vs `gemini-2.5-flash`
  to validate model choice.

- **Latency breakdown** — Log per-stage timing: sanitize, scope_gate, rewrite, knowledge_call.
  Needed before optimizing. Scope gate and rewrite add ~1-2 LLM calls; measure the actual cost.
  _(Superseded by full trace — latency fields are in the trace schema above.)_

---

## Priority order — next implementation cycle

Ordered by impact/cost ratio.

1. **Full pipeline trace → BigQuery + 👎👍 feedback** — unlocks all analytics and user signal;
   prerequisite: knowledge service exposes `selected_nodes` in `SearchResponse`
   (see `src/knowledge/TODO.md` and `src/channel_web/TODO.md` for the full spec split)
2. **Scope gate accuracy test set** — validates the cheapest LLM call before we rely on it
3. **Multi-question decomposition** (Stage 0) — correctness gap: second sub-question is silently dropped
4. **PRF reformulation** (Stage 0) — fixes vocabulary gap, the most common retrieval failure
5. **Query completeness check** (Stage 0) — prevents silent failures on underspecified queries
6. **Confidence threshold / I don't know** (Stage 3) — trivial check, prevents confident wrong answers
7. **Rate limiting** (Stage 1) — needed before any public launch
8. **NLI faithfulness check** (Stage 3) — one extra LLM call, catches conditional clause drop
9. **Session expiry** — prevents memory leak in production
10. **ReAct cross-reference loop** (Stage 4) — real engineering work; defer until synthesis quality is otherwise stable
11. **PII redaction** (Stage 1) — regex patterns first, LLM detection later
12. **Pipeline parallelization** — see `docs/design/parallelization_ideas.md` for full analysis.
    Three changes in priority order:
    (a) Merge `/topics` + `/search` into one call — eliminate duplicate routing+selection (~1100ms saved every specific query, zero cost).
        Knowledge service exposes breadth detection internally, returns `was_overview: bool`; gateway drops the `/topics` call entirely.
        Touch: `knowledge/indexer/multi.py`, `knowledge/main.py`, `gateway/services/knowledge_client.py`, `gateway/routers/chat.py`.
    (b) Wire `/search/stream` into gateway + channel_web — stream synthesis tokens; cuts perceived first-byte from ~1500ms to ~300ms.
        Prerequisite: BigQuery trace (needs `trace_id` on the terminal `answer_done` event).
    (c) Parallel classify + rewrite — fire both concurrently, cancel rewrite if OOS/vague.
        ~700ms saved on multi-turn specific queries. Measure multi-turn rate from traces before implementing.
