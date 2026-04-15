# Retrieval Quality Analysis — Living Document

_Started 2026-04-15. Append findings; never delete sections._

---

## Q6: "What should happen after a fire drill and who is responsible?"

**Document:** `en_policy3_health_safety_reporting`
**Status:** Root-caused. Fix directions identified. Not yet implemented.

### What happened

Single-doc query (policy3 alone) fails identically to multi-doc. The multi-doc
routing correctly selected policy3 — the pipeline is innocent. The failure lives
entirely in node selection and document content.

Selected nodes: `1.1` (Safety/Risk Assessment Scope) and `1.10` (Biennial Policy
Review). Neither contains post-drill procedure steps. Synthesis correctly responded
"the provided sections do not answer this question."

### Root causes (multi-faceted)

#### 1. Document content gap — primary

The policy has no dedicated "post-fire-drill procedure" section. What exists:

| Node | Title | Relevance to query |
|------|-------|--------------------|
| 1.1 | Safety, Risk Assessment, Emergency Procedures Scope | Mentions drills happen termly; plan "validated and practised with whole Imagine Team" — rationale, not procedure |
| 1.5 | Staff absences evacuation duties | "Personnel check", "Supply staff sweep" — closest to post-drill steps but framed as mid-evacuation duties |
| 1.6 | Visitor Contractor Safety Procedures | Staff escorts visitors to assembly point — during evacuation |

Roll call sign-off, post-drill debrief, findings documentation — genuinely absent
from the source. The synthesis LLM's "does not answer" is factually correct. The
failure is that the system never showed it nodes 1.1 and 1.5 together.

#### 2. Selection model makes two false semantic matches

The query decomposes into two sub-questions. The model resolves each independently
and makes a category error on both:

- "what should happen after a drill" → `1.1` (topic: "Emergency plan practice")
  — plausible label, but 1.1 is about preparing/validating the plan, not what
  to do once a drill completes.
- "who is responsible" → `1.10` (topic: "Leadership Team Responsibility")
  — this is biennial *policy review* responsibility, not drill operational
  responsibility. The word "responsible" matched but the referent is wrong.

Node `1.5` (Personnel check, Supply staff sweep) — the procedurally closest node —
was never selected. Its title "Staff absences evacuation duties" signals absence
coverage, not post-drill checklist, so the model dismissed it before reading content.

#### 3. Topic vocabulary loses temporal semantics

"After" is the hardest word in this query. No node uses temporally-specific
language: "post-drill", "following evacuation", "drill debrief", "all-clear".
Topics use atemporal labels: "Termly emergency drills", "Emergency plan practice",
"Personnel check". The selection LLM cannot ground "what happens *after*" against
atemporal phrases — it matches nominal subject matter ("drills") and lands on
scope/policy nodes.

#### 4. 83-node outline overloads single-call selection

The index covers a 6-policy school handbook (fire, health, weather, food, data,
whistleblowing). The selection LLM receives 83 nodes × 34670 chars in one call
and must pick 2–3 nodes. It must simultaneously do:

- Coarse-grained filtering: which of the 6 policy sections is relevant?
- Fine-grained discrimination: within the relevant section's 10 children, which
  2 are best?

Under this cognitive load the model makes plausible-sounding but wrong intra-section
choices. The topic vocabulary doesn't give enough signal to discriminate between
"scope of drill program" and "procedure during/after drill."

#### 5. Node 1.9 merge — red herring

Build log: `Check [1.8] (83c) + [1.9] (137c) → MERGE`.
Post-merge topics: fire alarm testing; certified agent; annual testing; competent
engineer — purely equipment testing. Whatever 1.9 originally said, it wasn't
post-drill procedure content. The merge did not suppress relevant information.

### Fix directions (prioritised)

**Fix 1 — Hierarchical node selection (addresses root causes 3 and 4)**

Replace the current single flat-outline selection call with a two-stage tree walk:
1. Show only level-1 nodes (6 items) → select relevant sections.
2. For each selected section, show that section's children only → select leaves.

This mirrors how a human scans a document and keeps each LLM call to O(10) items
instead of O(83). Temporal/procedural discrimination is easier when the model only
sees 10 siblings rather than 83 unrelated nodes.

This is the multi-doc routing idea applied one level deeper — the same two-stage
pattern we already validated at the document level (POC2).

**Fix 2 — Temporally-explicit topic extraction (addresses root cause 3)**

