# Spike: retrieval
Date: 2026-03-21
Status: COMPLETE

## Question
Which retrieval mechanism should the knowledge service use to find relevant context
across school documents (policies, timetables, menus, newsletters) given a query,
a current date, and a set of permitted source IDs — with mandatory citation?

## Corpus context (informed this decision)
- Format: Markdown, preprocessed for ingestion (enforced header hierarchy, tables
  rewritten as natural language)
- Size: 1–1000 KB per document, ~tens of documents per school
- Cross-references: unpredictable and subtle; entity mentions (pickup times, event
  dates, class names) appear across multiple documents and must be resolved to the
  same entity
- Change rate: some documents change weekly (newsletters), others have paragraph-level
  monthly changes; corpus must stay fresh without full reindex
- Query pattern: multi-hop temporal reasoning — e.g., "what time is pickup tomorrow?"
  requires: standard rule (policy) + any date-specific exception (newsletter) + current
  date injection. Citation of every claim is a hard requirement.
- Scale: MVP = 1 school, 2–3 concurrent users

## Options considered

### Option A: Pure vector search (Firestore Vector Search or pgvector)
- **How it works:** Embed each chunk at write time. At query time, embed the query and
  return the top-k most similar chunks by cosine distance. LLM reasons over the chunks.
- **Pros:** Simple, well-understood, low latency.
- **Cons:**
  - The core query type ("standard pickup time, overridden by newsletter for tomorrow")
    is a temporal entity resolution problem, not a similarity problem. Vector search
    returns the most similar chunks — it does not know that the newsletter chunk
    *supersedes* the policy chunk for a specific date.
  - Cross-document entity resolution is absent: "pickup at 15:30" in the policy and
    "pickup at 16:00 on Tuesday" in the newsletter are retrieved independently; the LLM
    must infer the override relationship without structural support.
  - Subtle cross-references (e.g., "see also the transport policy" implicit in a
    newsletter) are not followed.
  - Citation is chunk-level, not entity-level — the provenance chain is weak.
- **Estimated complexity:** Low to build, but structurally mismatched to the problem.

### Option B: R2R (SciPhi)
- **How it works:** Hybrid search (vector + BM25, reciprocal rank fusion) + automatic
  knowledge graph extraction from ingested documents. "Deep Research API" for multi-step
  queries. Managed at app.sciphi.ai. Collections map to access control groups.
- **Pros:**
  - Generous free tier: 300 RAG requests/month, 3,000 searches/month, 100 files, 1 GB
  - Hybrid search improves recall on keyword matches ("bus route 14") and semantic matches
  - Collections provide a multi-tenancy model that maps to permitted_source_ids
  - Production-ready managed service, Python SDK
- **Cons:**
  - Knowledge graph extraction is LLM-powered but not temporally structured. The
    "newsletter overrides policy for this specific date" relationship must be inferred
    by the LLM at query time from retrieved chunks — there is no bi-temporal model.
  - Collection permissioning is documented as "still under development, API will likely
    evolve" — a risk for a system with a multi-tenancy roadmap.
  - Citation mechanism not clearly documented.
  - Subtle cross-references between documents rely on vector proximity, which may miss
    implicit relationships.
- **Estimated complexity:** Low to integrate. Medium risk due to evolving permission API.

### Option C: Pageindex
- **How it works:** Vectorless, tree-structured indexing. Documents are converted to
  hierarchical trees; an LLM navigates the tree to find relevant sections. MCP-compatible.
  First-class Markdown support (`POST /markdown/`). Built-in citation: `<doc=file;page=1>`.
- **Pros:**
  - Excellent within-document navigation — good for long, structured policy documents
  - Native Markdown ingestion
  - Built-in citation format
  - MCP integration available
- **Cons:**
  - No documented collection/access control beyond API key — a hard blocker for the
    multi-tenancy roadmap (public vs. internal vs. per-individual differentiation)
  - Cross-document entity resolution is not a stated feature; tree navigation is
    document-scoped
  - No free tier — starts at $30/month
  - "Vectorless" means no semantic similarity across documents — subtle cross-references
    ("see the policy mentioned in this newsletter") would not be followed structurally
  - Unclear how inter-document links are resolved
- **Estimated complexity:** Low to integrate, but structurally limited for cross-document
  reasoning, and access control is a blocker.

