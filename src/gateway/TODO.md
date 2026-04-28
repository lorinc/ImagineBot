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
  Example (confirmed real failure 2026-04-27): "My son has lost his hoodie. Who should I talk to?"
  contains two questions: (1) what is the lost-items policy (location + monthly display schedule),
  and (2) who is the named contact for lost & found (María Luisa / Madhu, Secretaries). The
  current pipeline treats the message as one query and typically answers whichever sub-question
  the retrieval selects — the second is silently dropped. Tracked in eval as ce-001.

  Mitigation: after the scope gate passes, run a decomposition prompt: "Does this message
  contain more than one distinct question? If so, list each as a standalone query." If the
  result is a list, run each sub-query through the Stage A → Stage B pipeline independently
  and concatenate the answers in order. Single-question messages pass straight through with
  no added latency. A cheap structural model (Flash Lite) is sufficient for decomposition.

- **Multi-hop detection** — When knowledge synthesis returns "see other policy / see separate
  section", there is no follow-up retrieval pass. A post-synthesis check for these phrases
  could trigger a second retrieval round. See Stage 4 cross-reference item.

- **Language detection (prerequisite for translation)** — Extend the existing classifier
  call in `scope_gate.py` to also return `"language": "es" | "en" | "other"` — zero extra
  LLM cost since the classifier already reads the full query. Thread `language` through the
  pipeline so downstream steps can use it. This is a prerequisite only; it does not fix
  translation quality on its own (see item below).

  Edge cases:
  - `"other"`: default to English.
  - Canned responses (`ORIENTATION_RESPONSE`, `OUT_OF_SCOPE_REPLY`, `BROAD_QUERY_PREFIX`)
    are hardcoded strings and must have `_ES` / `_EN` variants in `config.py`.
  - Mixed-language queries: treat the dominant language as authoritative.

- **Translation quality — Spanish (Castellano)** — Simply instructing the LLM to "respond
  in Spanish" is insufficient and has already been observed to produce poor results. This
  school is English-medium, but ~80% of families are Spanish-speaking and many have limited
  English. Translation quality — including correct Castilian/Latin-American register — is
  a first-class correctness requirement, not a style preference.

  The problem is unsolved. Known candidate approaches being evaluated:
  1. **Term dictionary** — A curated glossary of school-specific terms with verified
     Spanish translations (e.g. "Infant Community" → "Comunidad Infantil"). Injected into
     the synthesis prompt. Deterministic and auditable. Does not help with full-sentence
     fluency or idiomatic phrasing.
  2. **Bilingual document enrichment** — Ingest translated versions of key documents
     alongside the English originals, and allow synthesis to draw on Spanish source text
     directly rather than translating English output. Preserves idiom and phrasing but
     requires translation of source documents.
  3. **Post-synthesis translation pass** — After synthesis produces an English answer,
     run a second dedicated translation call with school-specific context. More expensive;
     translation errors can compound synthesis errors.

  Next step: empirical evaluation. Run a set of Spanish-language queries through each
  approach and score the outputs with native Castilian speakers. Do not commit to an
  architecture before that data exists. Track evaluation results in a spike doc when
  the work begins.

