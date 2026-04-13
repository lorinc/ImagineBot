# POC1 — System Design Findings & Decisions

This file records every architectural decision made during POC1 design,
with rationale. A fresh session must read this before touching any POC1 code.

---

## Context

The system is a multi-tenant school chatbot. The knowledge layer receives
parent questions and must return accurate answers from 10–50 school policy
documents per tenant (15–150KB each, markdown). The full design is in
`docs/design/RAG_system_design.md`.

POC1 scope: validate the single-document PageIndex retrieval approach on one
real document (`en_policy5_code_of_conduct.md`, 107KB, 112 heading nodes).

Reference implementation studied: `temp/PageIndex/` (read-only, never copy
from it without user approval).

---

## Decision 1 — Do not trust markdown heading structure

**Decision:** Markdown `#`/`##`/`###` headings are used only as an initial
skeleton. They are NOT trusted as the final index structure.

**Rationale:** School admins write these documents. Heading discipline is poor.
A section with one `##` may contain 7,000 characters covering six unrelated
topics. The reference implementation's PDF path demonstrates the correct
approach: it uses an LLM to infer semantic structure from content, not from
markup. We apply the same principle to markdown.

**Contrast with reference markdown path:** The reference `page_index_md.py`
does trust headings. We explicitly diverge from that path.

---

## Decision 2 — Three-phase build pipeline

**Decision:** After heading parse, run two LLM-driven restructuring phases
before summarisation:

```
parse headings → split large nodes → thin small nodes → summarise
```

**Phase details:**

### Split phase
- **Threshold:** `MAX_NODE_CHARS = 1800` (direct content only, not including children)
- **Trigger:** any node with `node.char_count > MAX_NODE_CHARS`
- **Mechanism:** LLM reads the node's full content and identifies 2–6 semantic
  sub-section boundaries. It returns `[{title, start}]` where `start` is the
  first ~50 characters of each sub-section, copied verbatim from the text.
  We locate each `start` in the original text and split there. Content
  reproduction is NOT requested (avoids hallucination of large blocks).
- **Result:** synthetic child nodes created (IDs: `{parent}.s1`, `.s2`, …).
  `node.content` is set to `""` on success. Synthetic children are prepended
  before any heading-based children.
- **Recursion:** `_split_all` is depth-first; newly created children are
  immediately recursed into. A split that produces a still-oversized child
  is handled in the same pass.
- **Failure handling:** if the LLM returns < 2 sections, or start-phrase
  matching fails for any boundary, the node is left as-is (no partial split).

### Thin phase
- **Threshold:** `MIN_NODE_CHARS = 500` (full text including children)
- **Trigger:** consecutive sibling pairs where BOTH have
  `full_text_char_count < MIN_NODE_CHARS`
