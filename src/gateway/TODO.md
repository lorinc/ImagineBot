# TODO — gateway open questions and next steps

_Append-only. Resolve items by striking through and noting the outcome._

Priority order for next implementation cycle at the bottom.

---

## Stage 0 — Query understanding

The current pipeline sanitizes, gates, and rewrites. No intent classification,
no vocabulary bridging, no completeness check, no multi-hop detection.

- **Pseudo-Relevance Feedback (PRF) reformulation** — When the scope gate passes
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

## Stage 3 — Output quality checks

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

## Evaluation

- **Reformulation logging** — Log every rewrite: original query, rewritten query, session_id.
  Lets us audit whether rewrites are helping or hurting. Ship before PRF.

- **Scope gate accuracy** — Build a small test set (20-30 examples: in-scope and out-of-scope)
  and measure precision/recall. Run against `gemini-2.5-flash-lite` vs `gemini-2.5-flash`
  to validate model choice.

- **Latency breakdown** — Log per-stage timing: sanitize, scope_gate, rewrite, knowledge_call.
  Needed before optimizing. Scope gate and rewrite add ~1-2 LLM calls; measure the actual cost.

---

## Priority order — next implementation cycle

Ordered by impact/cost ratio.

1. **Reformulation logging** — pure observability, zero-cost, ships with Stage 0 anyway
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