Topic extraction prompt should ask the model to distinguish action phase:
- "exists / is established" vs "is executed during" vs "is executed after"
- Add phase labels to procedural topics: "post-drill: personnel headcount",
  "during-evacuation: assembly point escort"

This is a prompt change to `make_topics_prompt` / `make_intermediate_topics_prompt`.

**Fix 3 — Wider initial recall with content-preview re-rank (addresses root cause 2)**

Instead of picking final 2–3 nodes in one shot, pick top 5–6 candidates first,
then show each candidate's content preview (first 200 chars) and eliminate.
Prevents false semantic matches: "Leadership Team Responsibility" in 1.10 would
be eliminated immediately once the model sees the content says "biennial review."

**Fix 4 — Document gap surfacing**

When no selected node's content is temporally relevant to the query, the synthesis
step should say so explicitly and name the closest available nodes. Currently it
says "does not answer" with no guidance. This is a synthesis prompt change.

_Open questions moved to `poc/poc1_single_doc/TODO.md`._

---

## Node count and LLM reasoning capacity

### The core problem

Every selection call is bounded by the LLM's working memory over the outline.
Current state: 83 nodes, 34670 chars. The model is asked to read ~35K chars of
topic-dense outline and select 2–3 nodes in one pass.

Two failure modes at scale:

**A. Breadth overload** — too many *sibling* nodes at one level. The model reads
the first 20 and loses track of the rest. Late nodes get under-weighted.

**B. Depth conflation** — parent and child topics overlap heavily. The model can't
tell if the answer is in the parent's own content or in a child. It either picks
the parent (misses specifics) or guesses the wrong child.

### Structural answer: match selection granularity to tree structure

The index already has a tree. Use it. Selection should walk the tree top-down,
one level at a time:

```
Level 0 (root) → select relevant top-level sections  [O(n_docs) or O(n_sections)]
Level 1         → select relevant children within     [O(10–15)]
Level 2+        → select leaves within                [O(5–10)]
```

Each call sees only its local sibling list. The cost is O(depth) calls but each
call is fast, cheap, and accurate. This is exactly what we do at the document
level in POC2 routing — apply it recursively within a document.

### What "managing node count" means in practice

| Approach | Pro | Con |
|----------|-----|-----|
| Hard cap (e.g. MAX_OUTLINE_NODES=30) — truncate outline | Simple | Arbitrary; may cut relevant content |
| Hierarchical selection (walk tree top-down) | Principled; matches data structure | More LLM calls (O(depth)) |
| Semantic clustering — group nodes before showing | Can compress 83→20 | Clustering adds latency and its own errors |
| Two-pass: coarse recall → content-preview rerank | Catches false topic matches | Two calls per query |

Recommendation: **hierarchical selection** is the principled fix. It solves the
breadth problem by construction, aligns with the tree structure we already have,
and the POC2 routing layer proves the pattern works. The extra calls are cheap
(structural model, short prompts).

A hard cap is a useful safety net on top but not a substitute.

### Empirical question to resolve

At what outline size does selection quality degrade? Hypothesised threshold: 20–25
nodes per call. Run a controlled eval: same queries, same index, vary the outline
shown (top-5 children only vs full 10-child section vs full 83-node flat).
This would give us a concrete number to design around.

---

## Failure Mode Taxonomy

Derived from deep document analysis of all 6 en_* policy docs. Each category has
dedicated hard tests in `eval/queries_policy3_hard.json`, `eval/queries_policy1_hard.json`,
`eval/queries_multi_hard.json`.

### 1. Vocabulary alias
Query term ≠ document term, but concepts are identical.
- "supply teachers" vs "supply staff" (§1.5)
- "training" vs "brief summary of emergency procedures" (§1.6 contractors)
- "allergic reaction after eating" vs "wasp sting anaphylaxis" (§2.5)

Detectability: hard — topic phrases must preserve both the document's vocabulary
AND common synonym forms. Current topics use document-native language only.

### 2. Responsibility referent error
"Who is responsible for X?" matches a *Responsibility* node but for the wrong X.
- Policy review responsibility (§1.10, §2.6, §2.9 in policy1) ≠ operational responsibility
- Emergency Plan Head (§3.7) ≠ Leadership Team biennial reviewer

Fix direction: when a query asks about responsibility, rank candidates by whether
the node's *content* names the queried activity, not just the word "responsible."

