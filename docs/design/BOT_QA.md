# Benchmarking Plan

**Scope:** question set design for the eval harness.
Harness implementation — `golden.jsonl` format, `run_eval.py`, metrics — lives in `docs/design/SW_QA.md §3`.
This document owns the question taxonomy, composition rationale, and generation workflow.

**Eval runner target:** gateway `/chat` endpoint (SSE stream), not `/search` directly.
The system under test is gateway + knowledge together. Testing knowledge in isolation is not sufficient —
scope classification, session context, and groundedness are all gateway responsibilities.

---

## Question set

| Family | Count | Answerability tag | Primary failure mode tested | Pipeline stage |
|---|---|---|---|---|
| Direct fact lookup | 5 | `answerable` | Index miss — wrong `source_id` retrieved | K: Stage 1–2 |
| Conditional / if-then policy | 3 | `answerable` | Rule retrieved without its condition clause | K: Stage 2–3 |
| Exception omission | 2 | `answerable` | Standard answer returned; exception clause silently dropped | K: Stage 2–3 |
| Polysemic routing trap | 2 | `answerable` | Stage 1 routes to semantically closer but wrong policy branch | K: Stage 1 |
| L1 vocabulary mismatch | 2 | `answerable` | Stage 1 routes to wrong doc; query vocabulary matches wrong L1 title | K: Stage 1 |
| Parent-context loss | 1 | `answerable` | Stage 2 selects child node without parent; qualifying condition lost | K: Stage 2 |
| Procedure truncation | 1 | `answerable` | Multi-step procedure truncated at node boundary | K: Stage 2 |
| Cross-doc routing miss | 1 | `answerable` | Stage 1 routes to one doc when answer requires two | K: Stage 1 |
| Dual-version synthesis blend | 1 | `answerable` | Stage 3 blends 24/25 and 25/26 content instead of using authoritative version | K: Stage 3 |
| Version authority | 2 | `answerable` | Older family manual answer returned instead of current one | K: Stage 1 |
| Model knowledge supplement | 2 | `answerable` | Bot answers from training knowledge instead of corpus-specific value | GW: groundedness |
| Out-of-corpus | 3 | `out-of-corpus` | Gateway scope gate passes OOC query; knowledge hallucinates | GW: scope gate |
| In-scope undocumented | 2 | `in-scope-undocumented` | Topic in domain but fact absent; bot fabricates instead of abstaining | GW + K: both |
| Scope gate false positive | 1 | `answerable` | Gateway scope classifier incorrectly blocks an in-scope query | GW: scope gate |
| False presupposition | 1 | `false-presupposition` | System fabricates a rule that does not exist | GW + K: both |
| Underspecified | 1 | `underspecified` | System answers instead of requesting missing context | GW: clarification |
| Multi-turn follow-up | 2 | `answerable` | Answer ignores or contradicts session context from prior turn | GW: session |
| Regression | 1 | `answerable` | Known past failure (fire drill — see HEURISTICS.log) | K: Stage 1–3 |

Portfolio constraints:
- At least 40% of `answerable` items require `expected_source_ids` from more than one document.
- Every polysemic, L1-mismatch, version-authority, and dual-version item must have a `must_not_contain` entry for the decoy answer.
- Every negative item (`out-of-corpus`, `in-scope-undocumented`, `false-presupposition`, `underspecified`) must have a `must_not_contain` entry that catches the most likely hallucinated answer.
- Multi-turn items must include `prior_turns` in `golden.jsonl`; the runner sends the prior turn first with the same `session_id`.

---

## Question family definitions

### Direct fact lookup
Single-document, single-section answer. No reasoning chain.
Use to establish a baseline pass rate before any retrieval changes.
`expected_facts`: one specific substring (number, name, or short phrase) that only appears in the answer if the right section was retrieved.

### Conditional / if-then policy
Answer changes based on a condition stated in the same section or a nearby parent.
Do not include the condition value in the question. Ask "What is the sick leave entitlement?" not "What is the sick leave entitlement for a staff member hired before January?".
`expected_facts`: the conditional answer. `must_not_contain`: the unconditional default if one exists.

### Exception omission
The question has a standard answer AND a documented exception that materially limits who it applies to or when.
The bot returns the standard answer and sounds complete, but silently drops the exception clause.
Distinct from conditional/if-then (where the condition *changes* the answer) — here the main answer is
present but the scope restriction is missing.
`expected_facts`: the exception phrase. `must_not_contain`: a phrasing that implies universal applicability.
*Construction:* search corpus for "except", "does not apply", "excluding", "unless" adjacent to a policy statement with a clear default answer.

