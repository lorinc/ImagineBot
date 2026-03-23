# src/knowledge/ — Claude Code context

## Purpose
Retrieval layer. Given a query and an optional set of permitted source IDs,
returns a cited answer. Called by channel_web (Sprint 1) / gateway (Sprint 2+).

## Retrieval mechanism (decided 2026-03-23 — see ARCHITECTURE_PIVOT in root CLAUDE.md)
- **Engine:** Vertex AI Context Caching + Gemini 2.5 Flash (full-context, not RAG)
- **Why:** ~100K token corpus fits in a single cache; full-context beats RAG at this scale;
  500 queries/day max; citations returned as structured JSON via response_schema
- **Cache:** Created by `tools/create_cache.py` from `data/pipeline/latest/02_ai_cleaned/en_*.md`
- **Cache name:** persisted in Firestore `config/context_cache.cache_name`
- **Access filtering:** `group_ids` appended to query as instruction ("Answer only from: X, Y")

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

`valid_at` is always `null` — no temporal model in context caching.

## Module map
```
main.py          POST /search, GET /health, Firestore cache-name lookup
```

## Cache lifecycle
- Cache name cached in process memory for 5 minutes (`_CACHE_REFRESH_SECS = 300`)
- Firestore doc `config/context_cache` is the authoritative source of truth
- To refresh corpus: run `tools/create_cache.py` (deletes old cache, creates new, updates Firestore)
- Cache TTL: 48h by default (configurable via `--ttl-hours` flag)
- Service reads `cache_name` from Firestore on startup and after TTL expiry

## Environment variables
```
GCP_PROJECT_ID          img-dev-490919
VERTEX_AI_LOCATION      europe-west1 (default)
```

## Service account IAM (knowledge-sa@img-dev-490919.iam.gserviceaccount.com)
- `roles/aiplatform.user` — Vertex AI context cache + generation calls
- `roles/datastore.user` — Firestore cache name lookup
- `roles/secretmanager.secretAccessor` — (legacy from Sprint 1, harmless)

## Key invariants
- The service never calls external services except Vertex AI and Firestore.
- `group_ids` filtering is always applied before generation — never skipped.
- Every returned fact carries `source_id` — citation is a hard requirement.
- If no cache exists in Firestore: returns HTTP 503 ("Run tools/create_cache.py first.")

## Known issues / pending
- Spanish corpus not in cache (en_*.md only). System prompt multilingual answer
  is the planned approach — implement before next corpus update.
