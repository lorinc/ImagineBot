# Evaluation framework for a TOC-routed QA system over dense policy documents

## Benchmark design principles

A benchmark for your system should be **corpus-native**, **source-aware**, and **behavior-driven**. Recent RAG evaluation work shows that using public Q&A datasets to assess a local system can lead to non-optimal system design and dataset imbalance, while realistic long-context benchmarks show that multi-document reasoning remains substantially harder than short-context or synthetic QA. LongBench Pro is especially useful here because it labels cases by context dependence, length, and difficulty rather than collapsing them into one generic score. citeturn8view3turn8view4turn8view5turn8view6turn10view2turn10view3turn10view4

For your architecture, one “correct answer” score is not enough. The benchmark has to diagnose three separable stages: **TOC routing** to the right subtree, **evidence assembly** across overlapping and extending documents, and **grounded answer generation** from the selected evidence. Fine-grained RAG evaluation and recent deep-search benchmarks both make the same point: retrieval is often the main bottleneck once evidence becomes sparse, related, multi-hop, and source-distributed. citeturn8view0turn8view1turn8view11

Because your corpus is policy-heavy, the benchmark should not focus only on factual lookup. Policy-oriented evaluation work suggests a much better frame: test **memorization**, **understanding**, and **application** separately, with specific attention to ideas, interests, institutions, numerical reasoning, scenario-based decision-making, procedural implementation, and value explanation. That is a strong match for your corpus, which mixes narrative, facts, decisions, and values. PolicyBench also reports that models often struggle more on policy intent and institutional reasoning than on explicit recall or structured numeric tasks, which is exactly the kind of gap you want your benchmark to expose. citeturn16view0turn16view1turn16view2turn16view3turn16view4

The practical consequence is that each benchmark item should be written to test **one primary failure mode** and, at most, **one or two secondary ones**. If you do not label cases that way, you will get an aggregate score without knowing whether your system failed because the TOC router picked the wrong branch, because the source selector missed an exception document, because the table parser lost inherited header context, or because the answerer hallucinated from partial evidence. Behavior-driven evaluation work argues explicitly for this shift from undifferentiated benchmarks to scenario-specific test specifications. citeturn13view4

## Benchmark item schema

The basic unit should be a **test specification first, question second**. In the literature, behavior-driven evaluation frameworks first describe the expected system behavior in a scenario and then instantiate concrete tests from it; that is the right pattern for your use case because you already know the architecture and its likely blind spots. Likewise, HotpotQA’s sentence-level supporting facts and GaRAGe’s passage-level grounding annotations show why evidence must be labeled at a finer granularity than “this document contains the answer.” citeturn13view4turn8view8turn17view1

Each item in your benchmark should store all of the following:

- **Question ID and corpus snapshot ID** so results remain valid when documents change.
- **Primary slice label** and **secondary slice labels**, such as polysemy, overlap-extension, exception handling, table carry-forward, sparse mention, multi-doc synthesis, scenario application, or abstention.
- **Answerability label**, such as answerable, underspecified, false presupposition, out-of-corpus, or conflict-requires-qualified-answer.
- **Answer type**, such as span, boolean, list, comparison, calculation, procedure, explanation, or abstain.
- **Canonical answer** plus acceptable variants.
- **Gold TOC path**, including the correct ancestor nodes and the correct leaf node or nodes.
- **Gold evidence units**, at the level of page, paragraph, list item, table, row group, or cell span.
- **Evidence necessity label**, such as required, supporting-but-optional, or distractor.
- **Relation label between sources**, such as same document, sibling section, addendum, override, extension, exception, cross-reference, or table-plus-text.
- **Coverage label**, distinguishing a **full-dependency** item from a **partial-dependency** item. LongBench Pro and Loong both show why this matters: some questions fail if even one required source is missing. citeturn10view2turn10view3turn7view12
- **Normalization instructions**, especially for table inheritance, header propagation, footnotes, and document-precedence rules.
- **Scoring rubric**, including answer scoring, evidence scoring, and abstention criteria.

For table questions, annotate both the **raw table region** and the **normalized semantics**. HybridQA and TAT-QA show that many grounded answers require reasoning over both cells and surrounding text, and DocFinQA shows that long-document QA breaks down when retrieval and context disambiguation are weak. In your corpus, empty cells that mean “same as above” should therefore be made explicit in annotation, because otherwise you will not know whether failure came from routing, retrieval, or table interpretation. citeturn7view3turn7view7turn9view2

