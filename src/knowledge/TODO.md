# TODO — src/knowledge open work

_Append-only. Resolve items by striking through and noting the outcome._

---

## UX Framework gaps — knowledge service obligations

Full analysis in `gap_analysis.md`. All four open gaps share the same root prerequisite.

### ~~selected_nodes in SearchResponse (prerequisite for Gate 3, Gate 4, trace, evaluation)~~

~~`POST /search` currently reads `synthesis.selected_nodes` internally in `_facts_from_result`
but does not return it to callers. Add it to `SearchResponse`.~~

_Done: `selected_nodes` returned in SearchResponse. Gateway reads it in sprint item D._

### ~~has_evidence flag (Gate 3 — simplest evidence signal)~~

~~Once `selected_nodes` is exposed, the gateway can derive evidence presence itself.~~

_Done: Gateway derives this from `selected_nodes` directly — no separate flag needed. Sprint item D._

---

### Gate 3a — Routing candidates on retrieval miss

**Required by:** `src/gateway/TODO.md §Conversation policy — Gate 3a` (sprint item K).

When Gate 3a fires (`selected_nodes == []`), the gateway needs to know which documents Stage 1
routed to and what L1 sections exist in those documents, so it can surface adjacent topics to
the parent instead of returning a canned no-evidence reply.

**Change:** Add `routing_candidates: list[dict] | None` to `SearchResponse` in `models.py`.

Populate in `query_multi_index` inside the `if not section_parts:` early-return branch
(around line 263 of `indexer/multi.py`). At that point `resolved_docs` and `docs_by_id` are
available. For each `doc_id` in `resolved_docs`:
```python
{
  "doc_name": doc_id.replace("_", " ").replace("-", " ").title(),
  "l1_sections": [n["title"] for n in docs_by_id[doc_id]["l1_nodes"]]  # cap at 10
}
```

`routing_candidates` is `None` when `selected_nodes` is non-empty (normal answer or Gate 3b).
Additive field — no breaking change to existing callers.

Pass it through `_build_response()` in `main.py` to the caller.

**Files:** `models.py` (routing_candidates on SearchResponse), `indexer/multi.py` (populate
in the no-section-parts branch), `main.py` (_build_response passes it through).

---

### Gate 3b — `has_answer` flag

**Required by:** `src/gateway/TODO.md §Conversation policy — Gate 3b` (sprint item J).

When synthesis runs but concludes the retrieved sections don't answer the question, the gateway
has no structured signal — the abstention text is returned as if it were a real answer. This
caused the confirmed UAT failure on 2026-04-27 (tree climbing / health & safety chunk).

**Change:** Add `has_answer: bool` to `SearchResponse` in `models.py`.

Set in `_build_response()` in `main.py`:
- `False` when `synthesis_nodes` (i.e. `selected_nodes`) is empty — Gate 3a path, synthesis skipped
- `False` when `result["synthesis"]["answer"].strip()` starts with the abstention prefix defined
  in `make_synthesize_prompt`: `"The provided sections do not answer this question."`
- `True` otherwise

**Coupling to maintain:** The prefix checked here MUST match the abstention instruction in
`indexer/prompts.py make_synthesize_prompt`. Define a module-level constant in `main.py`:
```python
# COUPLING: must match the abstention instruction in indexer/prompts.py make_synthesize_prompt
_SYNTHESIS_ABSTENTION_PREFIX = "The provided sections do not answer this question."
```
Add a matching comment in `prompts.py` at the relevant line so the two locations stay in sync
when the prompt is edited.

`has_answer` defaults to `True` if the field is absent — additive, no breaking change.

**Files:** `models.py` (has_answer on SearchResponse), `main.py` (_build_response +
abstention constant), `indexer/prompts.py` (cross-reference comment on abstention string).

---

## Bugs

