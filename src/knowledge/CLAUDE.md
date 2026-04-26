# src/knowledge/ — Claude Code context

## Read first
Read `ARCHITECTURE.md` in this directory before making any changes to this service.

## Purpose
Retrieval layer. Given a query and an optional set of permitted source IDs,
returns a cited answer. Called by channel_web (Sprint 1) / gateway (Sprint 2+).

## Retrieval mechanism (migrated from poc1 — 2026-04-22)
- **Engine:** PageIndex — multi-document hierarchical index built offline from cleaned markdown
- **Query pipeline:** Stage 1 routing (doc selection) → Stage 2 node selection per doc → Stage 3 synthesis
- **Models:** `gemini-2.5-flash-lite` (structural/routing) + `gemini-2.5-flash` (selection/synthesis)
- **Index:** built by `tools/build_index.py` from `data/pipeline/latest/02_ai_cleaned/en_*.md`
- **Index location:** `multi_index.json` + per-doc JSONs in the directory pointed to by `KNOWLEDGE_INDEX_PATH`

## Deployment constraint
`--ingress=all --no-allow-unauthenticated` — NOT `--ingress=internal`.
channel_web calls the public `*.run.app` URL; internal ingress blocks it.
Security is enforced by `--no-allow-unauthenticated` + `channel-web-sa` run.invoker binding.

## Interface contract (stable — do not change without updating callers)

```
POST /search
  Request:  { "query": str, "group_ids": list[str] | null }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str, "valid_at": null }] }

GET /health
  Response: { "status": "healthy" }
```

`group_ids`: accepted but ignored — stub for future per-user access control (see TODO.md).
`valid_at`: always `null`.
`facts`: derived from selected index nodes (section title + doc_id). Not structured citations yet — see TODO.md.

## Module map
```
main.py          POST /search, POST /search/stream, GET /health, index loading
indexer/         PageIndex pipeline (originated in poc1 phase, 2026-04)
  config.py      GCP config, model names, node size thresholds
  llm.py         Vertex AI async wrapper, response schemas, semaphore
  multi.py       Multi-doc build + query pipeline (routing → selection → synthesis)
  pageindex.py   Per-doc build pipeline + single-doc query
  node.py        Node dataclass (tree unit)
  parser.py      Markdown → heading tree
  prompts.py     All prompt builder functions
  observability.py  Build logging, cost tracking
```

## Index lifecycle
- Build: run `tools/build_index.py` after corpus update → writes to `data/index/`
- Service reads `KNOWLEDGE_INDEX_PATH` (path to `multi_index.json`) at startup
- Paths in `multi_index.json` are relative to its directory — portable across environments

## Environment variables
```
GCP_PROJECT_ID          img-dev-490919
VERTEX_AI_LOCATION      europe-west1 (default)
KNOWLEDGE_INDEX_PATH    /data/index/multi_index.json (default)
```

## Service account IAM (knowledge-sa@img-dev-490919.iam.gserviceaccount.com)
- `roles/aiplatform.user` — Vertex AI generation calls
- `roles/datastore.user` — retained (harmless); reuse when vector cache is added
- `roles/secretmanager.secretAccessor` — legacy, harmless

## Key invariants
- The service never calls external services except Vertex AI.
- `group_ids` filtering is always applied before generation — not yet enforced (stub).
- Every returned fact carries `source_id` — citation is a hard requirement.
- If index not found at startup: RuntimeError (service fails to start — fail-fast).

## Archived: Vertex AI Context Cache approach
The original implementation cached the full corpus in Vertex AI and sent it with every
query (single LLM call, no index). Archived files:
- `tools/archive/create_cache.py` — cache creation tool with Firestore discovery
- Firestore schema: `config/context_cache` → `{cache_name, created_at, expires_at, source_ids}`
These are the starting point for the future vector-based cache layer (see TODO.md).

## Known issues / pending
See `TODO.md`.
