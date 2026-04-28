# School Chatbot Knowledge Layer — System Design

## Overview

A multi-tenant chatbot that answers parent questions about school documents. The knowledge layer must handle cross-document reasoning, ephemeral and long-lived content, and high query repetition — at minimal infrastructure cost.

---

## Document Corpus

Each school maintains 10–50 markdown documents, ranging from 15kb to 150kb. A preprocessing pipeline ensures clean heading hierarchy (`#`/`##`/`###`).

Documents fall into three lifecycle categories:

- **Large, slow-changing**: policies, handbooks, enrollment guides. Updated rarely — months or years between changes.
- **Small, temporary**: event announcements, one-off notices. Created, served for days or weeks, then deleted.
- **Small, periodically rewritten**: weekly menus, newsletters, schedules. Replaced entirely on a regular cadence.

---

## Core Architectural Problem

Parent questions frequently require answers that span multiple documents. "Can my kid bring a football to school?" may be addressed in a bus safety policy (balls as safety hazard), a parent handbook (permitted items), and a behavior policy (playground conduct). Each document uses different vocabulary.

Vector similarity search retrieves text that *sounds like* the query. It does not retrieve text that *answers* the query when the vocabulary doesn't align. A bus safety regulation about "inflatable sporting equipment during transport" does not look like an answer to "can my kid bring a football" in embedding space — but it contains a critical constraint on the answer.

This is not an edge case. Policy questions are inherently cross-document and vocabulary-mismatched. Getting them wrong has real consequences for parents and schools.

---

## Architecture: Three Layers

### Layer 1 — Precomputed Answer Index

Parent queries are highly repetitive — estimated 95/5 ratio of repeated to novel questions. The precomputed answer index serves the vast majority of queries with no retrieval pipeline and no LLM call.

The system stores every question asked, along with the generated answer and the `doc_id`s that contributed to it. Incoming queries are matched against stored questions via semantic similarity. On a hit, the precomputed answer is served directly.

This is not a cache. When a source document changes, stored questions referencing it are **re-answered in batch** against the updated documents, not deleted. The answer index is always warm. There is no cold start after document updates.

**What this enables beyond caching:**

- **Quality feedback loop.** Accumulated questions reveal what parents actually ask. Clusters of poorly-answered questions identify retrieval gaps or missing source content.
- **FAQ as a retrieval layer.** The stored questions themselves become a searchable index. New phrasings of old questions ("are balls allowed" vs. "can my kid bring a football") match against the question index without running the full pipeline.
- **Surgical invalidation.** When a document changes, the system can check whether the update actually affects each stored answer — unchanged answers remain valid even if their source document was modified.
- **HyQ convergence.** Hypothetical questions generated at index time (see Chunk Augmentation below) start as synthetic. Over time, they are replaced or supplemented by real parent questions from the answer index. The synthetic questions bootstrap retrieval quality; real questions refine it.

**Regeneration cost on document change:** all stored questions referencing the changed document are re-run through the retrieval pipeline in batch. At ~$0.005–0.010/query, 200 affected questions cost $1–2 per document update — acceptable for documents that change rarely. Periodically rewritten documents (menus, schedules) are referenced by fewer stored questions, so regeneration cost is proportionally smaller.

Latency: ~100ms (semantic similarity lookup + answer retrieval from Postgres).

### Layer 2 — Routing Layer (document selection)

When a query misses the answer index, the system must determine which documents are relevant before querying them. The open-source PageIndex operates on single documents, so a routing layer is needed to select which document trees to query.

Two routing strategies are under evaluation:

**Option A — Meta-tree (PageIndex-of-PageIndexes).** Extract root-node summaries from all per-document trees into a master document. Build a PageIndex tree on that master document. At query time, an LLM reasons over the meta-tree to identify which documents are relevant. This preserves reasoning-based retrieval at the routing level — the LLM can infer that "football on school premises" should check transport policy, equipment policy, and behavior policy, even when the vocabulary doesn't match.

**Option B — Vector search over document summaries.** Embed each document's root-node summary (or a generated document-level summary) into a pgvector index. Route by semantic similarity against these summaries. Faster and cheaper than an LLM reasoning call, but subject to the same vocabulary-mismatch limitations that motivate PageIndex in the first place.

Option A is more aligned with the architectural rationale for choosing PageIndex. Option B is simpler and cheaper. The choice depends on how well vocabulary-mismatched queries route under Option B in practice.

### Layer 3 — PageIndex Retrieval (per-document)

Each document has a PageIndex tree built from its markdown heading structure. The tree generator uses regex-based heading detection (zero LLM cost) to build the structural hierarchy, then generates one LLM summary per node.

At query time, the LLM reads a selected document's tree (summaries only, not full text), reasons about which nodes contain relevant content, then reads the full text of those nodes. This is two LLM calls per document queried.

For a multi-document query, the routing layer selects 1–3 documents, and retrieval runs against each selected document's tree. Results from all selected documents are passed to a final synthesis call that produces the answer with citations.

**Why PageIndex over vector chunking:** PageIndex preserves document hierarchy, handles cross-section references, and retrieves by relevance (LLM reasoning) rather than similarity (embedding distance). For structured school documents with clean heading hierarchy, the tree maps directly to the document's own organization. The football-on-the-bus scenario — where the answer spans sections with mismatched vocabulary — is handled structurally rather than through compensating mechanisms.

**Latency for a full pipeline miss:** routing (~1–2s) + per-document retrieval (~1–2s per document, 1–3 documents) + synthesis (~1–2s) = ~3–6s total. Within the 5s soft limit for most queries. For complex multi-document queries that exceed it, a parallel conversational agent running on a fast/cheap model provides small-talk while the answer generates.

---

