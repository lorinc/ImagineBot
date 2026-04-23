# Pipeline Parallelization Opportunities

Analysis of where the request pipeline can be parallelized or restructured to reduce latency.
See the gateway and knowledge TODO files for the actionable items derived from this.

---

## Current pipeline (happy path, single-turn)

```
sanitize (~0ms)
→ classify (1 LLM call, ~700ms)
→ [rewrite_standalone (1 LLM call, ~700ms) — multi-turn only]
→ POST /topics  → knowledge: routing (~500ms) + per-doc selection (~600ms concurrent)
→ POST /search  → knowledge: routing (~500ms) + per-doc selection (~600ms concurrent) + synthesis (~1500ms)
```

Estimated wall-clock: ~700 + 700 + 1100 + 2600 = **~5100ms** (multi-turn, specific query)

---

## 1. Eliminate double routing + selection  ★ highest impact

**Problem:** `POST /topics` and `POST /search` both internally call `query_multi_index`.
Both run Stage 1 (routing LLM) and Stage 2 (per-doc node selection). `/search` then adds
synthesis. This means every specific query runs routing and selection **twice in series**.

**Saving:** ~1100ms guaranteed on every specific query. Zero cost overhead.

**Fix:** Expose `l1_topics` (or `topic_count`) in `SearchResponse` alongside the answer.
The gateway makes one call to `/search`, reads the breadth signal from the response, and
prepends `BROAD_QUERY_PREFIX` if needed. The dedicated `/topics` call and the two-stage
breadth-check step in `chat.py` disappear.

Two implementation paths:

**Option A — gateway-side breadth signal (minimal change)**
- Add `l1_topics: list[TopicNode]` to `SearchResponse` in `knowledge/main.py`.
- `query_multi_index` already computes this; just surface it.
- Gateway runs `_count_topics(result["l1_topics"])` after `/search` returns, decides
  whether to prepend `BROAD_QUERY_PREFIX`. No second network call.
- Downside: synthesis runs with the wrong prompt (overview vs. specific) if the gateway
  decides post-hoc. The synthesis prompt is already baked into the answer at that point.

**Option B — knowledge-side breadth detection (cleaner)**
- Knowledge runs routing + selection, checks breadth internally, selects the appropriate
  synthesis prompt, and returns `was_overview: bool` in `SearchResponse`.
- Gateway just reads the flag and prepends `BROAD_QUERY_PREFIX` if true.
- `MAX_TOPIC_PATHS` and `SIBLING_COLLAPSE_THRESHOLD` move from `gateway/config.py` to
  `knowledge/indexer/config.py` (or stay in gateway and are passed as query params).
- Downside: gateway loses explicit control over the breadth threshold.

**Recommendation:** Option B. The breadth decision is a retrieval concern (how many topic
areas the query spans), not a routing/UX concern. Knowledge is the right owner.

---

## 2. Parallel classify + rewrite  ★★ medium impact, multi-turn only

**Problem:** After sanitize, `classify` and `rewrite_standalone` run sequentially even
though they are independent — rewrite does not affect scope/specificity judgement.

**Saving:** ~700ms on every multi-turn specific query (one LLM RTT removed from the
critical path). No saving on first-turn queries (rewrite is skipped).

**Cost:** On OOS or vague queries (~30–40% of traffic), the rewrite result is discarded —
one wasted LLM call per such query in multi-turn sessions.

**Implementation:**
```python
corpus_summary = await _get_corpus_summary()
classify_task = asyncio.create_task(classify(query, corpus_summary))
rewrite_task = asyncio.create_task(rewrite_standalone(query, history)) if history else None

in_scope, specific_enough = await classify_task
if not in_scope or not specific_enough:
    if rewrite_task:
        rewrite_task.cancel()
    # ... return early response
final_query = (await rewrite_task) if rewrite_task else query
```

Worth it when multi-turn session rate is >40% of traffic. Measure first (BigQuery trace).

---

## 3. Stream synthesis tokens to the client  ★★ high perceived-latency impact

**Problem:** The gateway waits for `/search` to return a complete answer before yielding
the `answer` SSE event. Synthesis takes ~1500ms. Users see nothing during this window.

**Saving:** First token visible to user ~300ms after synthesis starts (vs. 1500ms now).
No wall-clock reduction — total time is the same. Pure perceived-latency win.

**Implementation:** Wire up the existing `/search/stream` endpoint in `knowledge/main.py`
into `gateway/routers/chat.py`. The gateway forwards synthesis tokens as partial `answer`
SSE events. Channel_web appends tokens to the response div rather than replacing it.

This is a UX change as much as a backend change — channel_web needs to handle partial
answer events. Design the SSE event schema before implementing:
```
event: answer_chunk
data: {"text": "...", "session_id": "..."}

event: answer_done
data: {"facts": [...], "session_id": "...", "trace_id": "..."}
```

The `facts` and `trace_id` fields can only be sent after synthesis completes, so they
live on the terminal `answer_done` event. The feedback UI attaches to `answer_done`.

---

## 5. Precision without latency: spend the parallel budget on quality

The previous items use parallelism to *save* time. This section uses the same parallel slots
to *spend more compute* — doing more work at the same wall-clock cost.

**The structural insight:** Stage 2 (per-doc selection) is already `asyncio.gather` over
routed docs. Adding more docs, more passes per doc, or more query variants costs zero
additional wall-clock time. It only costs more LLM API calls.

### 5a. Widen routing to 3-4 docs

`make_route_prompt` currently says "Select 1–2 document IDs." Routing misses are
**unrecoverable** — if the right doc isn't in the routed set, Stages 2 and 3 never see it.
Widening to 3-4 adds more docs to Stage 2, which already runs concurrently over all of them.