For multi-page documents, keep page-level location labels even if the downstream answerer only sees extracted text. Multi-page document QA work treats page identification as an explainability signal, and that is highly relevant to your system because a TOC-based router should be judged not just on whether it found the right document, but on whether it routed to the right structural region inside that document. citeturn9view3turn11view0turn11view1

## Question families that will actually stress this system

The question set should deliberately target the failure modes that matter for dense policy corpora: reasoning-intensive retrieval, connected multi-hop composition, policy-specific understanding, table-text integration, and correct abstention. Those needs line up well with the lessons from BRIGHT, MuSiQue, HotpotQA, Loong, HybridQA, TAT-QA, and policy-oriented benchmarks, but your version should be tailored to TOC routing, source overlap, and policy interpretation. citeturn8view7turn8view8turn8view9turn8view10turn7view12turn16view3turn16view4

**Routing-heavy families**

Questions in this group are supposed to confuse subtree selection rather than final answer generation. BRIGHT shows how sharply retrieval quality can drop when a query requires reasoning instead of surface-form matching, while LOFin shows how standardized document collections create confusion through near-duplicate tables and repetitive narratives. citeturn8view9turn8view10turn9view7

- **Local-definition disambiguation**: one term appears across multiple documents but has a different operational meaning in each.  
  *Template:* “Under the context of [specific program/process], what counts as ‘X’ when deciding [decision]?”
- **TOC-cousin trap**: the obvious heading is wrong, and the real answer sits in a sibling section, annex, footnote, or appendix.  
  *Template:* “According to the policy’s reporting requirements, who must approve [action]?” where the answer is hidden in exceptions or implementation notes.
- **Overlap-plus-extension**: one document states a base rule and another extends it without fully restating it.  
  *Template:* “For [role or region], does the general rule still apply, or does the addendum modify it?”
- **Single-mention critical detail**: the decisive fact appears exactly once in a note, example, exception box, or row label.  
  *Template:* “Which cases are excluded from [rule] when [rare condition] is present?”
- **Cross-reference hop**: the section points elsewhere and the first passage alone is insufficient.  
  *Template:* “What is the approval path for [case]?” where the answer requires following an internal pointer.
- **Carry-forward table interpretation**: blank cells inherit prior row or header meaning.  
  *Template:* “Under the eligibility table, are [group] in [condition] exempt?” where the answer requires reconstructing implied values.

**Reasoning-heavy families**

This group should force genuine composition rather than shortcut retrieval. MuSiQue was explicitly built to require connected reasoning, HotpotQA emphasizes supporting facts and comparison, Loong stresses cases where each source is necessary, and PolicyBench shows why policy QA must include application, procedure, and value explanation rather than fact recall alone. citeturn8view7turn8view8turn7view12turn16view3turn16view4

- **Rule plus exception plus scenario**: the answer requires composing a general rule, an exception, and the facts of a case.  
  *Template:* “A staff member in [scenario] wants to do [action]. Is it allowed, and why?”
- **Comparison across documents**: the answer is not a lookup but a contrast.  
  *Template:* “How does the approval requirement differ between [group A] and [group B]?”
- **All-docs-required synthesis**: every supporting source matters; omitting one changes the conclusion.  
  *Template:* “What conditions must all be satisfied before [outcome] can occur?”
- **Temporal or precedence reasoning**: later guidance, departmental addenda, or special annexes alter earlier rules.  
  *Template:* “Which rule governs this case if the handbook says X and the later circular says Y?”
- **Procedural implementation**: the system must infer an action sequence rather than restate a clause.  
  *Template:* “What is the correct process for [situation], including required approvals and timing?”
- **Policy logic and value explanation**: the answer requires purpose, rationale, or underlying principle.  
  *Template:* “Why does the policy treat [case] differently from [other case]?”
- **Numerical or threshold reasoning from prose plus table**: the answer requires combining numbers across formats.  
  *Template:* “Given [values], what cost share / threshold / limit applies?”

**Grounding-heavy families**

Grounding and abstention are just as important as answer correctness. UAEval4RAG shows why RAG systems should be evaluated on underspecified and false-presupposition queries, not only answerable ones, and GaRAGe shows that models often over-summarize from noisy evidence, cite irrelevant passages, and fail to deflect when the grounding is insufficient. citeturn13view2turn17view0turn17view1

- **Underspecified scenario**: the question asks for a decision but omits a required factor.  
  *Template:* “Is this employee eligible?” without region, status, or timing.
- **False presupposition**: the question assumes a rule exists when it does not.  
  *Template:* “What is the penalty for [action] under policy X?” where policy X contains no such rule.
- **Out-of-corpus request**: the correct behavior is to say the corpus does not contain the answer.  
  *Template:* “What does the policy say about [topic not covered anywhere]?”