- **Merge conditions — ALL THREE must hold:**
  1. Both nodes are **small** (full text below threshold)
  2. Both nodes are **consecutive** siblings (adjacent in parent's child list)
  3. LLM judges them **semantically similar** (same specific topic; a reader
     looking for either would expect to find them together)
- **Mechanism:** LLM call returning `{should_merge: bool, merged_title: str}`.
  If merge: content concatenated, child lists concatenated, first node's ID
  kept.
- **Pass:** single left-to-right pass, loops until no merges occur. A merged
  node is immediately re-checked against its new right neighbour.
- **Order:** post-order (leaves first), so small leaf nodes collapse before
  their parent is evaluated.

**Why thinning diverges from reference:** The reference `tree_thinning_for_index`
merges on size alone (no semantic check). We require semantic similarity as an
additional condition because false merges corrupt the index — a "Monitoring and
Review" stub next to a "Definitions" stub should NOT merge even though both are
small.

### Summarise phase
- Recursive bottom-up: children summarised before parent.
- Parent prompt includes child summaries so parent summary reflects full
  section coverage.
- **No content truncation.** The 1800-char truncation that was in the original
  code has been removed. After the split phase, no node has direct content
  exceeding `MAX_NODE_CHARS`, so truncation is never needed.

---

## Decision 3 — Model selection per step

**Decision:** Use different models for different build and query steps.

| Step | Model | Rationale |
|------|-------|-----------|
| Split (find boundaries) | `gemini-2.0-flash` | Structural/mechanical — text comprehension, no deep reasoning needed |
| Merge check (yes/no) | `gemini-2.0-flash` | Very simple binary decision on short context |
| Summarise | `gemini-2.5-flash` | Summary IS the index entry; quality directly drives retrieval accuracy |
| Node selection (query step 1) | `gemini-2.5-flash` | Vocabulary-mismatch reasoning lives here — the critical quality gate |
| Synthesis (query step 2) | `gemini-2.5-flash` | Answer accuracy and citation discipline |

**Status: NOT YET IMPLEMENTED.** As of this session, all steps still use
the single `MODEL = "gemini-2.5-flash"` constant. This is the first thing
to implement in the next session before running the eval.

**Implementation note:** Replace the single `MODEL` constant with per-step
model IDs. Thread the correct model instance to `_split_large_node`,
`_check_merge`, `_summarise_node`, and both query steps. The `get_model()`
helper will need to accept a model name parameter, or be called separately
per step.

**Thinking mode:** Node selection could benefit from `thinking_budget` for
vocabulary-mismatch queries. Keep it OFF for the baseline eval so we have
a clean control. Enable it as a second variable after baseline results are
in hand.

---

## Decision 4 — Summary quality is measured indirectly

**Decision:** There is no direct metric for summary quality. The eval IS the
measurement.

**Rationale:** A summary is good if and only if the node-selection LLM
correctly identifies relevant nodes given that outline. We cannot score
summaries in isolation.

**Critical test — Query 7 (vocabulary mismatch probe):**
```
"Is racist language treated differently from other forms of misconduct?"
```
The relevant sections are §4 Behaviour Policy AND §5 Anti-Racism Policy.
The phrase "racist language" does not appear verbatim in §4's headings.
If node selection picks both sections, the summaries are adequate for
cross-section reasoning. If it misses §5, check what §5's summary actually
says — the summary likely lost the discriminating vocabulary.

---

## Decision 5 — Retrieval titles are generated, not extracted

**Decision:** Each node gets a `retrieval_title` generated by the LLM during
the summarise phase, in addition to its heading-derived `title`. The outline
shown to the step-1 node-selection LLM uses `retrieval_title`, not `title`.
The heading `title` is kept for human-readable output only.

**Rationale — the vocabulary dead-end problem:**
Node titles are heading text verbatim. Headings name the *topic container*,
not the *content*. "§2.5 Protocol for treating wasp stings" is opaque to a
query like "what training must staff complete for medical emergencies" — zero
shared vocabulary. The step-1 LLM never selects that node, so EpiPen training
is invisible to the answer.

LLM-generated titles describe *what the content is about*, not what the heading
says. "§2.5" becomes "Anaphylaxis treatment protocol and EpiPen administration
training required of all staff" — now it is selectable from the medical
emergencies query.

**Observed directly:** The reference implementation (pageindex.site) uses
LLM-generated titles for all nodes, even though their documents have clear
chapter headings. Titles like "Grice's Maxims and Principles of Conversational
Design" and "From Orality to Digital Conversation: The Evolution of Human
Communication" are content-derived, not heading-extracted. The retrieval benefit
is the primary reason; format-agnosticism (PDF compatibility) is secondary.

**Implementation:**
- Add a `retrieval_title: str` field to `Node`.
- During `_summarise_node`, after generating the summary, make a second LLM call
  (or include in the same prompt) asking for a `retrieval_title`: a short phrase
  (≤ 12 words) that describes what this section is specifically about, using the
  vocabulary a reader would use when searching for it — NOT the heading text.
- Outline format for step-1: `[{id}] {retrieval_title} — {summary}` instead of
  `[{id}] {title} — {summary}`.
- Index JSON stores both `title` and `retrieval_title`.

**Scope of benefit:** Directly addresses vocabulary-mismatch cross-section
failures. Has no effect on lookup or procedure queries where the heading text
already matches query vocabulary. Expected to fix policy3 Q3 and similar.

**Cost:** One additional LLM call per node during build (can be batched into
the summarise prompt to avoid the round-trip). No change to query-time cost.

---

## Current state of poc1 code

### `build/pageindex.py`
- `parse_tree`: heading-based initial split (unchanged from original)
- `_split_text_by_starts`: locates semantic boundaries by start-phrase matching
- `_split_large_node`: LLM splits one oversized node; mutates in place
- `_split_all`: recursive depth-first split pass over entire tree
- `_merge_nodes`: combines two sibling nodes
- `_check_merge`: LLM semantic similarity check for a candidate pair
- `_thin_level`: left-to-right pass over one sibling list
- `_thin_all`: post-order thinning pass over entire tree
- `_summarise_node`: bottom-up summarisation (truncation removed)
- `build_index`: orchestrates parse → split → thin → summarise; logs node
  counts after each phase

### `run/run_eval.py`
- 7 queries designed to exercise different retrieval scenarios
- Full intermediate artefacts captured (outline, selected IDs, full text sent,
  raw LLM responses)

### `post_mortem/findings.md`
- Template waiting to be filled after eval run

---

## What to do next session

1. **Implement model differentiation** (Decision 3 above — not yet coded).
   Change `get_model()` to accept a model name. Pass `gemini-2.0-flash` to
   split and merge steps; keep `gemini-2.5-flash` for summarise and query.

2. **Run the build:**
   ```bash
   cd poc/poc1_single_doc
   python3 build/pageindex.py build \
     ../../data/pipeline/2026-03-22_001/02_ai_cleaned/en_policy5_code_of_conduct.md \
     eval/index.json
   ```
   Read the `[build]` output carefully. It prints node counts after each phase
   (parse → split → thin). Verify the counts make sense:
   - After parse: 112 nodes
   - After split: should be > 112 (12 nodes get split, each into 2–6 children)
   - After thin: should be < after-split count (33 small-node candidates,
     some fraction will merge)

3. **Run the eval:**
   ```bash
   python3 run/run_eval.py eval/index.json eval/results.json
   ```

4. **Fill post_mortem/findings.md** from stdout and `eval/results.json`.
   Pay particular attention to:
   - Were the 12 oversized nodes split successfully? Check split quality by
     reading the synthetic child titles in `nodes_flat`.
   - Query 7: did node selection pick both §4 and §5?
   - Latency: is total per-query within 5s?
   - Any unresolved IDs (LLM hallucinated a node ID not in the index)?

5. **Design POC2** based on findings. The open routing-layer question
   (meta-tree vs. vector routing) is the next architectural decision.
   See `docs/design/RAG_system_design.md` §Layer 2 for context.