### Polysemic routing trap
The same keyword (e.g., "reporting", "notice", "disclosure") appears under multiple policy headings with different procedures. The question is phrased neutrally. The correct answer lives in the less obviously-named section.
`expected_source_ids`: the right document. `must_not_contain`: a phrase specific to the decoy document's answer.
*Construction:* use the Structural Trap prompt (see §Generation workflow).

### L1 vocabulary mismatch
The relevant content is buried under an L1 title whose wording does not match the query's surface vocabulary. Stage 1 routes to the wrong document entirely. The failure is a *document-level* routing miss, not a section-level one.
Example: a question about photo consent routes to Child Protection (surface match on "privacy/data") instead of the Family Manual where the parental consent procedure lives.
`expected_source_ids`: the correct document. `must_not_contain`: a phrase specific to the wrongly-routed document's answer.
*Construction:* use the L1 Vocabulary Gap prompt (see §Generation workflow).

### Parent-context loss
The answer lives in a child node, but the qualifying condition is stated only in the parent node's introductory text. Stage 2 selects the child but not the parent; synthesis returns the bare rule without its qualifier.
Do not name the subsection. Ask about the outcome.
`expected_facts`: the conditional answer including the qualifier. `must_not_contain`: the unqualified bare rule.
*Construction:* scan the two largest policy files for intro paragraphs containing "except", "unless", "only if", "provided that", or "subject to", followed by subsections that state the rule without repeating the restriction.

### Procedure truncation
A multi-step procedure spans a heading boundary in the source document. Stage 2 selects the first node (steps 1–N) but not the continuation node (steps N+1 onward). The answer looks complete but silently omits the later steps.
Ask "what are all the steps for X" on a known multi-part procedure.
`expected_facts`: a phrase from the later steps only. `must_not_contain`: any phrasing that presents an early step as the final step.
*Construction:* identify known multi-step procedures in policy files; verify the steps span multiple headings in `data/pipeline/latest/02_ai_cleaned/`.

### Cross-doc routing miss
The complete answer requires combining content from two different documents (e.g., the policy states the obligation; the family manual describes the practical parent-facing implementation). Stage 1 routes to only the more obviously-named document.
Frame the question so neither document title is named. Both `expected_source_ids` entries are required.
`must_not_contain`: a specific claim that is only correct if the second document was included.
*Construction:* identify procedures mentioned in both a policy file and the family manual; verify the two accounts differ in detail.

### Dual-version synthesis blend
Both `en_family_manual_24_25` and `es_family_manual_25_26` are indexed. Stage 1 routes to both; Stage 3 blends conflicting content rather than deferring to the authoritative (25/26) version.
Distinct from version-authority (which tests Stage 1 routing alone) — this tests Stage 3 synthesis under conflicting multi-doc input.
Frame the question without mentioning a year. The 24/25 answer must differ from 25/26 for the chosen procedure.
`must_not_contain`: the 24/25 value. `expected_source_ids`: 25/26 source only.

### Version authority
`en_family_manual_24_25.md` and `es_family_manual_25_26.md` contain overlapping procedures. The 25/26 version is authoritative.
Frame the question without mentioning a year. The correct answer is from 25/26.
`must_not_contain`: the 24/25 answer if it differs. `expected_source_ids`: the 25/26 source.
*Construction:* use the Override & Conflict prompt (see §Generation workflow).

### Model knowledge supplement
The corpus gives a school-specific answer that differs from general world knowledge (Spanish labor law, common child safety practice, general school norms). The bot must use the corpus answer. The failure is silent substitution — the bot answers with the "common sense" version that sounds more authoritative.
`expected_facts`: the corpus-specific value. `must_not_contain`: the plausible general-knowledge answer.
*Construction:* identify corpus passages where the school's policy explicitly differs from the common default (e.g., a non-standard sick leave entitlement, an atypical dismissal time, a school-specific emergency procedure).

### Out-of-corpus
Topic is completely absent from all corpus documents. Correct behaviour: gateway scope gate intercepts the query and returns the canned boundary response without calling knowledge.
`expected_facts`: a substring of the canned reply (e.g., "not covered"). `must_not_contain`: any fabricated policy claim.
Note: this tests the *gateway scope gate*, not knowledge. A failure here means the gate passed the query; knowledge then either hallucinates or 0-chunk short-circuits. Both are failures.