## Chunk Augmentation (relevant if vector routing is chosen)

If Option B (vector routing) is selected, two preprocessing techniques improve routing quality:

- **Contextual retrieval** (Anthropic pattern): for each document, an LLM reads the full source and generates a context snippet explaining the document's role and coverage. Prepended to the document summary before embedding.
- **HyQ (Hypothetical Questions)**: for each document (or each major section), an LLM generates questions the document would answer. Stored as additional embedding vectors pointing to the same document, so the router can match by question similarity rather than summary similarity.

HyQ is particularly valuable here because it converges with the precomputed answer index over time. Synthetic questions bootstrap routing quality at launch; real parent questions from the answer index replace them as the system accumulates usage data.

Both techniques cost ~$1–3 per school for the full corpus, one-time. Incremental updates re-process only changed documents.

If Option A (meta-tree routing) is selected, these techniques are unnecessary — the LLM reasons over document summaries directly and does not depend on embedding similarity.

---

## Multi-Tenancy

All tenants share one Supabase Postgres instance. Isolation via Row Level Security on a `school_id` column:

```sql
CREATE POLICY "tenant_isolation" ON document_chunks
FOR ALL TO authenticated
USING (school_id = (auth.jwt() -> 'app_metadata' ->> 'school_id')::uuid);
```

PageIndex trees (stored as JSON), the precomputed answer index, and all metadata use the same `school_id` isolation.

---

## Document Lifecycle Management

Each record carries an `expires_at` timestamp and a `content_type` enum. Query-time filter: `WHERE expires_at IS NULL OR expires_at > NOW()`. A daily `pg_cron` job deletes expired rows.

| Type | `expires_at` | Update pattern |
|------|-------------|----------------|
| Large, slow-changing | `NULL` | Re-index on change |
| Small, temporary | Set at creation | Auto-expire |
| Periodically rewritten | N/A | Delete-and-replace on rewrite schedule |

When documents change, expire, or are replaced:

1. The document's PageIndex tree is regenerated (or deleted).
2. The meta-tree (Option A) or document summary embeddings (Option B) are updated.
3. Precomputed answers referencing the document are re-generated in batch.

---

## Indexing Pipeline

Event-driven. Markdown files land in Cloud Storage → Cloud Function triggers:

1. **Tree generation**: regex-based heading detection → structural hierarchy (zero LLM cost) → node summarization (one LLM call per node) → store tree as JSON in Postgres.
2. **Routing layer update**: extract root-node summary → update meta-tree (Option A) or re-embed document summary (Option B).
3. **Answer index regeneration**: identify stored questions referencing the changed document → re-run through routing + retrieval pipeline in batch.

Incremental updates use hash-based change detection (SHA-256 per source document). Changed documents are fully re-processed.

---

## Cost Structure

### Fixed costs

| Service | Cost | Role |
|---------|------|------|
| Supabase Pro | $25/month | Postgres: trees, answer index, metadata, RLS, optional pgvector for routing |
| Cloud Run | $0 (free tier) | API endpoint, scales to zero |
| Cloud Functions | $0 (free tier) | Ingestion pipeline |
| Cloud Scheduler | $0 | Cron jobs for TTL cleanup and answer regeneration |

### Per-query cost (pipeline miss, before answer index)

Routing call + 1–3 document retrievals + synthesis: ~$0.005–0.015/query depending on documents selected.

### Effective cost (with 95% answer index hit rate)

| Queries/day | Effective monthly query cost |
|-------------|------------------------------|
| 100 | ~$1–3 |
| 2,000 | ~$15–45 |
| 5,000 | ~$40–115 |

### One-time indexing cost per school

PageIndex tree generation (node summarization): depends on node count per document — requires measurement on real documents. Contextual retrieval + HyQ (if vector routing): ~$1–3 per school.

---

## Open Questions

### Must evaluate before implementation

1. **PageIndex node density on real documents.** Run the open-source tree generator on one large and one small document from the actual corpus. Node count drives indexing cost, meta-tree size, and retrieval latency. All cost estimates depend on this.

2. **Routing layer: meta-tree vs. vector search.** Test both on the same set of cross-document queries (the football scenario and similar). Does the meta-tree's reasoning advantage over vector routing justify the extra LLM call? Or does vector routing with HyQ-augmented document summaries route accurately enough?

3. **Semantic similarity threshold for answer index matching.** How close must an incoming query be to a stored question before serving the precomputed answer vs. running the full pipeline? Too loose → wrong answers served. Too strict → unnecessary pipeline runs. Requires testing with real parent queries.

4. **Cross-document query ratio.** What fraction of real parent queries require multi-document answers? This determines how much value the routing layer's reasoning capability adds. Needs real query data.

5. **Meta-tree size at multi-tenant scale.** With 50 documents per school, the meta-tree fits in a single LLM context window. At scale with shared district-level documents, does it still fit, or does it need a pre-filtering step?

### Should test but non-blocking

6. **HyQ vs. contextual retrieval vs. both.** If vector routing is chosen, do these provide additive quality improvement, or is one sufficient?

7. **Answer regeneration filtering.** When a slow-changing document updates, can we cheaply determine which stored answers are actually affected by the change vs. re-running all of them?

8. **PageIndex reasoning model selection.** Which LLM (Gemini Flash, Claude Haiku, other) produces the best node selection quality at lowest cost for school-domain content?

9. **HyQ-to-real-question transition.** At what point does the accumulated real question corpus make synthetic HyQ questions redundant? Is there a useful feedback loop where real questions improve HyQ generation for new documents?

10. **Latency masking effectiveness.** Does the conversational small-talk agent successfully mask 5–8 second retrieval times in user testing, or do parents perceive the delay negatively regardless?
