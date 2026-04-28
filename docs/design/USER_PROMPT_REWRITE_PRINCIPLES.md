# User Prompt Rewrite Principles

**Purpose:** Define what constitutes an "ideal question" for the rewrite step in the
gateway pipeline. The rewrite step is the single point where conversation history is
used to resolve context; all downstream steps (classify, routing, selection, synthesis)
receive the rewritten question and have no access to history.

**Why this matters:** The rewrite question is the input to a three-stage retrieval
pipeline. Stage 1 (routing, flash-lite) matches the question against an L1 document
outline by vocabulary. Stage 2 (node selection, flash) picks leaf sections within
selected docs. Stage 3 (synthesis, flash) generates the answer. Each stage benefits
from a different property of the ideal question.

---

## The five properties of an ideal question

### 1. Self-contained
All pronouns and implicit references must be resolved using conversation history.
No downstream step has access to history — if an implicit reference survives rewrite,
it will cause a routing miss or a synthesis error.

- "What about teachers?" → "What is the homework correction policy for classroom teachers?"
- "And for part-time staff?" → "Do part-time staff receive the same sick leave entitlement as full-time staff?"
- "yes, go ahead" (after a clarification) → the full question the user confirmed

### 2. Corpus-native vocabulary
The routing model (flash-lite) matches the question against a compact L1 outline of the
knowledge base. Vocabulary mismatch is the primary cause of routing failures in
hierarchical retrieval: if the user says "can my kid stay home sick" but the corpus
section is titled "Absence and Attendance Policy", the router may miss.

The rewrite model receives the corpus L1 summary and should align its output vocabulary
to the terms the knowledge base actually uses. This closes the vocabulary gap without
requiring the user to know the document structure.

### 3. Single topic
One subject per question. Multi-topic questions degrade both routing (router selects
wrong or too many docs) and synthesis (answer is spread across unrelated content).
The `multiple` query_type exists to split compound questions — but rewrite should not
produce a compound question if the user's message is about one thing.

If a follow-up shifts topic, rewrite should cover the new topic only. The prior topic
is already answered and in history.

### 4. Explicit qualifiers only
Include constraints the user stated. Do not add constraints they did not mention.
Invented specificity causes retrieval to narrow to the wrong section or return no
evidence.

- User said "primary teachers" → keep "primary teachers"
- User said "teachers" → do not add "primary" or "secondary"
- User did not mention a year or contract type → do not add one

### 5. Interrogative form
A proper question in the form "What is...", "How does...", "Who is responsible for...",
"What happens when...". The synthesis prompt is framed as question answering; feeding
it a command ("tell me about X") or an affirmation ("yes") degrades output quality.

Non-question inputs that must be converted:
- Short affirmations after a clarification: convert to the question being confirmed
- Commands: "Tell me about the dress code" → "What is the dress code policy?"
- Fragments: "the fees" → "What are the school fees?"

---

## Why each pipeline step benefits

| Stage | Property that matters most | Why |
|---|---|---|
| Classify | Self-contained, single topic | Classifier sees a clean, unambiguous question |
| Routing (flash-lite) | Corpus vocabulary | Cheap model does vocabulary matching against L1 outline |
| Node selection (flash) | Explicit qualifiers | Selection is recall-oriented; hallucinated constraints over-narrow |
| Synthesis (flash) | Interrogative form, self-contained | Answer is generated in response to the question |

---

## Corpus vocabulary access

The gateway fetches and caches the corpus L1 summary from `GET /knowledge/summary`
(10-minute TTL, already used by the classify prompt). The same cached value is passed
to the rewrite prompt — zero additional cost, one extra prompt variable.

The rewrite model should treat the L1 summary as a vocabulary reference: prefer terms
that appear in the outline when they accurately reflect what the user asked. Do not
force a corpus term when the user's phrasing was already precise.

---

## Non-goals

- The rewrite step does not judge scope (that is classify's job).
- The rewrite step does not split multi-topic questions into sub-questions (that is the
  `multiple` path in classify + item I orchestration).
- The rewrite step does not add information not present in the user's message or
  conversation history.