### In-scope undocumented
The topic is within the school's remit and related content IS in the corpus, but the *specific* answer is not documented anywhere. Correct behaviour: the system abstains with a verification boundary response rather than fabricating. Distinct from out-of-corpus — the domain matches, this specific fact just isn't there.
`expected_facts`: abstention phrase. `must_not_contain`: the most plausible model-knowledge answer (e.g., a generic regulation that would "fit").
*Construction:* identify school-domain questions where the corpus covers the general topic but leaves this specific detail unaddressed.

### Scope gate false positive
A clearly in-scope query is incorrectly classified as out-of-scope by the gateway scope classifier. Knowledge is never called. The failure is a blocked answer, not a hallucination.
`expected_facts`: a substring only present in a genuine knowledge answer (not in the canned boundary response). `must_not_contain`: the canned out-of-scope phrase.
*Construction:* use in-scope queries that use unusual or indirect phrasing that might trigger a false scope rejection.

### False presupposition
Question assumes a rule, penalty, or procedure exists when it does not. The system must not fabricate an answer.
`expected_facts`: abstention phrase. `must_not_contain`: the fabricated answer the system is most likely to invent.

### Underspecified
Question is missing a required discriminating factor (role, date, location, school level). Correct behaviour: gateway asks for clarification, not knowledge.
`expected_facts`: clarification phrase. `must_not_contain`: any specific policy answer.

### Multi-turn follow-up
A follow-up question whose correct answer depends on context established in the prior turn (e.g., the prior turn established which school level, role, or procedure is under discussion). The failure mode: the system answers the follow-up as if it were standalone — ignores session context and either asks for already-given information or gives a generic answer.
`prior_turns`: one prior user message that establishes the discriminating context. `expected_facts`: the contextually-correct answer. `must_not_contain`: the generic answer that would be correct if the prior turn were absent.
The runner sends the prior turn first with the same `session_id`, then sends `query`.

### Regression
Exact query from a known past failure documented in `.claude/HEURISTICS.log`. Pin the query string verbatim.
Re-run on every corpus or prompt change. If this item degrades, revert.

---

## Notes field convention

Add an answerability tag and a slice label to every `notes` value:

```
"notes": "[answerable][polysemic] 'reporting' appears in Child Protection and H&S; correct source is H&S §3.2"
"notes": "[answerable][l1-mismatch] photo consent query routes to Child Protection instead of Family Manual"
"notes": "[answerable][exception-omission] sick leave policy applies except during probation; bare rule omits probation clause"
"notes": "[answerable][procedure-truncation] fire drill procedure steps span two headings; Stage 2 misses second node"
"notes": "[answerable][dual-version-blend] notification deadline differs between 24/25 and 25/26 manuals"
"notes": "[answerable][model-knowledge-supplement] school dismissal time differs from Spanish default; bot must use corpus value"
"notes": "[answerable][multi-turn] prior turn established nursery level; follow-up asks about supervision ratio"
"notes": "[false-presupposition] No penalty schedule exists; system must not fabricate one"
"notes": "[out-of-corpus] GDPR / data retention — not addressed in any corpus document"
"notes": "[in-scope-undocumented] substitute teacher procedure — topic in corpus but specific escalation steps absent"
"notes": "[scope-gate-false-positive] indirect phrasing of in-scope query; gate may misclassify"
```

These tags are for human filtering only. The runner does not parse `notes`.

---

## golden.jsonl schema

Standard item:
```json
{
  "id": "fd-001",
  "query": "What must staff do immediately after a fire drill?",
  "expected_facts": ["personnel headcount", "staff check"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["evacuation route"],
  "notes": "[answerable][direct-fact] fire drill procedure — regression anchor"
}
```

Multi-turn item (adds `prior_turns`):
```json
{
  "id": "mt-001",
  "prior_turns": [
    {"role": "user", "content": "My child is in the nursery."}
  ],
  "query": "What is the supervision ratio?",
  "expected_facts": ["1:3", "nursery"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["1:8", "primary"],
  "notes": "[answerable][multi-turn] prior turn establishes nursery level; ratio differs from primary"
}
```

`prior_turns` is an optional list. Each entry has `role` (`user` or `assistant`) and `content`.
The runner sends prior turns in order with the same `session_id` before sending `query`.

---

## Generation workflow

Do not write questions from memory. Use the corpus directly.

### Step 1 — Polysemic candidates (Prompt 1)
Feed `data/index/multi_index.json` (full TOC) to a capable LLM with this prompt:

> "Analyze this Table of Contents. Identify 5–8 terms that appear under multiple section headings with operationally different meanings in each context. For each term, write one question where the phrasing semantically matches the wrong heading but the correct answer is in the less obvious section. The question must not name the correct section. Output: term | decoy heading | correct heading | question | expected answer phrase | decoy answer phrase."

