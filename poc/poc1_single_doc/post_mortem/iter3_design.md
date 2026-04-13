# Iteration 3 — Design

_Authored 2026-04-13. Implements decisions from iter2 post-mortem discussion._

---

## What changes from iteration 2

| Area | Iter 2 | Iter 3 |
|------|--------|--------|
| Oversize detection | line-number gap heuristic | character count on full_text_chars |
| Preamble hoisting | step 5 (after splitting) | step 2 (before splitting) |
| Summary format | budget formula → prose | topic phrase list (1–5 words, semicolons) |
| Summary length | mathematical formula | no cap — LLM determines density |
| Eval monitoring | chars→synth per query | also phrase_count/chunk_chars distribution |

---

## Indexer protocol — 9 steps

### Step 1 — Parse markdown → initial tree
- Walk the file top-to-bottom; detect headers by `#` prefix.
- Record: level, heading text (working title), character position of header line.
- Build tree from heading hierarchy. Store full_text_chars = char count of everything
  from this header to the next sibling/parent header (not including sub-headers' text
  — raw slice, sub-sections included).

### Step 2 — Hoist preamble content (before splitting)
- For every node that has content (non-header text) _before_ its first child header:
  create a synthetic child node at the start of the children list.
  - Working title = parent's heading text (verbatim, as a starting point).
  - Content = that preamble text only (not sub-sections).
- This ensures all content lives in leaf nodes before any further processing.
- These synthetic nodes will be thinned or re-titled by downstream steps — no
  special handling needed.

### Step 3 — Detect oversized leaves
- For every leaf node: if full_text_chars > MAX_NODE_CHARS → mark as oversized.
- Use character count. Do NOT use line-number gaps — line length varies too much.

### Step 4 — Split oversized leaves
For each oversized leaf:
1. Build breadcrumb: `doc_name > H1 title > … > parent title`
2. Send to LLM (gemini-2.5-flash-lite):
   - System: "You are building a structured index. Breadcrumb (context only, do not
     echo): `<breadcrumb>`. Identify semantic sub-topics in the text below. For each,
     return: TITLE: <1–8 word index title> and DESCRIPTION: <topic phrase list>."
   - User: full text of the oversized node
3. Parse response → create child nodes, each with title + description.
4. Parent's title and description are **completely discarded and regenerated** from
   the children's combined titles+descriptions (not the corpus — this is a lightweight
   roll-up, not a re-read).
5. If any newly created child is still > MAX_NODE_CHARS → it becomes a candidate for
   the next iteration of this step.

### Step 5 — Repeat until no oversized leaves remain
- Loop steps 3–4 until all leaves are ≤ MAX_NODE_CHARS.
- Guard: if a node fails to split below MAX after 3 iterations, log a warning and
  leave it as-is. Do not infinite-loop.

### Step 6 — Summarise unprocessed leaves
- Any leaf that went through step 4 already has a title + description.
- Any leaf that was never oversized still has only a working title (from the markdown
  heading) and no description.
- For each unprocessed leaf: send its full text + breadcrumb to LLM (flash-lite)
  with the topic phrase list prompt (see "Summary format" below).

### Step 7 — Thin the tree (merge small nodes)
Merge consecutive sibling leaf nodes where ALL of:
- At least one node is < MIN_NODE_CHARS (small nodes may be merged into adjacent
  normal-sized nodes — synthetic preamble nodes are a prime example of this case)
- Combined size ≤ MAX_NODE_CHARS
- Same parent (no cross-branch merges)
- LLM judges them semantically coherent (pass both titles+descriptions as input)

When merging:
- Re-read the full combined text.
- Generate a new title + description from scratch (same prompt as step 6).
- Do NOT concatenate the old descriptions — start fresh.

### Step 8 — Bottom-up intermediary rewriting
- For every non-leaf node, bottom-up (deepest first, root last):
  - Input to LLM: the title + description of each direct child (not the corpus).
  - Output: new title + description for this node.
  - Same topic phrase list prompt (see below), framed as "synthesise the index entry
    for a section whose sub-sections cover: [child titles + descriptions]."

### Step 9 — Validate
- No leaf > MAX_NODE_CHARS
- No unresolved node IDs
- All nodes have non-empty title and description
- Log: total nodes, depth distribution, phrase_count/chunk_chars per node

---

## Summary format (all summarisation steps)

**Goal:** A rich TOC / search anchor. Not a prosaic summary. The output will be shown
to a retrieval LLM that must decide "does this node contain what the user is asking
about?" It must be as vocabulary-rich and topic-dense as possible.

**Prompt wording:**
```
For each distinct concept, rule, or procedure in this section, write a 1–5 word
topic phrase. Separate phrases with semicolons. No sentences, no elaboration.
```

**For procedural / sequential content only:** append one structural framing line:
```
[sequence: <step1> → <step2> → <step3>]
```
This preserves the step relationship without prose.

**Title rewriting:**
- Working titles come from markdown headings (e.g. "Welcome to the 2026 school year").
- When a node is processed, rewrite the title to reflect its index nature
  (e.g. "School values and goals for 2026").
- Title must NOT include the breadcrumb path.

**Breadcrumb:**
- Always pass `doc_name > H1 > … > parent` as context to every LLM call.
- Explicitly instruct: "This breadcrumb is context only — do not include it in your
  output."

---

## Eval changes

### New metrics to capture per node (post-mortem output)
- `phrase_count`: number of semicolon-separated phrases in the description
- `phrase_density`: phrase_count / full_text_chars — monitor for outliers

### New metrics to capture per query (eval output)
- `node_ids_selected`: which IDs were chosen in step 1
- `chars_to_synthesis`: total chars sent to step 2
- `selected_depth`: leaf vs parent selection (flag parent selections)

Target distribution: `chars_to_synthesis` under 15K for lookup/procedure queries.
Synthesis explosion (>40K) should be flagged in the post-mortem table.

---

## What does NOT change

- MAX_NODE_CHARS = 5000, MIN_NODE_CHARS = 1500
- Models: gemini-2.5-flash-lite (structural/splitting), gemini-2.5-flash (quality
  summarisation — step 8 and complex splits)
- Two-step retrieval: step 1 (outline → node selection), step 2 (full text → synthesis)
- Sub-process parallelism for independent summarisation tasks

---

## Build and eval commands

```bash
cd poc/poc1_single_doc

# Build index for all 4 docs
for doc in en_policy5_code_of_conduct en_policy3_health_safety_reporting \
            en_policy1_child_protection en_family_manual_24_25; do
  python3 indexer/pageindex.py build \
    ../../data/pipeline/2026-03-22_001/02_ai_cleaned/${doc}.md \
    eval/index_${doc}.json
done

# Run eval
for doc in en_policy5_code_of_conduct en_policy3_health_safety_reporting \
            en_policy1_child_protection en_family_manual_24_25; do
  python3 run/run_eval.py \
    eval/index_${doc}.json \
    eval/queries_$(echo $doc | sed 's/en_//').json \
    eval/results_${doc}.json
done
```

---

## Before building

1. Replace `family_manual Q3` — the fasting query belongs in `policy3` (§4.4).
   Add a real cross-section query spanning at least two sections within the family manual.
2. Verify the replacement query has vocabulary present in the target document:
   `grep -n "<key terms>" data/pipeline/2026-03-22_001/02_ai_cleaned/en_family_manual_24_25.md`
