# POC1 Post-Mortem: Single-document PageIndex

## Run metadata
- Source: en_policy5_code_of_conduct.md
- Index built: 2026-04-12T19:09:54Z
- Build time: 88.2s
- Eval run: 2026-04-12T19:11:40Z
- Total eval time: 100.4s

---

## Node density

| Metric | Value |
|--------|-------|
| Total nodes | 176 |
| Level 1 (#) nodes | 9 |
| Level 2 (##) nodes | 79 |
| Level 3 (###) nodes | 71 |
| Level 4 (synthetic split) nodes | 17 |
| Min direct content (chars) | 0 |
| Max direct content (chars) | 1769 |
| Avg direct content (chars) | 579 |
| Nodes with < 100 chars (stubs) | 29 |
| Avg full_text_chars (with children) | 1581 |

**Verdict:** too granular for single-pass full-outline selection.
176 nodes × ~370 chars/summary = 65K char outline sent to step 1 on every query.

**Implication for POC2:** The outline is too large for flat selection to be fast or cost-efficient.
A routing layer (hierarchical or vector) must reduce the candidate set before full-outline selection.

---

## Build cost

| Metric | Value |
|--------|-------|
| Build time (wall clock) | 88.2s |
| LLM calls (approx) | ~284 (176 summarise + ~75 split + ~33 merge checks) |
| Models used | gemini-2.5-flash-lite (split/merge) · gemini-2.5-flash (summarise) |

Build is one-time per document version. 88s is acceptable for offline ingestion.

---

## Query results

### Query 1: Attendance percentage for secondary students
- Selected IDs: `3`, `3.4`, `3.4.s6`
- Correct sections? Yes
- Answer quality: correct — "at least 95% for Secondary students [3.4.s6]"
- Latency: 5260ms
- Notes: Clean retrieval. Synthetic split node `3.4.s6` held the exact fact.

### Query 2: Bullying reporting process (step-by-step)
- Selected IDs: 17 nodes (`6.10.*`, `6.11.*`, `6.12`)
- Correct sections? Yes — bullying procedure spans §6.10–6.12
- Answer quality: correct — step-by-step procedure reproduced accurately
- Latency: 16111ms
- Notes: High selection count is appropriate here; bullying procedure is spread across
  many subsections. But 17 nodes → 11s synthesis step. The granularity created more nodes
  than needed for this answer.

### Query 3: Physical restraint of students
- Selected IDs: `4.9.s2`, `4.16`, `4.17`
- Correct sections? Yes
- Answer quality: correct — conditions and legal basis covered
- Latency: 17716ms (step1=13219ms — slow despite only 3 nodes selected)
- Notes: Step 1 latency dominated by the 65K outline. Selection itself was precise.

### Query 4: Weapons classification
- Selected IDs: `8.2`, `8.4`, `8.4.s2`
- Correct sections? Yes
- Answer quality: correct — specific weapon types listed with citations
- Latency: 8972ms
- Notes: Good. Synthetic split node `8.4.s2` captured the detailed weapon list.

### Query 5: PE day dress code
- Selected IDs: `2.4`, `2.4.s3`
- Correct sections? Yes
- Answer quality: correct — religious headwear and hair rules cited
- Latency: 5354ms
- Notes: Clean and fast. Only 2 nodes needed.

### Query 6: Drug incident procedure
- Selected IDs: 12 nodes (`7.1`, `7.2`, `7.4`, `7.5`, `7.8`, `7.9`, `7.11`, `7.12`, `7.14`, `7.15`, `4.9`, `4.9.s4`)
- Correct sections? Yes (§7 is the drugs policy; §4.9 covers general consequences)
- Answer quality: correct — full procedure including medical, investigation, and escalation steps
- Latency: 21033ms
- Notes: High selection count driven by the drugs section being split into many subsections.
  Similar pattern to Q2: granular split → more nodes selected → slower synthesis.

### Query 7: Racist language vs. general misconduct (cross-section) — CRITICAL
- Selected IDs: `4.9`, `4.9.s4`, `4.18`, `5.5.s5`, `5.7`, `6.11`
- Correct sections? **PASS** — both §4 Behaviour Policy AND §5 Anti-Racism selected
- Answer quality: correct — explicitly distinguishes racist language from minor verbal misconduct,
  cites escalating consequences up to permanent exclusion for continued racist behaviour
- Latency: 25964ms
- Notes: The vocabulary mismatch was bridged. "Racist language" doesn't appear verbatim in §4
  headings, but the summaries were rich enough for step 1 to connect the query to both
  sections. This validates summary quality for cross-section reasoning.

---

## Open questions answered

### 1. Node density on real documents
Verdict: 176 nodes for a 107KB document is too granular for flat outline selection.
Implications: The outline hitting 65K chars is a hard wall. Multi-document tenants
(10–50 docs) would produce 1760–8800 node outlines — completely infeasible as a flat pass.
A routing layer is not optional for the production system.

### 2. Does the two-step LLM correctly select sections for vocab-mismatched queries?
Verdict: **Yes.** Q7 passed — both §4 and §5 selected despite the query phrase not
appearing verbatim in §4 headings.
Implications: Summary quality is sufficient. The bottleneck is scale, not accuracy.
The PageIndex retrieval mechanism works; the problem is the outline size.

### 3. Is latency within the 5s soft limit?
Step 1 avg: 7461ms  |  Step 2 avg: 6883ms  |  Total avg: 14344ms
Verdict: **Exceeds limit.** Only Q1 (5260ms) and Q5 (5354ms) are close to the target.
Q7 hit 25964ms. Root cause: step 1 sends 65K chars on every query.

### 4. What fraction of real parent queries require multi-section answers?
Estimate from eval: 4 of 7 queries (Q2, Q3, Q6, Q7) required 3+ sections.
Multi-section retrieval is the common case, not the edge case.

---

## Failure modes observed

- None: no unresolved IDs, no hallucinated node references in any of the 7 queries.
- Over-selection on procedural queries (Q2: 17 nodes, Q6: 12 nodes): the LLM includes
  adjacent subsections as a safety measure. Answers remain correct but synthesis latency
  is proportional to selection count.
- 29 stub nodes (< 100 chars direct content): the thin phase didn't merge these, likely
  because they aren't consecutive with another small node or failed the semantic similarity
  check. These contribute to outline bloat.