### Option D: Graphiti (temporal knowledge graph, backed by Neo4j Aura)
- **How it works:** Graphiti (open source, by Zep) ingests documents as *episodes* and
  uses an LLM to extract entities, relationships, and temporal validity windows. Facts
  are stored as graph edges with `valid_from` / `valid_until` metadata. When a newsletter
  says "pickup is 16:00 on 25 March instead of 15:30," Graphiti creates a time-bounded
  override edge, not a new chunk. Querying "what is pickup time tomorrow?" traverses:
  entity(pickup_time) → standard_value + any_override_valid_on(tomorrow) → source
  episode. Every derived fact traces to its source episode = structural citation.
- **Retrieval:** Hybrid — semantic embeddings + BM25 + graph traversal. Sub-second latency.
- **Incremental updates:** New episodes integrate immediately without recomputation. Weekly
  newsletters are just new episodes; the graph handles the override relationship.
- **Backend options:** Neo4j, FalkorDB, Kuzu, Amazon Neptune.
  → **Neo4j Aura Free** (managed, no devops, 50k nodes / 175k relationships free tier)
  is the right choice for this project's ops constraint.
- **Managed service:** Zep Cloud wraps Graphiti with governance and SLAs (SOC2). Free
  tier exists; pricing not publicly detailed. Neo4j Aura Free + self-hosted Graphiti on
  Cloud Run is the cost-controlled alternative.
- **MCP server:** Ships as a Docker container (FalkorDB + MCP server). Addressable via
  HTTP. Tools: add/retrieve/delete episodes, semantic + hybrid search, graph operations.
- **Pros:**
  - Bi-temporal model is structurally correct for the query type. Override relationships
    are explicit graph edges, not inferred by the LLM at query time.
  - Incremental ingestion: weekly newsletters integrate without reindex
  - Entity resolution is a core feature: "pickup time" in policy and "pickup time
    exception" in newsletter resolve to the same entity with an override relationship
  - Every fact has source provenance = citation is structural, not bolted on
  - Cross-document entity resolution handles subtle references by resolving to shared
    entities in the graph
  - Neo4j Aura Free = fully managed graph backend, no devops
- **Cons:**
  - LLM call per ingestion episode (entity extraction) — cost item per new document
  - More complex ingestion pipeline than pure vector search
  - Graphiti's group_id (the access control primitive) enforcement at the API level needs
    verification — not clearly documented as cryptographically enforced
  - Zep Cloud free tier limits are not publicly disclosed — Neo4j Aura + Cloud Run path
    avoids this uncertainty
- **Estimated complexity:** Medium. Ingestion pipeline is more involved. Retrieval query
  is simpler (structured graph traversal vs. chunk reasoning).

## Dead ends

**Pure vector search (Firestore, pgvector, or any chunk-based approach):** Ruled out as
primary mechanism. The fundamental problem is temporal entity resolution across documents,
not similarity ranking. Vector search can be a component (Graphiti uses it internally),
but cannot be the retrieval model. The LLM would need to reason "does this newsletter
chunk override this policy chunk for tomorrow's date?" from unstructured retrieved text —
structurally fragile and untestable.

**Pageindex:** Access control is a hard blocker. No collection/source filtering = cannot
implement `permitted_source_ids` scoping. Also paid-only with no free tier.

**R2R collection permissioning:** Documented as "still under development, API will likely
evolve." Not stable enough to build a multi-tenancy roadmap on.

**Graphiti as MCP server (for access control):** Considered as an architectural option
where the gateway gives Claude direct MCP tools pointing at Graphiti, eliminating the
`knowledge/` REST service. Rejected for MVP because: access control (permitted_source_ids)
enforcement would depend on Claude correctly passing group_id filters to MCP tool calls —
behavioral, not structural. If Claude omits the filter, data leaks. The `knowledge/`
REST wrapper enforces group_id filtering in code, not in prompting. Revisit MCP
architecture after access control is hardened.

**Post-filter on source_id:** Ruled out universally. If retrieval returns results before
filtering, a chunk from a non-permitted source can appear in the LLM's context even if
pruned from the final response. Access control must be enforced before retrieval.

## Decision

**Graphiti with Neo4j Aura Free as the graph backend, Vertex AI text-embedding-004 for
embeddings, and Gemini Flash for graph entity extraction at ingestion time. The
`knowledge/` service remains a REST wrapper — MCP architecture deferred.**

Rationale:
- The query type (temporal override resolution, cross-document entity matching, citation)
  is structurally matched to a temporal knowledge graph. Any chunk-based system pushes
  the hard problem into the LLM prompt — untestable and fragile for a citation-mandatory
  system.
- Neo4j Aura Free = fully managed, no devops, within free tier for MVP scale (tens of
  documents → well under 50k nodes / 175k relationships).
