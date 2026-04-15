# TODO — poc1 open questions and next steps

_Append-only. Resolve items by striking through and noting the outcome._

Priority order for next implementation cycle at the bottom.

---

## Stage 0 — Query understanding

The LLM currently receives the raw user query with no pre-processing. There is no intent
detection, no reformulation, no clarifying-question mechanism, and no multi-hop capacity.

- **Corpus-grounded glossary** — One offline LLM job over the index that produces a
  term→label mapping (e.g. "fire drill" → "evacuation procedure; personnel check").
  Inject the mapping into the reformulation prompt at query time. Zero runtime overhead
  beyond prompt tokens. Directly fixes the vocabulary gap without blind world-model
  expansion. Requires re-running when the index changes, not when queries change.

- **Retrieval framing shift** — Change the select/discriminate prompt framing from
  implicit label-matching ("does this topic sound related?") to explicit navigational
  reasoning ("which section would a reader look in first to answer this question?").
  Same outline, same prompts, different instruction wording. No rebuild, no extra call.
  May close cases like `1.5` being skipped for "after a fire drill" without any index change.

- **Query completeness check** — Before retrieval, a single LLM prompt asks: "Is this
  query complete enough to answer, or is a required parameter missing?" If below threshold,
  ask a clarifying question rather than silently retrieving on an underspecified query.
  No separate classifier model needed — a prompt-based judge is sufficient at this corpus
  scale.

- **Pseudo-Relevance Feedback (PRF) reformulation** — When the glossary doesn't cover a
  term, do a preliminary aggressive keyword pass against the outline and feed the raw hits
  to the LLM: "Given this query and these available index labels, rewrite the query to
  strictly use the terminology found in the index." Keeps expansion grounded in actual
  corpus vocabulary rather than world-model assumptions.

- **Multi-hop detection** — When synthesis returns "see other policy / see separate
  section", there is no follow-up retrieval pass. A post-synthesis check for these phrases
  could trigger a second retrieval round. (See also Stage 4 cross-reference item.)

---

## Stage 1 — Routing (multi-doc)

- **MH1 routing failure** — "Student physically attacks teacher" routes to policy1 (Child
  Protection) instead of policy3 (H&S, §2.3.s5 contains "Violence to staff — see Code of
  Conduct"). Fix direction: enrich policy3's routing summary to surface the staff-violence
  cross-reference.

---

## Stage 2 — Retrieval / navigation (single-doc)

- **Two-stage selection prompting** — Change the discriminate prompt to: "1. Identify the
  single most critical subsection ID. 2. Only add further IDs if they contain information
  strictly absent from the primary section — penalise redundancy." Forces the model to
  anchor on the best hit before adding neighbours. No index rebuild, no extra call.
  Directly targets P1H5/P1H6 over-selection.

- **P1H6 precision regression** (post-Fix 1) — Baseline was exact (2 nodes: `1.11.L21`,
  `1.13`). Post-Fix 1: 7 nodes selected. Root cause: `1.11.L*` siblings have near-identical
  topic content; the discrimination call over-selects rather than narrows. Two-stage
  selection prompt (above) or content-preview rerank (Stage 3) would help.

- **P1H5 residual noise** — Improved from 11 → 7 nodes (expected: 3). Remaining noise is
  within `1.11.L*`. Same root cause as P1H6.

- **Q6 vocabulary miss** — `1.5` ("Staff absences evacuation duties" / topics: "Personnel
  check") is never selected for "what should happen after a fire drill". Root cause:
  topic labels are atemporal; temporal query finds no match. Corpus-grounded glossary and
  retrieval framing shift (Stage 0) directly target this.

- **Dense-sibling threshold** — At what sibling count does discrimination quality degrade?
  Hypothesis: >20 nodes per call. Run controlled eval: same queries, vary the outline shown
  (5 children vs 10 vs full section). Would validate or adjust `_COMBINE_THRESHOLD = 20`.

---

## Stage 3 — Content-preview rerank

Before committing to final leaf selection, fetch the first ~200 chars of each candidate
and pass them to a second LLM discrimination call. Lets the model see actual content
rather than topic phrases — eliminates false semantic matches like "Leadership Team
Responsibility" matching "who is responsible?". No GPU or external API needed; same LLM
already in use. No index rebuild. Adds one LLM call per query.

- **Overlap with Stage 0/2 fixes** — Measure after Stage 0 and two-stage selection are
  in place: how many queries still have false semantic matches that content preview would
  catch? Only implement if the cheaper fixes leave meaningful gaps.

---

## Stage 4 — Synthesis

- **Structured condition extraction** — Replace the current open-ended synthesis prompt
  with a three-step structure: (1) Core Rule — state the primary directive. (2) Exceptions
  and Conditions — explicitly list any "if", "unless", "except", "provided that" clauses
  found in the text. (3) Final Answer — combine steps 1 and 2. Prompt change only,
  no infrastructure cost. Directly fixes failure mode #4 (conditional clause drop).

- **Cross-reference chain (failure mode #5)** — When synthesis returns "see other policy /
  see separate section", no follow-up retrieval occurs. Implement a ReAct-style loop:
  the LLM emits a structured fetch action instead of a final answer when it detects a
  cross-reference; the orchestrator fetches and re-prompts. Hardcode `max_iterations = 3`
  to bound recursion. Real engineering work — defer until synthesis quality is otherwise
  stable.

---

## Evaluation

The existing harness (query → expected section IDs → precision/recall) already separates
retrieval quality from synthesis quality. Extend it rather than adopting a heavy framework.

- **Faithfulness check** — After each synthesis, run a second LLM prompt: "Does this
  answer contradict or omit any condition present in the retrieved sections?" Flag as a
  silent failure if yes. Catches the "but not if high-risk" drop without requiring RAGAS
  or a separate NLI model.

- **Ablation testing** — Remove the top-ranked retrieved section and check whether the
  answer degrades. If the answer is unchanged, the section was noise. Useful for validating
  that reranking changes are having real effect.

---

## Open empirical questions

- **Q6 / P3H6 doc gap** — Is the absence of post-drill procedure intentional (school's
  policy genuinely has no post-drill checklist), or is the content present in a different
  document in the corpus? Unverified.

- **Rebuild cost** — Any change to topic extraction prompts invalidates all existing indexes.
  Measure per-document rebuild cost before committing to any prompt change that requires
  a rebuild.

---

## Priority order — next implementation cycle

Ordered by impact/cost ratio. Each is a prompt change or a single offline job unless noted.

1. **Structured synthesis prompt** (Stage 4) — prompt change, fixes a known bug immediately
2. **Two-stage selection prompt** (Stage 2) — prompt change, targets P1H5/P1H6
3. **Retrieval framing shift** (Stage 0) — prompt wording change, no cost
4. **Corpus-grounded glossary** (Stage 0) — one offline job, fixes vocabulary gap safely
5. **Content-preview rerank** (Stage 3) — one extra LLM call, defer until 1–4 are measured
6. **ReAct cross-reference loop** (Stage 4) — real engineering work, defer until synthesis is stable

---

## Retired / superseded

- ~~**Fix 2: temporally-explicit topic extraction**~~ — Dropped. Adding temporal phase labels
  to topic phrases ("post-drill: personnel headcount") is overfitting one semantic dimension.
  The underlying issue is vocabulary gap between query language and index label language;
  corpus-grounded glossary (Stage 0) addresses this in general without requiring an index
  rebuild or predicting query dimensions at index time.
