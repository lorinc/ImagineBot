# TODO — src/knowledge open work

_Append-only. Resolve items by striking through and noting the outcome._

---

## Bugs

_No known bugs at UAT entry (2026-04-22)._

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

**Hypothesis:** Change `make_synthesize_prompt` to output JSON with a `citations` array
(`[{document, excerpt}]`) instead of plain text. Map to `facts` directly.
Risk: structured output may constrain the three-step answer format. Evaluate on the
existing eval set before shipping.

---

### Query improvement backlog (carried from poc1/TODO.md)
The full poc1 improvement backlog lives at `poc/poc1_single_doc/TODO.md`. Items
relevant to the production service, in priority order:

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

See `poc/poc1_single_doc/TODO.md` for Stage 0 items (query reformulation, PRF, glossary).

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