### 3. Semantic label mismatch
Section title signals wrong topic, hiding correct content.
- §1.5 "Staff absences" contains the *only* supply-staff evacuation instruction
- §2.5 "Wasp Sting Protocol" contains the full *anaphylaxis* protocol (any cause)
- §1.10 "Complaints Procedure" explicitly covers staff-belittling-pupils

Fix direction: Fix 2 (temporally-explicit topic extraction) also helps here —
ask the topic LLM to identify what *question types* the section answers, not just
its subject matter.

### 4. Conditional negation
Document says "normally X" then "however, not if Y." Retrieval may succeed but
synthesis ignores the exception clause.
- §1.13: "normally seek to discuss with parents" BUT exception for high-risk cases

This is a **synthesis** failure, not a retrieval failure. The synthesis prompt
should be strengthened: "If the section contains an exception or condition, you
MUST include it in the answer."

### 5. Cross-reference chain
Document A contains "see Document B" — single-doc query returns the redirect,
not the content. Multi-doc router must detect and include Document B.
- §2.3.s5 "Violence to staff — see Code of Conduct" → policy5 needed
- §1.7 "Attendance — see Code of Conduct" → answer for missing-child threshold
  is in §1.8, NOT policy5's attendance section

Detectability: the synthesis step will output a "see other policy" non-answer.
A post-synthesis check for "see separate policy" / "see section" phrases could
trigger a follow-up retrieval pass.

### 6. Threshold precision
Query contains a number. Document has the authoritative threshold. System must
retrieve the exact section, not an adjacent one that mentions similar concepts.
- 10 consecutive days → §1.8 (social services trigger)
- §1.7 (attendance monitoring) is adjacent but contains no threshold

### 7. Adversarial routing bait
A surface keyword in the query strongly activates the wrong document.
- "visitor" → policy3 visitor safety; correct doc: policy1 (staff abuse)
- "absence" → policy5 attendance; correct: policy1 §1.8 (missing education)
- "confidential" → policy1 §2 (Confidentiality Policy); correct: §1.13 (no-secrets rule)

These are the hardest to fix at the routing layer alone — requires content-preview
reranking (Fix 3) or hierarchical selection to resolve.

### 8. Document gap (honest null)
Answer is genuinely absent from the corpus. The system should say so explicitly.
- Post-drill re-entry checks (Q6 / P3H6)
- Parent photography at school events (MH5)
- Evacuation procedure for physically disabled students

Current synthesis prompt handles this ("The provided sections do not answer") but
only when the retrieved sections clearly don't match. When retrieved sections are
*partially* relevant, synthesis may confabulate.

### Test inventory

| File | Queries | Primary failure modes |
|------|---------|----------------------|
| `queries_policy3_hard.json` | P3H1–P3H6 | vocabulary alias, responsibility referent, doc gap |
| `queries_policy1_hard.json` | P1H1–P1H6 | conditional negation, adversarial redirect, threshold |
| `queries_multi_hard.json` | MH1–MH6 | cross-reference chain, routing bait, doc gap |

Run commands:
```bash
cd poc/poc1_single_doc
# Policy3 hard
python3 run/run_eval.py eval/index_en_policy3_health_safety_reporting.json \
  eval/queries_policy3_hard.json eval/results_en_policy3_hard_baseline.json

# Policy1 hard
python3 run/run_eval.py eval/index_en_policy1_child_protection.json \
  eval/queries_policy1_hard.json eval/results_en_policy1_hard_baseline.json

# Multi hard
python3 run/run_multi_eval.py eval/multi_index.json \
  eval/queries_multi_hard.json eval/results_multi_hard_baseline.json
```

---

## Baseline Hard Eval Results (2026-04-15, pre-hierarchical-selection)

Results saved in `eval/results_en_policy3_hard_baseline.json`,
`eval/results_en_policy1_hard_baseline.json`, `eval/results_multi_hard_baseline.json`.

### Overall: 16/17 retrieval targets hit

| Suite | Score | Notes |
|-------|-------|-------|
| Policy3 Hard | 5/5 (P3H6 skipped) | P3H6 doc gap handled correctly: synthesis said "does not answer" |
| Policy1 Hard | 6/6 | P1H5 over-selects (11 nodes, 22K chars) — signal noise, not failure |
| Multi Hard | 5/6 | MH1 fails — see below |
| **Total** | **16/17** | |

### Policy3 Hard — detail

