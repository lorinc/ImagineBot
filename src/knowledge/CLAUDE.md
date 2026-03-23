# src/knowledge/ — Claude Code context

## Purpose
Retrieval layer. Given a query, a current timestamp, and a set of permitted source IDs,
returns relevant context for the LLM with mandatory citation. Called by the gateway.
Written to by the ingestion service.

## Retrieval mechanism (decided — see docs/spikes/retrieval.md)
- **Engine:** Graphiti (temporal knowledge graph — open source, by Zep)
- **Graph backend:** Neo4j Aura Free (managed, no devops, 50k nodes / 175k relationships)
- **Embeddings:** Vertex AI `text-embedding-004`
- **Graph extraction LLM:** Gemini Flash (structured output, used at ingestion time only)
- **Key model:** Facts are graph edges with `valid_from` / `valid_until`. A newsletter
  exception for a specific date is an override edge, not a competing chunk. The query
  "what is the pickup time tomorrow?" traverses: entity → base fact + any override valid
  on tomorrow's date → source episode (= citation).
- **Access control:** `source_id` maps to Graphiti `group_id`. Every retrieval call
  passes `group_ids = permitted_source_ids`. Enforced in this service's code — never
  passed through unchecked from the caller.
- **Current date (CORRECTED 2026-03-22):** `reference_time` is NOT a parameter of
  `graphiti.search()`. It only applies to `add_episode()`. Temporal filtering in search
  requires `SearchFilters` with `DateFilter` objects. Not yet implemented — safe to omit
  while all corpus facts share the same `valid_at` and none have `invalid_at` set.

## Interface contract (stable — do not change without updating the gateway)

```
POST /retrieve
Request:  { "query": str, "permitted_source_ids": list[str], "top_k": int }
Response: { "chunks": list[Chunk], "retrieval_metadata": RetrievalMetadata }

Chunk:
  chunk_id:    str         (Graphiti episode/edge ID)
  source_id:   str         (Graphiti group_id)
  content:     str
  score:       float       (higher = more relevant)
  metadata:    dict        (title, url, episode_id, valid_from, valid_until)

RetrievalMetadata:
  mechanism:   str         ("graphiti-temporal")
  duration_ms: int
  total_candidates: int

POST /write
Request:  { "chunks": list[ChunkInput], "source_id": str }
Response: { "written": int, "skipped": int }
```

Contract tests in `tests/contracts/test_knowledge_contract.py` enforce these shapes.

## Module map
```
main.py
routers/
  retrieve.py     POST /retrieve — injects reference_time, enforces group_id filter
  write.py        POST /write — ingests episodes into Graphiti with group_id=source_id
  health.py       GET /health
models/
  chunk.py        Chunk, ChunkInput, RetrievalMetadata — field contracts
services/
  retrieval_service.py    query embed → Graphiti search(group_ids, reference_time)
  write_service.py        episode ingest → Graphiti add_episode(group_id=source_id)
config.py
```

## Graphiti API facts (verified against graphiti-core==0.28.2)
- `search(query, group_ids, num_results)` returns `list[EntityEdge]` — RELATES_TO edges
  only. Hybrid BM25 + semantic, RRF reranked. This is the correct method for fact retrieval.
- `reference_time` is an `add_episode()` parameter, NOT a `search()` parameter.
- `add_episode()` accepts `custom_extraction_instructions: str` — use this to improve
  extraction of operational/attribute facts from policy documents.
- Edge extraction requires both source AND target entity nodes. Facts like "school starts
  at 9:00 AM" may not be extracted unless the LLM is guided via custom_extraction_instructions
  to treat abstract concepts ("School Day", "Drop-off Time") as entities.
- Entire document body passed as single episode is the intended usage — no internal chunking.

## Key invariants
- `permitted_source_ids` → Graphiti `group_id` filter applied before every search.
  A fact from a non-permitted source must never appear in the response.
- The `/write` endpoint is only callable from the ingestion service.
  Enforced via `WRITE_SECRET` bearer token checked in the write router.
- `reference_time = now()` is always injected by this service. The caller never sets it.
- Every returned chunk must carry `source_id` and `episode_id` in metadata — citation
  is a hard requirement, not optional.
- Every call logs: query (truncated 200 chars), source_ids count, top_k, reference_time,
  duration_ms, chunks returned, min/max score.

## Environment variables
```
NEO4J_URI               bolt+s://xxxxx.databases.neo4j.io:7687
NEO4J_USER              neo4j
NEO4J_PASSWORD          [secret]
GCP_PROJECT_ID
VERTEX_AI_LOCATION      e.g. us-central1
WRITE_SECRET            Shared secret for ingestion → knowledge write calls
```

## MCP architecture (deferred)
Graphiti ships an MCP server. Considered replacing this REST service with the Graphiti
MCP server and having the gateway give Claude direct MCP tools. Deferred: access control
enforcement would be behavioral (Claude passes group_ids) not structural (code enforces
group_ids). Revisit when: (a) Graphiti group_id enforcement is formally documented as
access-controlled, AND (b) multi-tenancy model is stable and tested.

## Known issues
None — spike complete. See docs/spikes/retrieval.md for full decision record.