- **Corpus-grounded glossary** (low priority — PRF is strictly more general) — One offline
  LLM job over the index that produces a term→label mapping (e.g. "fire drill" → "evacuation
  procedure; personnel check"). Inject the mapping into the reformulation prompt at query time.
  Advantage over PRF: deterministic and auditable. Implement only if PRF misses systematic,
  recurring patterns.

---

## Pipeline order — rewrite before classify

**What it is:** Currently the pipeline classifies the raw user message, then rewrites it.
The classifier therefore sees terse follow-ups like "And what about balls?" in isolation
and may flag them as underspecified. Instead, the rewrite step must run first so the
classifier always receives an expanded, context-resolved question:
"What are the policies on bringing recreational items to school, especially balls?"

**Why:** The rewrite is what makes the bot intelligent. Every downstream gate —
classify, topics, search — should operate on the fully-resolved question, not on
whatever terse fragment the user typed.

**Implementation:**
1. In `routers/chat.py`, move the rewrite block (currently step 3 after classify) to
   before the classify block (currently step 2). Run rewrite whenever `history` is
   non-empty and `not override_active`. Set `final_query` from the result.
2. Pass `final_query` to `classify()` instead of `query`.
3. Remove the `history` parameter from `classify()` and from `scope_gate._PROMPT`
   and `_prior_exchange_block()` — the history context is now injected at the rewrite
   step, not the classify step. Item O's rationale is superseded.
4. `final_query` flows through unchanged to topics and search (no second rewrite).

**Side effects:**
- `scope_gate.py`: remove `history` param, `_prior_exchange_block`, `{prior_exchange}` in prompt.
- `tests/gateway/test_scope_gate.py`: remove history-related tests (those cases are now
  handled by rewrite, not by classifier history injection).
- `tests/gateway/test_chat_flow.py`: update `test_session_id_persists_across_requests` —
  `rewrite_standalone` is now called before classify, so patching order matters.

**Files:** `routers/chat.py`, `services/scope_gate.py`,
`tests/gateway/test_scope_gate.py`, `tests/gateway/test_chat_flow.py`.

---

## Conversation policy (gate behaviors)

Gate behavior items designed in the 2026-04-27 spec session. Implementation order in SPRINT.md
items G–K. Full design rationale in that session's conversation context; key decisions noted
inline below.

### Gate 1 — Scope override

**What it is:** When Gate 1 fires `OUT_OF_SCOPE_REPLY`, the user should be able to assert
"this is a school question, look it up" and have the system attempt retrieval anyway.

**Two sub-cases handled differently:**
- User rephrases with school context ("actually this is about the school catering menu") →
  classifier re-evaluates the new message, likely flips `in_scope=True` on its own. No special
  handling required — already works.
- User asserts without rephrasing ("no, look it up anyway", "check the docs", "just search it") →
  the assertion message is itself OOS. Requires session-aware override detection.

**Design decision:** On a detected override, retry the PREVIOUS query verbatim (from session
history), bypassing Gate 1. If Gate 3a/3b then fires, return that response as-is. Override is
a one-shot bypass — do not loop further.

**Implementation:**
1. Store `last_pipeline_path` and `last_query` in `_sessions[session_id]` alongside `turns`.
   Both are available at the end of each request in `chat.py`; just persist them.
2. In `chat.py`, before calling `classify()`: if `session.get("last_pipeline_path") == "out_of_scope"`
   AND current message matches override intent → set `in_scope=True` forcibly and substitute
   `session["last_query"]` as the working query.
3. ~~Override intent detection: start with a gateway-level phrase check — message is short (<15 words)
   AND contains trigger phrases ("look it up", "check", "search", "that is about the school",
   "in the documentation", "check anyway"). Define trigger phrases in `config.py`. Upgrade to
   classifier context injection if false positive rate is high in practice.~~
   **→ Superseded by sprint item M. See "Gate 1 — Override intent: LLM classifier" below.**

**Files:** `routers/chat.py` (session state persistence + override detection),
`config.py` (OVERRIDE_TRIGGER_PHRASES list).

**Tests:**
- Prior OOS turn, user says "look it up" → Gate 1 bypassed, prior query retried through full pipeline
- Prior OOS turn, user rephrases with school context → classifier evaluates new message, may flip naturally
- No prior OOS, user says "just check" → Gate 1 fires normally (no prior context to trigger override)
- Prior OOS, user sends clearly unrelated next message → Gate 1 fires normally

---

### Gate 1 — Override intent: LLM classifier

**What it is:** Replace the `OVERRIDE_TRIGGER_PHRASES` list + word-count heuristic with an LLM
classifier call that determines whether the user's message expresses override intent given the
conversation context (last turn was OOS).

**Why:** Phrase matching (`any(phrase in query.lower() ...)`) is the opposite of every intent
detection pattern in this codebase. It produces false negatives for any phrasing not in the list,
and false positives when trigger words appear in an unrelated message. The classifier already
handles intent detection; override intent is just another classification task.

**Implementation:**
1. Add a new function in `services/scope_gate.py`:
   `async def classify_override_intent(query: str) -> bool`
   Single LLM call with `response_mime_type="application/json"` and schema `{"override": bool}`.
   Prompt context: the assistant just replied that the question is out of scope; the user sent
   `query`; does the user intend to ask the assistant to search anyway, regardless of scope?
   Temperature 0.0.
2. In `routers/chat.py`, replace the `OVERRIDE_TRIGGER_PHRASES` guard with:
   `override_active = session.get("last_pipeline_path") == "out_of_scope" and await classify_override_intent(query)`
3. Remove `OVERRIDE_TRIGGER_PHRASES` from `config.py` and all imports.

**Files:** `services/scope_gate.py` (new `classify_override_intent`), `routers/chat.py`
(replace guard), `config.py` (remove `OVERRIDE_TRIGGER_PHRASES`).

**Tests:**
- Prior OOS, message = "look it up" → override intent True → bypass
- Prior OOS, message = "actually can you check the school website for this?" → override intent True → bypass
- Prior OOS, message = "what is the lunch menu?" (new unrelated question) → override intent False → classify normally
- No prior OOS, message = "just search" → guard does not fire (no OOS session state)

---

### ~~Gate 2 — Classifier schema expansion~~ DONE 2026-04-28

**What it is:** The current classifier returns `{in_scope: bool, specific_enough: bool}`.
`specific_enough=False` fires a single generic `ORIENTATION_RESPONSE`. This conflates three
distinct failure modes that require different responses.

**New classifier output schema** (change `scope_gate.py` prompt + `_SCHEMA` + `classify()` return):
```
{
  "in_scope": bool,
  "query_type": "answerable" | "underspecified" | "overspecified" | "multiple",
  "sub_questions": ["..."],   // only when query_type == "multiple"; each a standalone query
  "missing_variable": "..."   // only when query_type == "underspecified"; e.g. "school level", "role"
}
```

**Gate behaviors by `query_type`:**
- `answerable` — Gate 2 passes; proceed to retrieval. Replaces `specific_enough=True`.
- `underspecified` — Ask ONE targeted clarification question naming the `missing_variable`. No KB call.
  Store the original query in session so the follow-up re-runs it with the variable injected via
  `rewrite_standalone()`. Copy: "To answer this, I need to know: [missing_variable]. Could you tell me?"
- `overspecified` — Gate 2 passes. Before retrieval, run a generalization rewrite: strip the
  over-specific constraints and reformulate as a broader query (e.g. "sick leave policy for
  primary teachers hired before 2020 on probation" → "sick leave policy for primary teachers").
  Retrieve on the generalized query. Prepend the answer with an explicit note:
  "Your question was very specific, so I looked up a more general answer. If you think I've
  made a mistake with this generalization, please say so and I'll try to answer your original
  question." Store the original query in session so a pushback triggers a retry on the original —
  same mechanism as Gate 1 override (session `last_pipeline_path = "overspecified_generalized"`,
  `last_query = original query`).
- `multiple` — Extract `sub_questions`; pass to parallel orchestration (see Gate 2 — Multiple
  questions below). Gate 2 passes.

**Migration note:** `specific_enough` can be removed once `query_type` is in place. Update all
tests — `specific_enough=False` mapped to `query_type == "underspecified"`.

See also §Stage 0 — "Query completeness check" (earlier entry, same problem, this item supersedes it).

**Files:** `services/scope_gate.py` (prompt, `_SCHEMA`, `classify()` return type),
`routers/chat.py` (gate branching on `query_type`), `config.py` (clarification response copy).

**Tests:**
- "What are the rules?" → underspecified (no topic) → clarification request naming missing variable
- "What is the sick leave policy for primary teachers hired before 2020 on probation?" → overspecified → generalized to "sick leave policy for primary teachers" → answer with generalization note
- "My son lost his hoodie. Who should I contact?" → multiple → sub_questions extracted
- "What is the uniform policy?" → answerable → proceed

---

### Gate 2 — Multiple questions: parallel orchestration

**What it is:** When `query_type == "multiple"`, run each sub-question through the full retrieval
pipeline concurrently, then synthesise a single coherent combined answer.

**Context:** Confirmed real failure — "My son has lost his hoodie. Who should I talk to?" contains
two questions: (1) what is the lost-items policy, (2) who is the named contact. Current pipeline
answers whichever sub-question retrieval selects; the other is silently dropped. See eval item ce-001.
Also see §Stage 0 — "Multi-question decomposition" (earlier entry; this item supersedes it with the
full design decision).

**Design decision:** The sub-questions are likely related and the final answer requires synthesis,
not concatenation. Produce coherent prose, not a bulleted list of independent answers.

**Implementation:**
1. After classifier returns `query_type == "multiple"`, run `asyncio.gather` over
   `knowledge_client.search_stream(sq, trace_id=trace_id)` for each sub-question. Reuse the
   same `trace_id`; log all sub-results in the trace under a `sub_queries` key.
2. Gate 3a/3b apply per sub-question independently. If a sub-question hits Gate 3, include a
   partial-miss note in the combined answer: "For [topic], no documentation was found."
3. After all results arrive, call `services/multi_answer.py` — a new module with a single
   synthesis function. Feed all `(sub_question, answer)` pairs to one LLM call:
   "These are answers to related sub-questions from one parent message. Write a single coherent
   response addressing all of them. Preserve all facts and citations."
4. Merge `facts` from all sub-results (deduplicate by `source_id`).
5. Emit progress events during parallel retrieval. Single `answer` SSE event at the end.

**Edge case:** If a sub-question is OOS, skip it silently and answer the rest. Do not surface
OOS copy for individual sub-questions.

**Files:** `routers/chat.py` (parallel orchestration), `services/multi_answer.py` (new —
combined synthesis prompt and call), `services/knowledge_client.py` (no changes needed).

**Dependency:** Gate 2 classifier schema expansion must ship first (sprint item H before I).

**Tests:**
- Two answerable sub-questions → both covered in single coherent answer
- One answerable + one Gate 3a miss → combined answer with partial-miss note for second
- Single-question message → no decomposition, standard pipeline, no latency added

---

### Gate 3a — Retrieval miss: adjacent topic surfacing

**What it is:** When Gate 3a fires (`selected_nodes == []`), instead of the canned
`NO_EVIDENCE_REPLY`, surface which documents were considered and what L1 sections exist,
so the parent can decide to rephrase or accept that the topic is undocumented.

**Target response (dynamic, not canned):**
"We looked at [document name(s)] but couldn't find relevant sections. Related topics we do have:
[L1 section list from routed docs]. Would you like to ask about any of these, or rephrase?"

**Information required:** Stage 1 routing ran and selected documents before Stage 2 found nothing.
The knowledge service needs to return which docs were routed and their L1 sections.
See `src/knowledge/TODO.md §Gate 3a — routing candidates` for the knowledge-side change.
Shape: `routing_candidates: [{"doc_name": str, "l1_sections": [str]}]` — additive field on
`SearchResponse`, `None` when `selected_nodes` is non-empty.

**Gateway implementation:**
1. Check `result.get("selected_nodes") == []` AND `result.get("routing_candidates")` is non-empty.
2. Construct response dynamically from `routing_candidates`. Cap at 5–6 section titles total
   to avoid overwhelming. Human-readable: strip underscores, title-case `doc_id`.
3. Do NOT call an LLM. Simple string builder in `chat.py` or a helper in `services/gate_replies.py`.
4. `pipeline_path = "in_scope_no_evidence"` (unchanged). `facts = []`.

**Files:** `routers/chat.py` (Gate 3a response construction),
`config.py` (Gate 3a response template string).

**Dependency:** Knowledge service routing_candidates change (sprint item K; can ship together).

---

### Gate 3b — Synthesis abstention: transparency

**What it is:** When Stage 2 found nodes but synthesis concluded they don't answer the question,
tell the parent which sections were checked and invite rephrasing — instead of silently returning
the synthesis abstention text as if it were a real answer.

**Root cause of current failure (confirmed UAT 2026-04-27):** `selected_nodes` reflects nodes
sent TO synthesis, not nodes synthesis found useful. The synthesis prompt instructs the model to
emit a specific abstention string, but this is unstructured — the gateway cannot distinguish it
from a real answer. "Are children allowed to climb trees in the school garden?" → H&S node
selected → synthesis said "The provided sections do not answer this question." → Gate 3 did not fire.

**Fix requires two parts:**

*Part 1 — Knowledge service:* Add `has_answer: bool` to `SearchResponse`.
See `src/knowledge/TODO.md §Gate 3b — has_answer flag`.

*Part 2 — Gateway:* After receiving search result, check
`result.get("has_answer", True) == False` AND `result.get("selected_nodes")` is non-empty.
Construct response dynamically:
"Based on your question, we looked at: [selected_nodes as 'Doc Name > Section Title'].
No answer was found in those sections. Try rephrasing, or ask about one of those topics directly."

Format `selected_nodes` as human-readable: `{doc_id.replace('_', ' ').title()} > {node title}`.
Cap at 5 sections.

`pipeline_path = "in_scope_no_synthesis"` (new value — distinguishes from Gate 3a
`"in_scope_no_evidence"`). `facts = []`.

Do NOT call an LLM to construct this response.

**Files:** `routers/chat.py` (Gate 3b detection + response construction),
`config.py` (pipeline_path constant `"in_scope_no_synthesis"`).

**Dependency:** Knowledge service `has_answer` flag (sprint item J; must ship together).

---

### Gate 3 — Contact offer follow-up  BUG — UAT fail 2026-04-27

**What it is:** When Gate 3 fires after a Gate 1 override, `gate3_fallback_prompt()` offers
to look up who to contact. When the user replies "yes", that reply hits `classify()` cold
(no history), is flagged OOS, and returns the standard OOS deflection.

**Root cause:** `classify()` receives no session history. Short affirmative follow-ups are
evaluated in isolation with no conversational context, so "yes" is always OOS.
The offer and the follow-up handling are both correct in principle — the pipeline just lacks
the context to interpret the reply.

**Fix:** Pass session history into `classify()` — see §Contextual classify below (sprint item O).
With history, the classifier correctly interprets "yes" in context of the prior offer.
The rewrite step already uses history and will produce the right query naturally
(e.g. "yes" + "Would you like me to look up who handles this?" → "who can I contact about X?").

No gateway state machine, no per-intent classifier, no second-search branching in `chat.py`.
The offer string in `services/prompts.py` stays. No other changes needed in this service.

**Resolved by:** Sprint item O (contextual classify). Ship O to close this bug.

---

### ~~Contextual classify: session turns into scope gate~~ DONE 2026-04-28

**What it is:** Short follow-up utterances ("yes", "go ahead", "please do") hit the scope
classifier without any session context and are evaluated in isolation. A bare "yes" is OOS;
with context (the bot just asked a follow-up question) it is clearly in-scope intent.

**Fix:** Pass the last N turns from session history into `classify()` as conversational context.
The classifier prompt already produces structured JSON — extend it to receive a `history` field
so it can interpret terse follow-ups correctly.

**Design decision:** N = 2 turns (last user message + last bot reply). More than that is noise
for classification purposes; the relevant context is always the immediately preceding exchange.

**Implementation:**
1. In `routers/chat.py`, pass `session.get("turns", [])[-2:]` to `classify()` as `history`.
2. In `services/scope_gate.py`, extend `classify(query, history=[])`:
   - If `history` is non-empty, prepend a "Prior exchange:" block to the prompt before the query.
   - Format: `User: {q}\nAssistant: {a}` for each turn.
3. No schema change — classifier still returns `{in_scope, specific_enough}`.

**Files:** `services/scope_gate.py` (extend prompt + function signature),
`routers/chat.py` (pass history slice to classify).

**Tests:**
- Prior turn: bot asked "Would you like X?" → user says "yes" → classify sees context → in_scope True
- Prior turn: OOS deflection → user says "ok thanks" → classify sees context → in_scope False (acceptance, not query)
- No prior turns → classify called without history → behaviour unchanged (regression guard)

---

### ~~Gate 3 — LLM fallback reply~~ DONE 2026-04-27

**What it is:** When Gate 3 fires (no evidence or synthesis abstention) AND the user
explicitly requested a search (override path), the canned no-evidence reply is jarring
and unhelpful. Instead, pass the full narrative to the LLM and let it respond naturally.

**Trigger condition:** `override_active == True` AND Gate 3 fires (either 3a or 3b).

**Narrative given to the LLM:**
- The original user question
- That the user explicitly asked to search even after an out-of-scope reply
- That the knowledge base was searched and returned no relevant documentation
- Instruction: respond helpfully, acknowledge the search came up empty, answer from
  general knowledge if appropriate for the context (school info bot)

**Design decision:** Do NOT apply this fallback on all Gate 3 fires — only when
`override_active`. The canned reply is acceptable for normal in-scope queries with
no evidence; it is specifically bad when the user insisted on searching.

**Implementation:**
1. New module `services/fallback_reply.py` — single async function
   `fallback_reply(query: str, override_context: bool) -> str`. One Gemini Flash Lite call.
   Prompt lives in `services/prompts.py` (create if not present; canonical home for all
   gateway LLM prompts).
2. In `chat.py`: when Gate 3 would fire AND `override_active`, call `fallback_reply()`
   instead of yielding the canned string. Stream result as normal `answer` SSE event.
3. `pipeline_path` unchanged — still `"in_scope_no_evidence"` or `"in_scope_no_synthesis"`.
   Add `"fallback_reply": true` to the trace for observability.

**Files:** `services/fallback_reply.py` (new), `services/prompts.py` (new or extend),
`routers/chat.py` (guard on override_active at Gate 3 exits).

**Tests:**
- Override active + no evidence → fallback_reply called, canned string NOT yielded
- Override active + no synthesis → fallback_reply called
- No override + no evidence → canned string yielded as before (regression guard)

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

  **Dependency on Gate H (classifier expansion):** Once `query_type` exists in the classifier
  output, it should be forwarded to the knowledge service as part of this intent tag. The
  `overview: bool` flag is already a primitive version of this pattern — `query_type` is its
  natural generalisation. The knowledge service can then select a synthesis prompt variant per
  type: overview summary for broad queries, step-preserving prompt for procedural queries,
  exception-emphasis prompt for conditional/if-then queries. Do not implement before Gate H
  ships — there is nothing to forward until the classifier produces `query_type`.

- **Two-stage selection hint** — Forward the scope gate's classification reasoning as a
  "focus hint" to knowledge: "User is asking about post-event procedures, not pre-event
  preparation." Knowledge can inject this into the discriminate prompt.

---

## Bugs

- ~~**`KNOWLEDGE_SERVICE_URL` defaults to empty string** — silent misconfiguration: the service
  starts and all knowledge calls silently fail. Add a startup assertion:
  `if not KNOWLEDGE_SERVICE_URL: raise RuntimeError("KNOWLEDGE_SERVICE_URL is not set")`.
  One line in `config.py` or `main.py` startup.~~ DONE 2026-04-26.

- ~~**Synchronous identity token fetch in async path**~~ DONE 2026-04-27. `run_in_executor` + 55-min TTL cache in `knowledge_client.py`.

- ~~**Corpus summary never expires**~~ DONE 2026-04-26. 10-minute TTL added to
  `_get_corpus_summary()` in `routers/chat.py`. Falls back to stale value (not fallback string)
  if refresh fails while a cached value exists.

- ~~**Feedback buttons missing on short-circuit exits**~~ DONE. `trace_id` emitted in `answer` event for both `out_of_scope` and `orientation` exits; trace written via `write_trace` on both paths.

- **Override active does not bypass overspecified branch** — UAT fail 2026-04-28.
  When `override_active=True`, `classify()` still runs on the previous query and returns
  `query_type="overspecified"`, triggering the generalization+note path. Override should
  bypass Gate 2 (overspecified/underspecified) entirely and proceed straight to retrieval,
  mirroring how it bypasses Gate 1 (OOS). Fix: in `chat.py`, after the override guard sets
  `override_active`, skip the `query_type in ("overspecified", "underspecified")` branch and
  fall through to topics+search. Tracked as SPRINT BUG-Q1.

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



- **Answer relevance judge** — After synthesis, run a single Flash Lite call that checks
  two things: (1) does the answer actually address the user's question (Grice's Relation
  maxim — the "lost hoodie / who to contact" failure mode), and (2) is the answer in the
  language detected by the scope gate. Distinct from NLI faithfulness: faithfulness checks
  groundedness against retrieved documents; relevance checks whether the question was
  answered at all.

  **Design constraint — judge must be classification-aware:** "Does this answer the question?"
  has different criteria depending on `query_type`. A broad question answered with a high-level
  topic summary + drill-down options should pass; that same answer for a direct fact lookup
  should fail. The judge prompt must receive `query_type` alongside `(question, answer)` and
  apply type-appropriate criteria. Without this, the judge has no baseline — it will either
  over-reject overview answers or under-reject evasive direct answers.
  Prerequisite: Gate H (classifier expansion) must ship before this is unsheled.

  Implementation notes:
  - Lives in `services/answer_judge.py`. Returns a structured `AnswerJudgement` dataclass:
    `addressed: bool`, `language_correct: bool`. Prompt lives in `services/prompts.py` —
    this file does not yet exist in the gateway; create it as the canonical home for all
    gateway LLM prompts (migrate `scope_gate._PROMPT` and `rewrite._PROMPT` there too,
    importing them back into their respective modules). Keeps prompts findable and testable.
  - Called in `chat.py` after step 6 (search result received), before step 7 (stream answer).
  - On `addressed=False`: emit answer with `warning` field set; log the failure; record
    in trace.
  - On `language_correct=False`: one retry — re-issue the search request with an explicit
    language instruction; if it fails again, emit with warning. Never loop more than once.
  - Extensibility: `AnswerJudgement` is a dataclass — add new check fields as the judge
    grows without changing call sites. The prompt in `prompts.py` is the single place to
    add new criteria.

  Observability — full pipeline integration required:
  - Record a `gateway.answer.judge` span via `SpanCollector.record()` with attributes
    `{"addressed": bool, "language_correct": bool}` and duration_ms.
  - Add entries to `step_messages.py`:
    `"gateway.answer.judge"` → `"Answer checked: relevant · correct language"` (happy path)
    `"gateway.answer.judge.not_addressed"` → `"Answer may not fully address your question"`
    `"gateway.answer.judge.wrong_language"` → `"Language mismatch detected — retrying"`
  - Span emitted via `_thinking_sse()` in `chat.py` so it appears in the WebUI progress
    sequence between "processing" and the final answer event.
  - Include `judge: {addressed, language_correct, latency_ms}` in the Firestore trace doc
    and in the BigQuery trace schema (add to the Stage 3 observability section above).

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

- ~~**Session expiry**~~ DONE 2026-04-27. 30-min TTL; sweeper task runs every 5 min via `start_session_sweeper()` in lifespan.

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