| ID | Expected | Selected | Result |
|----|----------|----------|--------|
| P3H1 vocab_alias | `[1.5]` | `[1.5]` | PASS |
| P3H2 responsibility_referent | `[3.3, 3.7]` | `[3.3, 3.4, 3.7]` | PASS |
| P3H3 vocab_alias | `[2.5, 2.4]` | `[2.4, 2.5]` | PASS |
| P3H4 cross_section_compound | `[1.1, 1.8]` | `[1.1, 1.8]` | PASS |
| P3H5 vocab_alias | `[1.6]` | `[1.6]` | PASS |
| P3H6 document_gap | `[]` | `[1.3]` | SKIP — synthesis correct |

### Policy1 Hard — detail

| ID | Expected | Selected | Result | Notes |
|----|----------|----------|--------|-------|
| P1H1 conditional_negation | `[1.13]` | `[1.13]` | PASS | |
| P1H2 enumeration_threshold | `[1.8]` | `[1.7, 1.8]` | PASS | Extra 1.7 (wrong but harmless) |
| P1H3 adversarial_redirect | `[1.13]` | `[1.13, 2.1, 2.3]` | PASS | §2 noise added alongside correct node |
| P1H4 adversarial_redirect | `[1.10]` | `[1.10, 1.11.L6, 1.16]` | PASS | 1.11.L6 noise |
| P1H5 cross_section_compound | `[1.11.L21, 1.13, 1.11.L3]` | 11 nodes, 22K chars | PASS | Over-selection — all expected present but 8 extra nodes sent to synthesis |
| P1H6 cross_section_compound | `[1.11.L21, 1.13]` | `[1.11.L21, 1.13]` | PASS | Exact |

**P1H5 noise note:** 11 nodes selected vs 3 expected. No parent expansion triggered —
the flat outline returned too broad a sweep. Hierarchical selection (Fix 1) should
contain this: a two-stage walk would stop at the relevant leaves instead of selecting
all 11 siblings in §1.

### Multi Hard — detail

| ID | Expected docs | Selected docs | Result |
|----|--------------|---------------|--------|
| MH1 adversarial_redirect | `[policy5, policy3]` | `[policy5, policy1]` | **FAIL** |
| MH2 adversarial_redirect | `[policy1]` | `[policy1, policy5]` | PASS |
| MH3 cross_section_compound | `[policy1]` | `[policy1, policy3]` | PASS |
| MH4 cross_section_compound | `[policy3, policy4]` | `[policy4, policy3]` | PASS |
| MH5 document_gap | `[policy2]` | `[policy2, family_manual]` | PASS |
| MH6 temporal_semantics | `[policy4]` | `[policy4, policy3]` | PASS |

### MH1 failure — root cause

**Query:** "What happens if a student physically attacks a teacher?"

**Expected routing:** policy5 (Code of Conduct — behaviour procedure) + policy3
(§2.3.s5 "Violence to staff — see Code of Conduct" cross-reference).

**Actual routing:** policy5 + policy1 (Child Protection).

**Routing reasoning:** "The Code of Conduct policy likely outlines expected student
behavior and consequences for violations, while the Child Protection policy would
address serious incidents involving harm to staff."

**Root cause:** The router correctly identifies policy5 as the primary source but
then conflates "harm to staff" with child protection rather than health & safety.
Physical attack on a teacher is an H&S incident (policy3) before it is a
safeguarding case. The router's summary of policy3 likely does not surface
"violence to staff" prominently enough to beat policy1's safeguarding framing.

**Fix direction:** Policy3's routing summary should mention its cross-reference to
Code of Conduct for staff-violence cases. Alternatively, Fix 3 (content-preview
rerank) would expose the §2.3.s5 redirect text and let the model see the connection.
This is a routing-layer issue, not a node-selection issue.

### Signal noise observations

Several passing queries selected extra wrong-but-harmless nodes. These inflate
synthesis context without causing incorrect answers, but they indicate the selection
model is not discriminating precisely enough. All excess selections involve:
- Adjacent sibling nodes (policy1 §1.3, §1.4, §1.7 alongside correct §1.8 or §1.13)
- Section-level nodes when leaf nodes were sufficient (policy1 §2.1, §2.3 alongside
  §1.13 for P1H3)

Hierarchical selection (Fix 1) is expected to reduce both types: the two-stage walk
naturally prunes at the section boundary before exposing siblings.