- **`/search` (non-streaming) duplicates the pipeline** — `POST /search` and
  `POST /search/stream` run the same retrieval + synthesis pipeline in parallel
  code paths. Any prompt or logic change must be applied twice. Deprecate `/search`
  once all callers (currently: gateway non-streaming path) have migrated to
  `/search/stream`. Track remaining callers before removing.

---

## Multilingual index support (blocked on ingestion spike)

Once `src/ingestion/TODO.md` — "SPIKE: multilingual corpus" resolves to Option A
(translate at ingestion time), the knowledge service needs to:

- Accept a `language: "en" | "es"` parameter on `POST /search` and `POST /topics`.
- Route to the language-appropriate index variant (parallel `en_*` / `es_*` indexes,
  or a bilingual index with per-node language fields — TBD in the spike).
- Default to `"en"` until ES indexes exist.

Do not implement until the ingestion spike answers: which Spanish variant(s), who reviews
translations, and how often the corpus updates. See `src/ingestion/TODO.md` for full context.

---

## Tuning

### Breadth detection thresholds
The gateway uses two empirically chosen constants (in `src/gateway/config.py`):
- `MAX_TOPIC_PATHS = 5` — max distinct topic groups before overview mode triggers
- `SIBLING_COLLAPSE_THRESHOLD = 3` — min L1 sections from one doc before collapsing to doc-level

These were set to reasonable-sounding defaults without real-query data. To tune:
1. Run a representative set of parent queries through the pipeline with logging
2. Inspect `topic_count` in gateway logs for questions that should/shouldn't trigger overview
3. Adjust the constants — no code changes required, just `config.py`

---

## Hypotheses

Items carried over from poc1 evaluation cycles. Priority order at the bottom.

### Index storage
**Problem:** Index files are loaded from a path on disk (`KNOWLEDGE_INDEX_PATH`). For UAT
this is a mounted volume or local path. No lifecycle management — rebuilding the index
requires redeploying or remounting.

**Future:** A document/ingestion management layer will own index versions, track which
corpus revision produced them, and trigger rebuilds. The knowledge service should
discover the current index via a registry (Firestore or similar), not a static path.

Reuse `tools/archive/create_cache.py` Firestore schema as a starting point:
`config/knowledge_index` → `{index_path, built_at, corpus_revision, source_ids}`.

---

### group_ids access filtering
**Problem:** `group_ids` is accepted but ignored. All users see all documents.

**Future:** `group_ids` is a stub for per-user document access control and multi-tenancy.
When enforced, the routing stage in `multi.py` should restrict which doc IDs are
eligible before passing to `query_multi_index`. The gateway/access service resolves
`user_id` → permitted `group_ids`; the knowledge service enforces them.

Implementation: filter `multi_index["documents"]` to only those whose `doc_id` is in
`group_ids` before routing. No changes to `multi.py` itself — pass a filtered index.

---

### Structured citations in facts
**Problem:** `facts` in the API response are derived from the list of selected nodes
(section title + doc_id), not from structured citations in the answer. The synthesis
prompt produces plain text with inline `[doc_id:section_id]` references.
Related to UX framework Gate 3 and evaluation gaps — see `gap_analysis.md`.

**Hypothesis:** Change `make_synthesize_prompt` to output JSON with a `citations` array
(`[{document, excerpt}]`) instead of plain text. Map to `facts` directly.
Risk: structured output may constrain the three-step answer format. Evaluate on the
existing eval set before shipping.

---

### Query improvement backlog (carried from poc1)
Items relevant to the production service, in priority order:

**Priority 1 — Structured synthesis prompt** _(prompt-only, no rebuild)_
Edit `indexer/prompts.py` — `make_synthesize_prompt`.
Current three-step structure already deployed. Measure on eval before further changes.

**Priority 2 — Two-stage selection prompt** _(prompt-only, no rebuild)_
Edit `indexer/prompts.py` — `make_select_prompt` / `make_discriminate_prompt`.
"1. Identify single most critical ID. 2. Add further only if strictly absent."