Pick the 2 best candidates. Verify answers against the source `.md` files before writing the `golden.jsonl` entry.

### Step 2 — Parent-context loss candidates (Prompt 2)
Feed the full text of `en_policy3_health_safety_reporting.md` and `en_policy5_code_of_conduct.md` to a capable LLM with this prompt:

> "Find sections where the introductory paragraph of a heading contains a qualifying condition (words like 'except', 'unless', 'only if', 'provided that', 'subject to') followed by one or more subsections that state the rule without repeating the restriction. Write one question asking about the outcome that can only be correctly answered if the qualifying condition from the parent is known. The question must not name the parent section. Output: parent section | qualifying condition | child section | question | correct answer (with qualifier) | wrong answer (bare rule without qualifier)."

Pick the 1 best candidate. Verify parent/child structure exists in `data/pipeline/latest/02_ai_cleaned/`. Confirm the qualifier is only in the parent heading's text, not repeated in the child.

### Step 2b — Cross-doc routing miss candidates (Prompt 2b)
Feed the L1 outlines of all 6 documents with this prompt:

> "Identify 3–5 topics that appear in both a policy file and the family manual, where the policy states an obligation and the family manual describes the practical parent-facing implementation. For each, write one question whose complete answer requires combining both accounts. The question must not name either document. Output: topic | policy doc + section | family manual section | question | detail only in policy | detail only in family manual."

Pick the 1 best candidate. Verify both source passages exist in `data/pipeline/latest/02_ai_cleaned/`. Both must appear in `expected_source_ids`.

### Step 3 — Version authority + dual-version candidates (Prompt 3)
Feed `en_family_manual_24_25.md` and `es_family_manual_25_26.md` side by side with this prompt:

> "Compare these two versions of the family manual. Identify 3–5 procedures, rules, or dates that differ between them. For each, write one question that does not mention a year, where the 24/25 answer is plausible but wrong, and the 25/26 answer is correct. Output: section | 24/25 answer | 25/26 answer | question."

Pick the 2 best candidates for version-authority (tests Stage 1 routing). Use the 24/25 answer as `must_not_contain`.
Pick the 1 best candidate for dual-version synthesis blend (pick a case where Stage 1 would plausibly route to both documents simultaneously).

### Step 4 — L1 vocabulary mismatch candidates (Prompt 4)
Feed the L1 outlines and this prompt:

> "Identify 3–5 topics where the correct answer is in a document whose L1 title does not obviously match the query vocabulary, but another document's L1 title does match. For each, write one question whose vocabulary aligns with the wrong document's title. The answer must come from the less-obviously-named document. Output: query vocabulary | wrong L1 title (decoy) | correct L1 title | correct doc | question | expected answer phrase | decoy answer phrase."

Pick the 2 best candidates. Verify the correct source passage exists in `data/pipeline/latest/02_ai_cleaned/`.

### Step 5 — Hand-curation gate
For every LLM-generated candidate before it enters `golden.jsonl`:
1. Locate the source passage in `data/pipeline/latest/02_ai_cleaned/` and confirm the answer is present.
2. Confirm the `must_not_contain` string actually appears in the decoy source.
3. Confirm the question cannot be answered by title-scanning alone.
4. For multi-turn items: confirm the prior turn is the *only* source of the discriminating context (the follow-up question must be genuinely ambiguous without it).
5. If any check fails, discard the candidate and generate a replacement.

---

## Deferred

| Item | Why deferred |
|---|---|
| LLM-as-judge in `run_eval.py` | Current harness uses substring matching; LLM judge changes runner design |
| Gold TOC path annotation | Requires exposing internal node traversal — not instrumented |
| Baseline ladder (BM25, dense retrieval) | Needs separate retrieval harness; out of scope until v1 is stable |
| Multi-hop cross-reference questions | Requires corpus to contain explicit "see section X" pointers — verify first |
| Recall over-selection bleed | Stage 2 selects too many adjacent nodes on broad queries; synthesis blends facts from off-target sections; hard to construct a reliable `must_not_contain` without running the full pipeline first |
| Recall-oriented out-of-scope false positive | Recall bias causes Stage 2 to select tangentially-related nodes on OOC queries, bypassing 0-chunk short-circuit; partially covered by `out-of-corpus` family — separate item needed only once the distinction is empirically confirmed |
| Handoff to human agent | Gateway does not yet implement escalation path |
| Retry / state preservation across session | Gateway does not yet implement session resumption after error |
| Retrieval paraphrase robustness | Same question in different vocabulary; tests index coverage breadth; requires paired items and a separate metric |
