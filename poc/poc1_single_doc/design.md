# PageIndex — Design Document

Single-document knowledge retrieval over markdown policy documents.
No RAG, no vector store. The full document is indexed once; queries read only the relevant sections.

---

## How it works

### Build (one-time, per document)

1. **Parse** — the markdown is split into a tree of nodes by heading level (`#`, `##`, `###`). Each node holds its heading title and its direct text content (not children's).

2. **Normalize** — nodes that are too large (> 5,000 chars) are split by asking an LLM to identify section boundaries within the text. Nodes that are too small (< 1,500 chars) are candidates for merging with their sibling; an LLM decides whether the merge makes semantic sense.

3. **Topic generation** — for each leaf node, an LLM reads the full text and produces a short list of 1–5 word topic phrases (e.g., `Racism incident investigation; Racial slurs; Disciplinary escalation`). These are stored in the index alongside the node.

4. **Save** — the tree (titles, content, topics) is written to a JSON file. That file is everything the query step needs.

### Query (per user question)

1. **Outline** — the index is rendered as a flat, indented list: `[id] Title: topic1; topic2; …`. Parent nodes (those with children) are annotated `[+N children — do not select]`.

2. **Node selection** — an LLM sees the outline and the question. It returns a JSON list of leaf node IDs to read, with a one-sentence reason. It is explicitly instructed not to select parent nodes.

3. **Fallback expansion** — if the LLM does select a parent anyway, it is replaced by its direct children before proceeding.

4. **Synthesis** — the full text of the selected nodes is concatenated and sent to an LLM with the question. The answer cites section IDs inline.

---

## Models

| Step | Model | Why |
|---|---|---|
| Split boundary detection | `gemini-2.5-flash-lite` | Mechanical — find where sections begin |
| Merge decision | `gemini-2.5-flash-lite` | Boolean yes/no on two text blocks |
| Topic generation | `gemini-2.5-flash` | Needs to produce accurate, retrievable phrases |
| Node selection (query) | `gemini-2.5-flash` | Needs to reason about relevance across ~100 nodes |
| Answer synthesis (query) | `gemini-2.5-flash` | Quality answer with citations |

---

## Cost

All costs are on Vertex AI, `europe-west1`. Pricing: flash-lite $0.075/$0.30 per 1M in/out tokens, flash $0.15/$0.60 per 1M in/out tokens.

### Build (one-time per document)

| Document | Nodes | Build cost | Build time |
|---|---|---|---|
| Code of conduct (policy5) | 120 | $0.016 | 71s |
| Health & safety (policy3) | 83 | $0.010 | 58s |
| Family manual | 49 | $0.006 | 60s |
| Child protection (policy1) | 35 | $0.005 | 74s |

Rule of thumb: **~$0.01 per 50 nodes, ~60–75 seconds**. Build runs once and the result is a static JSON file.

### Hosting

The index is a JSON file (~120–365 KB per document). It loads into memory at startup. There is no vector database, no embeddings service, no context cache. Hosting cost is zero beyond the Cloud Run instance that serves queries.

### Query cost

Measured across 16 queries on 4 documents:

| | Value |
|---|---|
| Average cost per query | ~$0.0015 |
| Cheapest query (narrow lookup) | $0.00064 |
| Most expensive query (broad, multi-section) | $0.00274 |
| Queries per dollar | ~660 |

---

## Performance

Measured in iter4 across 16 queries on 4 documents.

**Chars sent to synthesis LLM** (main efficiency metric — less is faster and cheaper):

| | Chars |
|---|---|
| Average | 5,518 |
| Maximum | 17,563 |
| Minimum | 223 |

The maximum (17,563c) is a genuine multi-section child protection query that requires 7 separate leaf nodes. It is not an anomaly — the answer required that breadth.

**Latency:** two LLM round trips per query. Average ~21s wall time; ranges from ~3s (simple, fast node selection + short synthesis) to ~30s (slow selection or many sections). The policy1 Q3 outlier (140s) was a Vertex quota retry, not typical behavior.

**Parent selections:** 0 out of 16 queries. The annotated outline and prompt instruction were sufficient; the fallback expansion never had to fire in this eval.