**Hypothesis:** Widening routing to 3-4 docs reduces answer-misses on cross-cutting queries
(questions that touch two policy areas in different documents) without increasing latency.

**Test:** Identify queries that currently return "sections do not answer this question" or
low-rated answers. Check the trace to see which doc held the answer and whether it was
in the routed set. If routing miss rate > 15%, widen.

### 5b. Dual-pass selection per doc (direct + context framings)

Currently each doc gets one selection call: *"which leaf nodes directly answer the question?"*

Fire two concurrent calls per doc:
- **Pass A** (current): direct answer nodes
- **Pass B** (new): *"which sections provide required background, definitions, or context
  that a reader would need to understand the answer?"*

Union unique node IDs before synthesis. Both calls run concurrently inside `_select_from_doc`.
Synthesis receives richer input — catches the "technically answers the question but misses
the prerequisite context" failure mode.

**Hypothesis:** Dual-pass selection reduces answers that are technically correct but
incomplete (missing the "unless", the pre-condition, the definitional context).

**Test:** After implementing BigQuery trace, compare `selected_nodes` count and user
ratings between single-pass and dual-pass on the same queries. Expect no latency change,
improved rating on procedural questions that have prerequisites.

### 5c. Query expansion in parallel with routing

While Stage 1 routing runs (~500ms), fire a vocabulary-normalization call concurrently:
*"Rephrase this question using the formal policy document vocabulary a school handbook
would use. Keep the same question, change only the vocabulary."*

Feed both original and expanded query to Stage 2 selection. This addresses the vocabulary
gap failure mode: parent asks "sick day" → doc uses "illness absence procedure."

Related to PRF reformulation in `gateway/TODO.md` Stage 0, but differs: PRF rewrites against
index labels; this expansion call is pure vocabulary normalization, no index lookup needed.
Can live inside `query_multi_index` (knowledge-internal, no gateway change required).

**Hypothesis:** Query expansion reduces selection misses on informal/colloquial phrasing
without affecting precision (expanded query is a reformulation, not a broadening).

**Test:** Compare `selected_nodes` and ratings on queries that use informal vocabulary
("get fired", "call in sick", "fight at school") vs. their formal equivalents.

### 5d. Routing miss recovery via cheap parallel scan

In parallel with Stage 2 selection on routed docs, fire a structural-model pass on the
un-routed docs:
*"Does any section in this document contain information directly relevant to this question?
If yes, return the most relevant L1 section IDs."*

If any un-routed doc returns a hit, merge into Stage 3 alongside main selections.
Structural model (Flash Lite) is cheap and fast. This is a safety net for routing errors —
it fires on every query but contributes nodes only when routing was too narrow.

**Hypothesis:** Routing miss recovery catches the tail of routing errors (~10-20% of
queries where the routed docs are correct but incomplete) with minimal cost overhead.

**Test:** Track how often the recovery pass contributes nodes that end up in the final
synthesis (BigQuery: count queries where recovery nodes were used). If >10%, the main
routing is too narrow and Move 5a should be prioritized instead.

---

## 4. What is NOT worth parallelizing

**Stage 1 → Stage 2 speculation (start per-doc selection before routing finishes)**
Routing takes ~500ms and narrows N docs to 1–2. Speculating over all N docs wastes
N-2 selection calls per query (each ~600ms, quality model). For a corpus of ≤10 docs
this is strictly worse. Revisit only if corpus grows beyond 20 docs and routing becomes
the bottleneck.

**Sub-agents for per-doc selection**
Stage 2 already uses `asyncio.gather` over doc selection coroutines — they run
concurrently within the knowledge service. Making them separate HTTP services or separate
processes adds network overhead without latency benefit. The current model is correct.

**Speculative topic call during classify**
The topics call needs the final (rewritten) query to be accurate. For first-turn queries
the original == final, so speculation is possible — but the saving (~700ms) is smaller
than Option 1 (~1100ms) and adds cancellation complexity. Do Option 1 first; this
becomes moot because /topics disappears.

---

## Estimated latency budget before/after

| Path | Before | After (1+2+3) |
|------|--------|---------------|
| First-turn, specific | ~4400ms | ~3300ms (−25%) |
| Multi-turn, specific | ~5100ms | ~3300ms (−35%) |
| Out-of-scope / vague | ~700ms | ~700ms (unchanged) |

Streaming (item 3) reduces **perceived** first-byte from ~3300ms to ~500ms on specific
queries, without changing total wall-clock.

---

## Implementation order

**Latency savings (do these first):**
1. **Merge /topics + /search** (Option B above) — guaranteed saving, zero extra cost.
   Touch: `knowledge/main.py`, `knowledge/indexer/multi.py`, `gateway/routers/chat.py`,
   `gateway/services/knowledge_client.py`.
2. **Wire /search/stream in gateway + channel_web** — high UX impact, moderate effort.
   Prerequisite: BigQuery trace (needs `trace_id` on the terminal event).
3. **Parallel classify + rewrite** — measure multi-turn session rate from traces first;
   implement only if >40% of sessions are multi-turn.

**Precision improvements (do after BigQuery trace exists to measure effect):**
4. **Widen routing to 3-4 docs** (5a) — one-line prompt change; measure routing miss rate first.
5. **Dual-pass selection** (5b) — two concurrent calls in `_select_from_doc`; expect most gain
   on procedural / conditional questions.
6. **Query expansion in parallel with routing** (5c) — knowledge-internal; no gateway change.
   Measure on informal-vocabulary queries.
7. **Routing miss recovery** (5d) — implement only if 5a alone doesn't close the routing miss gap.