- **Conflict with qualified answer**: the sources disagree or apply to different scopes, so the right answer is conditional rather than absolute.  
  *Template:* “Does the organization permit [action]?” when the correct answer is “depends on unit / role / geography.”
- **Near-miss distractor**: there is a plausible but wrong answer in a closely related document.  
  *Template:* “Who is the approving authority?” where two approvals exist for similar but distinct workflows.

A useful authoring rule is that **hard questions should not be answerable by local lexical overlap alone**. MuSiQue was designed to prevent shortcut reasoning, BRIGHT shows that surface-match retrieval is not enough for complex queries, and classic long-document QA work argues that superficial local similarity should not decide the outcome. In practice, paraphrase your questions away from source wording, include at least one plausible distractor path from the same policy family, and ensure that the answer is not recoverable from a title or an isolated sentence unless the item is intentionally labeled easy lookup. citeturn8view7turn8view9turn6search5

## Scoring and diagnostics

Do not evaluate this system with answer accuracy alone. RAGChecker argues for fine-grained diagnostics across retrieval and generation; ARES shows that component-level evaluation can be scaled with a small human-labeled set and prediction-powered inference; GaRAGe adds grounding-aware metrics and deflection tests; sub-question coverage work shows that multi-facet questions need coverage measures, not just final-answer judgments; and behavior-driven evaluation warns that aggregate benchmark metrics often miss operational failure modes. citeturn8view0turn8view1turn8view2turn13view1turn17view0turn17view1turn13view4

A strong scoring stack for your system should include the following:

- **TOC routing recall**: did the router select any gold ancestor node within top *k*?
- **Leaf routing recall**: did it reach the correct section, page region, table, or appendix?
- **Path accuracy**: exact gold path match, plus **depth of first divergence** for partial credit.
- **Evidence coverage**: fraction of required evidence units retrieved.
- **Evidence precision or minimality**: fraction of retrieved evidence that is actually relevant.
- **Answer correctness**: exact match, token F1, numeric tolerance, boolean accuracy, or rubric score depending on answer type.
- **Grounded claim rate**: fraction of answer claims supported by retrieved evidence.
- **Citation accuracy**: whether cited passages are both relevant and sufficient.
- **Sub-question coverage** for multi-aspect items: whether the answer covered all core facets, not just one.
- **Abstention quality**: true-reject rate, false-reject rate, and refusal calibration on negative items.
- **Robustness slices**: paraphrase stability, distractor susceptibility, precedence handling, and table-normalization accuracy.
- **Efficiency**: pages, nodes, tokens, or sections inspected before answering.

A particularly important rule for this benchmark is **evidence-gated scoring**. If the system never reaches a gold leaf node, answer credit should be capped even if the generated text appears accidentally correct. Otherwise, you will reward lucky guessing and hide routing failures. Grounding-aware benchmarks such as GaRAGe and fine-grained frameworks such as RAGChecker strongly support separating “looked plausible” from “was actually supported by relevant evidence.” citeturn17view0turn17view1turn8view0

For open-ended answers, use a rubric with distinct dimensions for **completeness**, **hallucination**, and **irrelevance**, which is close to the setup proposed in RAGEval. For multi-aspect policy questions, also score **coverage** explicitly, because work on sub-question coverage shows that systems often answer one core facet while silently missing other important ones. citeturn14view0turn14view1turn13view1

Always evaluate against a **baseline ladder**, not just your full system. At minimum, run: a flat lexical retriever baseline, a flat dense-retrieval-plus-reranking baseline, your full TOC-routed system, an **oracle-routing** condition that hands the answerer the correct subtree, and an **oracle-evidence** condition that hands the answerer the gold passages or cells. BEIR is a useful reminder that BM25 remains a robust baseline, and DocFinQA’s comparison of retrieval-based and retrieval-free settings shows why this kind of decomposition is necessary when reasoning over long documents. citeturn7view0turn9view2

Use **human scoring on a carefully sampled slice**, then use automated judges for scale. ARES, RAGAS, RAGChecker, GaRAGe, and RAGEval all support some form of automated RAG evaluation, but the most reliable setup is still hybrid: human adjudication for benchmark construction and calibration, automated judges for iteration and large runs. citeturn7view1turn8view0turn8view2turn17view1turn14view0

## Construction workflow

The lowest-risk way to build this benchmark is a **human-in-the-loop pipeline with model assistance**. LongBench Pro uses a human-model collaborative construction process to draft hard questions and reference answers before expert verification, LegalBench and CUAD show the value of expert-designed domain tasks, GaRAGe shows why human grounding annotation matters, and RAGEval plus behavior-driven evaluation show how generation can be scaled if the final evaluation set is still curated against explicit scenario requirements. citeturn10view2turn10view3turn7view6turn9view6turn17view1turn14view0turn13view4

