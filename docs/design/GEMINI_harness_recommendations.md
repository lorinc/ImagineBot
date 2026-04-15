### Building a Robust RAG Pipeline over Hierarchical Policy Documents
*(Context: The following guide details how to build an enterprise Question-Answering system over structured, rule-heavy documents. It addresses common pipeline failures, such as missing vocabulary matches, hallucinating terms, over-selecting irrelevant sections, dropping critical "if/then" conditions, and failing to follow cross-references.)*

Here is a concrete breakdown of best practices across the query-to-answer lifecycle, anchored directly to your failure modes.

#### 1. Query Understanding Stage
**Goal:** Determine what the user actually wants before touching the index.
* **Intent Routing:** Use a fast, specialized classifier (like a fine-tuned SetFit model or a small LLM prompt) to categorize the query (e.g., *Definitional, Procedural, Troubleshooting, Out-of-Scope*). 
* **When to Ask vs. Infer:** Implement a "Confidence Threshold." If the entity extraction fails to find a required parameter (e.g., the query asks about "safety protocols" but doesn't specify which facility, and facility is a top-level hierarchy requirement), the system must ask. You can rely on LLM-as-a-judge prompts that score query completeness from 1-5; anything below 3 triggers a clarifying question.

#### 2. Document-Aware Query Reformulation
**Goal:** Fix the "fire drill" vs. "Personnel check" vocabulary gap without blind expansion.
* **Avoid "HyDE" (Hypothetical Document Embeddings):** Relying on the LLM's world model to write a fake answer for expansion will cause the domain bleed you noted.
* **Corpus-Grounded Glossaries:** Run an offline, one-time LLM job over your corpus to extract a mapping of common terms to their official policy labels. Inject this dictionary into your query-rewriting prompt.
* **Pseudo-Relevance Feedback (PRF):** If you must expand dynamically, do a preliminary, highly aggressive keyword search against your outline. Feed those initial, raw hits to the LLM and prompt: *"Given this query and these available index labels, rewrite the query to strictly use the terminology found in the index."*

#### 3. Retrieval Quality (Outline Selection)
**Goal:** Stop the LLM from selecting 7 sibling sections when only 2 are relevant.
* **Two-Stage Selection Prompting:** Do not ask the LLM to simply "select all relevant sections." 
    * *Prompt Pattern:* "1. Identify the *single* most critical section ID. 2. Only select additional section IDs if their titles contain information that is strictly missing from the primary section. Penalize redundancy."
* **Strict JSON Schemas:** Force the model to output its selection alongside a justification and confidence score. The act of generating the justification acts as a Chain-of-Thought (CoT) mechanism, forcing the model to evaluate utility before selecting.

#### 4. Reranking
**Goal:** Filter the LLM's initial broad recall down to high-precision hits.
* **Cross-Encoders:** This is a mature, highly validated practice. If your LLM selects 5 sections from the outline, fetch the actual text bodies of those 5 sections. Pass the query and the 5 texts through a Cross-Encoder (like `bge-reranker-v2-m3` or Cohere Rerank). 
* **Benefit:** Cross-encoders look at the deep semantic relationship between the query and the actual text, easily pruning the "near-identical sibling subsections" that tricked the LLM outline-reader. Keep only the top 1 or 2 highest-scoring chunks.

#### 5. Synthesis Guardrails
**Goal:** Prevent the system from dropping conditional clauses ("normally X, but not if Y").
* **Constitutional / Step-by-Step Prompting:** Synthesis drops conditions when it rushes to summarize. Force it to extract structure first.
    * *Prompt Pattern:* "Read the context and formulate your answer in three strict steps:
        1. **Core Rule:** State the primary directive.
        2. **Exceptions & Conditions:** Explicitly list any 'if', 'unless', 'except', or 'provided that' clauses found in the text.
        3. **Final Answer:** Combine step 1 and 2 into a coherent response."
* **Strict "I Don't Know":** Add a system instruction: *"If the context does not explicitly contain the answer, do not guess. Output exactly: 'I cannot answer this based on the provided documents.'"*

#### 6. Multi-Hop and Cross-Reference Handling
**Goal:** Detect "see section 3.4" and actually fetch it.
* **Agentic / ReAct Loops:** Standard RAG is a linear pipeline. Multi-hop requires an iterative loop.
* **Execution:** Instead of drafting a final answer immediately, the LLM is prompted to evaluate if it has enough information. If it sees a cross-reference, it outputs a tool call: `{"action": "fetch_section", "target": "3.4"}`.
* **Bounding Recursion:** The orchestration layer (e.g., LangGraph or custom Python logic) intercepts this, fetches 3.4, appends it to the context, and re-prompts the LLM. You must hardcode a `max_iterations = 3` limit in your backend loop to prevent infinite recursive fetches.

#### 7. Evaluation
**Goal:** Distinguish retrieval failures from synthesis failures and catch confident hallucinations.
* **Frameworks:** Use RAGAS (Retrieval Augmented Generation Assessment) or ARES. These are emerging standards that use an LLM-as-a-judge to score distinct pipeline steps.
* **Isolating Metrics:**
    * *Context Precision:* Did the outline-selector pick the right section?
    * *Answer Faithfulness:* Does the final answer perfectly map to the retrieved text? (This is how you catch the dropped "but not if Y" conditionals. If the context has a condition and the answer doesn't, Faithfulness drops).
* **Test-Set Construction:** You need a "Golden Dataset." Manually write 50-100 queries representing your known failure modes (e.g., queries with heavy slang, queries requiring multi-hop). Pair them with the known correct section IDs and the known correct answers. 

***

### Summary of Techniques & Trade-offs

| Dimension | Recommended Technique | Primary Benefit | Latency/Cost Trade-off |
| :--- | :--- | :--- | :--- |
| Query Understanding | Intent Routing (SetFit/Small LLM) | High accuracy, prevents wasted searches | Low latency, low cost |
| Formulation | Corpus-Grounded Glossaries | Fixes vocab gaps, prevents blind expansion | Low runtime latency, high offline prep cost |
| Retrieval | Chain-of-Thought Selection Prompting | Drastically reduces over-selection | High latency (longer LLM generation) |
| Reranking | Cross-Encoder (e.g., BGE-Reranker) | Filters out irrelevant sibling sections | Medium latency (requires GPU compute) |
| Synthesis | Structured Condition Extraction | Preserves explicit rules and caveats | Medium latency (higher token output) |
| Multi-hop | ReAct Loop with `max_iterations` | Solves cross-references | Very high latency/cost (multi-turn LLM calls) |
| Evaluation | RAGAS Framework (Faithfulness metric) | Isolates synthesis errors from retrieval | High offline compute cost |

If you were to prioritize implementing just one of these architectural shifts today to maximize immediate impact on your known failure modes, which one seems the most feasible for your current stack?