**Priority 4 — Corpus context card** _(new offline job)_
New file: `indexer/context_card.py`. One LLM call over all docs → extracts factual
org claims (name, address, key dates) → stored in index root.
Inject as system message prefix in synthesis call.

**Priority 0 — Retrieval framing shift** _(prompt-only, no rebuild)_
Change select/discriminate prompt framing from label-matching to navigational reasoning:
"which section would a reader look in first to answer this question?"
Directly fixes cases like `1.5` being skipped for ambiguous queries.

Stage 0 items (query reformulation, PRF, glossary) are tracked in `src/gateway/TODO.md` Stage 0.

---

### Precision-without-latency: parallel retrieval quality improvements

Full analysis in `docs/design/parallelization_ideas.md` §5. These use Stage 2's existing
concurrency budget to run more work at the same wall-clock cost.

**Prerequisite for all four:** BigQuery trace must exist so before/after quality can be
measured. Do not implement blindly — each has a stated hypothesis and test condition.

#### 5a. Widen routing to 3-4 docs
**Hypothesis:** Widening routing reduces answer-misses on cross-cutting queries without
increasing latency (Stage 2 already runs all docs concurrently).
**Change:** `make_route_prompt` in `indexer/prompts.py` — change "Select 1–2 document IDs"
to "Select 1–4 document IDs."
**Test condition:** Measure routing miss rate from trace data. Implement if >15% of
low-rated answers had the correct doc outside the routed set.

#### 5b. Dual-pass selection per doc (direct + context framings)
**Hypothesis:** Running two concurrent selection passes per doc (direct-answer framing +
background-context framing) and unioning the results reduces incomplete answers on
procedural/conditional questions.
**Change:** In `_select_from_doc` in `indexer/multi.py`, fire `asyncio.gather` over two
`llm_call` invocations — current `make_select_prompt` plus a new
`make_context_select_prompt` (background/definitions framing). Union unique node IDs
before synthesis.
**Test condition:** Compare `selected_nodes` count and user ratings on procedural questions
(those with if/unless/except clauses) before and after.

#### 5c. Query expansion in parallel with routing
**Hypothesis:** A vocabulary-normalization rewrite fired concurrently with Stage 1 routing,
then used alongside the original query in Stage 2 selection, reduces selection misses on
informal/colloquial phrasing.
**Change:** At the start of `query_multi_index`, fire an `asyncio.gather` over
`llm_call(structural_model, make_expand_prompt(question))` and the routing call. Pass
both `question` and `expanded_question` to `_select_from_doc`; union results.
Add `make_expand_prompt` to `indexer/prompts.py`.
Related to gateway PRF reformulation (gateway `TODO.md` Stage 0) but knowledge-internal:
no gateway change required.
**Test condition:** Compare ratings on queries that use informal vocabulary vs. their
formal equivalents in the eval set.

#### 5d. Routing miss recovery (cheap parallel scan on un-routed docs)
**Hypothesis:** A structural-model pass on un-routed docs, run in parallel with Stage 2
selection on routed docs, catches the tail of routing errors with low cost overhead.
**Change:** In `query_multi_index`, after Stage 1, fire `asyncio.gather` over both the
existing Stage 2 coroutines (quality model) and a new `_scan_doc(doc_id, question)`
coroutine (structural model, lightweight prompt) for each un-routed doc. Merge any hits
into `resolved_docs` before synthesis.
**Test condition:** Track how often recovery nodes appear in synthesis. If <10% of queries
use recovery nodes, routing is already good enough; if >10%, prioritise 5a instead.

---

### Vector-based cache layer
**When:** After group_ids filtering is enforced and corpus grows beyond single-cache fit.
**What:** Replace or augment PageIndex routing with vector similarity pre-filtering.
Reuse `tools/archive/create_cache.py` for Firestore schema and IAM starting points.
The `indexer/` module is designed to be modular — the routing stage in `multi.py` is the
natural integration point.

---

## Resolved

_(none yet)_