A practical workflow looks like this:

1. **Map the corpus structurally.**  
   Build a document-family graph that records base handbooks, annexes, addenda, overrides, revisions, and cross-references. Also record table locations, appendices, and version dates.

2. **Define your slice inventory before writing questions.**  
   Decide exactly which failure modes you want covered: local-definition ambiguity, overlap-extension, exception handling, sparse mention, carry-forward tables, multi-doc synthesis, scenario application, value explanation, underspecification, false presupposition, and out-of-corpus requests.

3. **Create source bundles rather than single-document prompts.**  
   For each candidate item, assemble the smallest document bundle that contains the necessary evidence plus one or two adversarial distractors from the same family.

4. **Generate candidate questions with labels, not free-form brainstorming.**  
   Prompt an LLM to create questions for a specific slice label and answer type, then ask a second model or reviewer to reject cases that are shortcut-solvable, ambiguous, or too close to source wording. This follows the label-targeted generation logic recommended by Know Your RAG and the schema-based generation pattern used by RAGEval. citeturn8view3turn8view4turn14view1

5. **Require expert adjudication for the hard set.**  
   A reviewer should finalize the canonical answer, acceptable variants, gold TOC path, gold evidence units, normalization operations, distractor paths, and abstention rule.

6. **Add paraphrases and adversarial rewrites.**  
   Each core item should have at least one paraphrase that changes lexical cues without changing intent, and at least one negative or distractor variant if the slice allows it.

7. **Pilot on your full system and the baseline ladder.**  
   Then mine the failures. If the system repeatedly misses appendix exceptions, build more appendix-exception items. If it confuses department-specific addenda with organization-wide rules, create a dedicated precedence slice.

8. **Freeze a hidden test set against a corpus snapshot.**  
   Keep at least part of the benchmark private, and version it when the corpus changes. Overlapping policy corpora evolve, and benchmark integrity depends on knowing exactly which snapshot the system was tested against.

The key discipline is to treat benchmark authoring as **failure-mode engineering**, not content summarization. The question is never just “what can I ask from this corpus?” It is “what question will tell me whether TOC routing, evidence assembly, and grounding are all functioning under a realistic policy-document stress condition?” That is the shift advocated by recent work on behavior-driven and scenario-specific evaluation. citeturn13view4turn14view2

## Starter benchmark plan

If you need a concrete and practical first release, build a **300-item benchmark** with roughly one third kept hidden for final evaluation. That is large enough to expose slice-level weaknesses and small enough to annotate carefully.

A good v1 composition is:

- **30** local-definition and terminology-in-scope questions
- **30** TOC-cousin and wrong-branch routing traps
- **35** overlap, extension, override, and exception questions
- **25** sparse-mention, appendix, or footnote questions
- **35** table carry-forward and table-plus-text reasoning questions
- **35** multi-document comparison or all-docs-required synthesis questions
- **35** scenario-based decision and procedural implementation questions
- **20** policy logic, rationale, and value explanation questions
- **25** underspecified or missing-fact questions that should trigger clarification or abstention
- **30** false-presupposition, out-of-corpus, or conflict-qualified-answer questions

You should also impose a few portfolio constraints on the whole set:

- At least **40%** of items should require multiple evidence units.
- At least **20%** should involve tables.
- At least **20%** should be explanatory or scenario-based rather than pure lookup.
- At least **15%** should be negative or abstention items.
- Every answerable item should include at least one **gold TOC path** and one **adversarial distractor path**.
- Every negative item should include a written explanation of **why abstention is correct**.

This composition is justified by the main lessons in recent evaluation work: public generic datasets are not enough; realistic policy reasoning needs separate testing of recall, understanding, and application; retrieval must be evaluated under reasoning-intensive and source-overlap conditions; grounding and abstention need their own metrics; and aggregate scores hide the exact failure modes you most need to diagnose in compound QA systems. citeturn8view3turn16view0turn16view3turn8view9turn8view11turn17view1turn13view2turn13view4

If you build the benchmark this way, it will tell you not merely whether the system “got the answer,” but whether it routed to the correct subtree, selected the right sources among overlapping policy documents, reconstructed implicitly inherited table meaning, respected precedence and exceptions, covered all required facets of the question, and knew when the corpus did not justify an answer. That is the diagnostic resolution your architecture needs. citeturn8view0turn17view1turn13view4