- Gemini Flash (cheapest structured-output model on the GCP stack) for ingestion entity
  extraction — negligible cost for ~50-100 documents with weekly incremental additions.
- Vertex AI text-embedding-004 for the semantic search component inside Graphiti — stays
  on GCP stack, no new vendor.
- The `knowledge/` REST service enforces `permitted_source_ids` → Graphiti `group_id`
  mapping in code. Access control is structural, not behavioral.

## Implementation notes

**Graph backend:**
- Neo4j Aura Free at console.neo4j.io — managed, 50k nodes, 175k relationships, free
- Connect Graphiti via `graphiti-core` with Neo4j driver
- One Neo4j Aura instance per environment (dev/staging/prod each have their own)

**Graphiti source mapping:**
- `group_id` in Graphiti = `source_id` in the knowledge service contract
- Every episode ingested sets `group_id = source_id` of the originating document
- Every retrieval call passes `group_ids = permitted_source_ids` — enforced in the
  knowledge service, never passed through from the caller unchecked

**Embeddings:**
- Model: `text-embedding-004` via Vertex AI
- Graphiti is configured with the Vertex AI embedding provider
- `VERTEX_AI_LOCATION` env var (e.g., `europe-west1` if GDPR becomes relevant later)

**LLM for graph extraction at ingestion:**
- Model: Gemini Flash (supports structured output — required by Graphiti)
- Used only at ingestion time, not at query time
- Cost estimate: ~$0.00015/1K tokens input; a 10KB document ≈ 2500 tokens ≈ $0.0004.
  Ingesting 100 documents ≈ $0.04. Weekly newsletter additions: negligible.
- **Extraction limitation (discovered 2026-03-22):** Edge extraction requires both a
  source AND target entity node. Operational attribute facts ("school starts at 9:00 AM")
  may not be extracted because "school" and "9:00 AM" don't form a named-entity pair.
  Mitigation: pass `custom_extraction_instructions` to `add_episode()` to guide the LLM:
  "Extract temporal and operational facts even when they involve abstract or implicit
  entities (e.g. 'School Day', 'Drop-off Time'). Do not skip facts that lack prominent
  named entities." This does not fully close the gap — table-to-prose preprocessing
  (Sprint 3) and section-level chunking remain necessary.

**Current date injection (CORRECTED — 2026-03-22):**
- `reference_time` is NOT a parameter of `graphiti.search()`. It is only used in
  `add_episode()` to set the validity window of ingested facts.
- Temporal filtering in search requires `SearchFilters(valid_at=[[DateFilter(...)]])`
  passed via the `search_filter` parameter. This is not currently implemented.
- For the current corpus (all facts share `valid_at=2024-09-01`, no `invalid_at`),
  omitting temporal filters has no practical effect. Implement `SearchFilters` when
  newsletter override facts with `invalid_at` are ingested.

**Citation:**
- Graphiti returns facts with source episode references
- The knowledge service maps episode references → `source_id` + document metadata
- The `Chunk.metadata` field carries: `episode_id`, `source_id`, `title`, `url`,
  and `valid_from`/`valid_until` for temporally-bounded facts
- The LLM is instructed to cite by source_id and title — never to state a fact without
  a citation from the retrieved chunk metadata

**Incremental updates:**
- When a document changes, the ingestion service re-ingests the changed episode
- Graphiti's temporal model invalidates the old fact and creates a new one — no
  manual deletion needed for content updates
- When a document is deleted, the ingestion service calls Graphiti's delete episode API
  with the episode's `group_id` = `source_id`

**Access control — `permitted_source_ids` > 30:**
- Graphiti's group_id filter has no documented hard limit (unlike Firestore's `in`
  limit of 30). No batching required.

**Environment variables:**
```
NEO4J_URI               bolt+s://xxxxx.databases.neo4j.io:7687
NEO4J_USER              neo4j
NEO4J_PASSWORD          [secret]
GCP_PROJECT_ID
VERTEX_AI_LOCATION      e.g. us-central1
GOOGLE_APPLICATION_CREDENTIALS   (or Workload Identity on Cloud Run)
WRITE_SECRET            Shared secret for ingestion → knowledge write calls
```

**MCP revisit trigger:**
Revisit the MCP architecture when: (a) Graphiti's group_id enforcement is formally
documented as access-controlled, AND (b) the multi-tenancy model is stable and tested.
At that point, the `knowledge/` REST layer can be replaced by the Graphiti MCP server
and access control enforced via a gateway-side middleware that injects permitted group_ids
as a non-overridable parameter before passing tool calls to the MCP server.
