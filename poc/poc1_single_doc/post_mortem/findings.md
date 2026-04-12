# POC1 Post-Mortem: Single-document PageIndex

## Run metadata
- Source: en_policy5_code_of_conduct.md
- Index built: [fill from results.json: index_built_at]
- Build time: [fill: index_build_time_s]s
- Eval run: [fill: eval_run_at]
- Total eval time: [fill: total_eval_time_s]s

---

## Node density (fill from results.json: nodes_flat)

| Metric | Value |
|--------|-------|
| Total nodes | [node_count] |
| Level 1 (#) nodes | [level_counts.1] |
| Level 2 (##) nodes | [level_counts.2] |
| Level 3 (###) nodes | [level_counts.3] |
| Min direct content (chars) | [min of char_count] |
| Max direct content (chars) | [max of char_count] |
| Avg direct content (chars) | [avg of char_count] |
| Nodes with < 100 chars (stubs) | [count] |
| Avg full_text_chars (with children) | [avg of full_text_char_count] |

**Verdict:** [too granular / reasonable / too coarse]

**Implication for POC2:** [e.g. "node density is fine; per-doc outline fits in ~3K tokens"]

---

## Build cost

| Metric | Value |
|--------|-------|
| Build time (wall clock) | [build_time_s]s |
| Estimated LLM calls | [node_count] |
| Estimated total tokens | [rough estimate] |
| Estimated cost | ~$[X] |

**One-time or per-corpus-update.** Acceptable for [freq]?

---

## Query results (fill from stdout + results.json)

### Query 1: Attendance percentage for secondary students
- Selected IDs: [fill]
- Correct sections? [yes/no — which section was expected?]
- Answer quality: [correct / partial / wrong]
- Latency: [fill]ms
- Notes:

### Query 2: Bullying reporting process (step-by-step)
- Selected IDs: [fill]
- Correct sections? [yes/no]
- Answer quality: [correct / partial / wrong — did it get the steps right?]
- Latency: [fill]ms
- Notes:

### Query 3: Physical restraint of students
- Selected IDs: [fill]
- Correct sections? [yes/no]
- Answer quality:
- Latency: [fill]ms
- Notes:

### Query 4: Weapons classification
- Selected IDs: [fill]
- Correct sections? [yes/no]
- Answer quality:
- Latency: [fill]ms
- Notes:

### Query 5: PE day dress code
- Selected IDs: [fill]
- Correct sections? [yes/no]
- Answer quality:
- Latency: [fill]ms
- Notes:

### Query 6: Drug incident procedure
- Selected IDs: [fill]
- Correct sections? [yes/no]
- Answer quality:
- Latency: [fill]ms
- Notes:

### Query 7: Racist language vs. general misconduct (cross-section)
- Selected IDs: [fill]
- Correct sections? [yes/no — should select from §4 AND §5]
- Answer quality:
- Latency: [fill]ms
- Notes: This is the vocabulary mismatch probe — 'racist language' doesn't appear
  verbatim in §4 Behaviour Policy. Did the node selection LLM bridge the gap?

---

## Open questions answered (from docs/design/RAG -- System Design.md)

### 1. Node density on real documents
Verdict: [fill]
Implications: [fill]

### 2. Does the two-step LLM correctly select sections for vocab-mismatched queries?
Verdict: [fill — based on query 7]
Implications: [fill]

### 3. Is latency within the 5s soft limit?
Step 1 avg: [fill]ms  |  Step 2 avg: [fill]ms  |  Total avg: [fill]ms
Verdict: [within limit / marginal / exceeds]

### 4. What fraction of real parent queries require multi-section answers?
Estimate from eval: [fill — how many queries needed > 1 section?]

---

## Failure modes observed

[List any: wrong section selected, unresolved IDs, hallucinated answers, missing citations]

---

## What to carry into POC2

[What worked well]
[What needs to change]
[Routing layer recommendation: meta-tree vs vector, based on these results]
