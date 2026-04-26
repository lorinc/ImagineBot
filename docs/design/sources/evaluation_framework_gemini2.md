Since you are a one-man team looking for speed, you should leverage your top-tier LLM to act as an "Adversarial Test Engineer." Instead of manual curation, use the following automated framework to generate a high-stress "Golden Dataset" directly from your document corpus.

### 1. The "Structural Trap" Prompt (Tests TOC Navigation)
Hierarchical systems often fail because of **Pathway Loss**: the model misinterprets a high-level heading and ignores the correct branch entirely. Use this prompt to find "decoy" paths.

**Prompt for your LLM:**
> "Analyze the Table of Contents (TOC) for these two documents:. Identify 5 instances where a term (e.g., 'Notice Period') appears in multiple branches but with different meanings (e.g., Employment vs. Housing). Generate a question where the semantic meaning of the question matches a 'decoy' header, but the actual policy answer is hidden under a generic or non-obvious header. 
> **Goal:** Trigger a 'Hierarchical Drift' where the retriever picks the wrong branch because the heading looks like a better match."

### 2. The "Vertical Inheritance" Prompt (Tests Sparse Tables)
Empty cells representing "same as above" are frequently lost when tables are converted to Markdown or text. You need to test if your system "reasons upward" to the parent row.

**Prompt for your LLM:**
> "Find the most complex table in that contains empty cells or 'ditto' marks. Identify a specific data point in a deeply nested row where the crucial context (like the Year or Region) is only mentioned 10 rows above it. 
> **Question Task:** Ask a question that requires that specific data point. 
> **Constraint:** The question must not mention the inherited context (e.g., ask 'What is the limit for Item X?' instead of 'What is the 2024 limit for Item X?'). This forces the system to reconstruct the 'Tuple' of information from sparse data.[1, 2]"

### 3. The "Override & Conflict" Prompt (Tests Document Overlap)
In dense policy environments, a "Policy Memo" often overrides a "Handbook" without deleting the old text.[3, 4]

**Prompt for your LLM:**
> "Identify a rule in that is modified or extended by a clause in. 
> **Question Task:** Generate a question where the answer in the Base Handbook is now incorrect or incomplete. 
> **Success Metric:** The system must detect the conflict and prioritize the 'higher-tier' or 'fresher' document over the more semantically similar base document."

### 4. Evolutionary Complexity (Evol-Instruct)
Take any simple fact and "stress-test" it by adding reasoning constraints. 

**Evolution Steps for your LLM:**
1.  **Base Fact:** "Sick leave is 5 days."
2.  **Add Constraint:** "How many sick days if the employee started in November?"
3.  **Add Reasoning Requirement:** "Compare the sick leave of a November hire to a June hire under the 2024 budget."
4.  **Add Scarcity:** "Find the one-sentence exception for 'emergency leave' in the 50-page Appendix and apply it to this scenario.[5]"

### 5. Automation Strategy for a One-Man Team
To build this fast without "experts," use the **LLM-as-a-Judge** pattern for your evaluation loop:

| Step | Action | Tooling Tip |
| :--- | :--- | :--- |
| **Synthesize** | Use an LLM to generate 50 "Multi-Needle" questions (questions requiring facts from 3+ different sections).[6, 5] | Give it the TOC and 5 random chunks at a time. |
| **Execute** | Run these 50 questions through your PageIndex system. | Capture the "Reasoning Trace" (which nodes it visited). |
| **Judge** | Pass the (1) Question, (2) System Answer, and (3) Original Source Text back to your top-tier LLM. | Ask: "Does the answer accurately reflect the source, especially any 'same as above' table logic? Respond VALID/INVALID." |

### Key Failure Modes to Watch For:
*   **Context Fragmentation:** The system finds the "Sick Leave" section but misses the "Eligibility" paragraph three pages earlier.
*   **Inexhaustive Computation:** The system finds the first mention of a rule and stops searching, missing a later "Exception" clause.
*   **Intent vs. Content Gap:** The user asks for a "trend," but the system only retrieves "data points" because they are semantically closer to the keywords.
