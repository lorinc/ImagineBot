# src/ingestion/ — Claude Code context

## Read first
Read `ARCHITECTURE.md` in this directory before making any changes to this service.

## Purpose
Convert school documents from Google Drive into a PageIndex that the knowledge service
can query. Runs on demand — not on the user request path. Currently a local CLI pipeline;
needs to become a deployed service for multi-tenant operation.

## Current state
A 5-step CLI pipeline run manually from a developer's machine. Drive is the authoritative
source. Processed output lands in `data/pipeline/` (gitignored local filesystem). The
knowledge service index is built separately by `tools/build_index.py`.

**This is a production gap:** if the developer's machine is lost, the processed corpus
must be regenerated from scratch. Drive OAuth credentials are personal, not a service
identity. There is no scheduling, no change detection, no audit trail.

## Pipeline steps

```
Google Drive: 0-docx-sources/
    ↓ Step 1 — DOCX → native Google Docs (Drive API, OAuth)
Google Drive: 1-native-gdocs/
    ↓ Step 2 — Google Docs → baseline Markdown (Docs export API)
data/pipeline/<run_id>/01_baseline_md/
    ↓ Step 3 — AI header cleanup (Gemini Flash Lite)
      Fixes header hierarchy using font-size metadata from Step 2.
      PRESERVES tables — does NOT convert them (that is Step 4).
data/pipeline/<run_id>/02_ai_cleaned/
    ↓ Step 4 — Table-to-prose conversion
      Converts markdown tables to narrative sentences.
      WHY: tables produce no structured facts in LLM extraction.
           Validated: timetable table → 0 facts; prose → extracted correctly.
      Overwrites 02_ai_cleaned/<stem>.md in-place AND writes a copy to
      03_chunked/<stem>_prose.md for step5_chunk.py.
data/pipeline/<run_id>/02_ai_cleaned/  ← also updated in-place by Step 4
data/pipeline/<run_id>/03_chunked/
    ↓ Step 5 — Semantic chunking (split by ## headers)
      Each ## section becomes one chunk file.
data/pipeline/<run_id>/03_chunked/
    ↓ [Index build — separate tool]
      tools/build_index.py reads data/pipeline/latest/02_ai_cleaned/en_*.md
      (prose-converted by Step 4) and writes the PageIndex to data/index/multi_index.json
```

### What Step 6 (Graphiti/Neo4j) was
Step 6 ingested chunks into a Neo4j knowledge graph via Graphiti. This approach was
abandoned in favour of PageIndex (full-context retrieval). The file was deleted 2026-04-26.

## Running the pipeline
```bash
# Full run (Steps 1–5):
python3 -m src.ingestion.pipeline.run --all

# Skip Drive upload, re-use existing Google Docs:
python3 -m src.ingestion.pipeline.run --from-step2

# Individual steps:
python3 -m src.ingestion.pipeline.run --step3
python3 -m src.ingestion.pipeline.run --step4
python3 -m src.ingestion.pipeline.run --step5

# Then build the index:
python3 tools/build_index.py
```

## Authentication
Steps 1–2 require Google Drive/Docs OAuth (personal account credentials — `token.json`).
Steps 3–5 require Vertex AI (Application Default Credentials).

Production path: Domain-Wide Delegation impersonating a service account identity, not
a personal OAuth token. Do not implement until the ingestion service is deployed.

## Local data layout
```
data/pipeline/
  <run_id>/           e.g. 2026-04-23_001
    01_baseline_md/   Step 2 output
    02_ai_cleaned/    Step 3 output (source for index build)
    03_chunked/       Steps 4+5 output
    manifest.json     Per-file state: step, chunk_count, ingested_at
  latest/             Symlink to most recent run_id
data/index/
  multi_index.json    PageIndex built from latest/02_ai_cleaned/en_*.md
  en_*.json           Per-document index files
```

`data/` is gitignored. Test fixtures live in `tests/fixtures/pipeline/` (committed).

## Idempotency
Steps 1–5 overwrite output files if re-run. `manifest.json` tracks current state per file;
do not use it as a history log.

## Key invariants
- Tables must be converted to prose BEFORE index build (Step 4 before `build_index.py`)
- `group_id` per document must equal `source_id` — never null, never shared across docs
- Drive is the authoritative source; `data/` is a local processing scratch space
- Steps 1–2 require personal OAuth; steps 3–5 require only ADC

## Future: deployed service
For multi-tenant operation, ingestion must become a deployed Cloud Run service or job:
- Drive webhook receiver: detect document changes without polling
- Per-tenant corpus management: each tenant has its own Drive folder and index
- Index lifecycle: versioned index builds, atomic cutover, no outage on rebuild
- Audit trail: log when corpus was last refreshed, from what document state
- Service identity: Domain-Wide Delegation, not personal OAuth tokens
- No laptop dependency: corpus and index live in GCS or Firestore, not local disk

See `docs/design/mature-infra-analysis.md` §3 for the full gap analysis.
