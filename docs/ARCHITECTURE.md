# Architecture

## GCP project structure

**Decision: 2 projects, not 4.**

```
img-dev   — all services, development + staging environment
img-prod  — all services, production environment
```

Rejected: one project per service (ingestion / knowledge / llm / channel_web).

**Why rejected:**
- Cross-project service-to-service calls require cross-project IAM + networking — significantly more complex than same-project IAM roles
- Workload Identity Federation must be set up once per project — 4 projects = 4x CI/CD setup
- Shared resources (Firestore, Secret Manager, Neo4j credentials) have no natural home across projects
- Firestore: one instance per project — cannot split across projects without a cross-project API boundary
- Service isolation at MVP scale is fully achievable via per-service service accounts within one project

**Service isolation within a project (not via project boundaries):**
- One Cloud Run service per `src/` service
- One service account per Cloud Run service, minimum permissions
  - e.g., `ingestion-sa@img-dev.iam.gserviceaccount.com` — only: Neo4j write, GCS read, Vertex AI
  - e.g., `knowledge-sa@img-dev.iam.gserviceaccount.com` — only: Neo4j read, Vertex AI
  - e.g., `gateway-sa@img-dev.iam.gserviceaccount.com` — only: Cloud Run invoker on downstream services
- Services call each other via HTTPS (Cloud Run URL), not shared databases
- Billing attribution via resource labels, not project splits

**Reference:** `REFERENCE_REPOS/MD2RAG/ISSUE-GEMINI-AUTH.md` — the prior project's pain was Gemini API key vs Vertex AI service account confusion, not project structure. Avoided here by using Vertex AI consistently (never the public Gemini API key endpoint).

---

## Per-project resources

Each project (`img-dev`, `img-prod`) contains:

| Resource | Purpose |
|---|---|
| Cloud Run (per service) | Each `src/` service runs as a Cloud Run service |
| Cloud Run Jobs (ingestion) | Ingestion runs on schedule/webhook, not always-on |
| Firestore | User data, access control mapping, session state |
| Secret Manager | Neo4j credentials, API keys — never in code or env files |
| Artifact Registry | Docker images for all services |
| Cloud Storage | Markdown staging bucket (Drive → GCS → ingestion) |
| Vertex AI | Embeddings (text-embedding-004) + LLM calls at ingestion (Gemini Flash) |
| Workload Identity Federation | CI/CD auth — one pool per project, no stored keys |

**Not in GCP:**
- Neo4j Aura Free — managed by Neo4j (one instance per environment, `console.neo4j.io`)

---

## Service deployment model

```
src/gateway/      → Cloud Run service  (always on, public HTTPS)
src/ingestion/    → Cloud Run Job      (scheduled or webhook-triggered, not on request path)
src/knowledge/    → Cloud Run service  (internal only — not public)
src/security/     → Cloud Run service  (internal only)
src/auth/         → Cloud Run service  (internal only)
src/access/       → Cloud Run service  (internal only)
src/channel_web/  → Cloud Run service  (public HTTPS)
```

Internal services are only reachable by other services with the Cloud Run Invoker role — not exposed to the public internet.

---

## Knowledge service: retrieval architecture

**Retrieval backend: Vertex AI Context Caching (Gemini 2.5 Flash)**

Decision: 2026-03-23. Graphiti + Neo4j retired. See heuristics.log for rationale.

```
Markdown files (data/pipeline/latest/02_ai_cleaned/ — 7 canonical files, ~100K tokens)
    ↓ ingestion service: Steps 1–4 (DOCX → GDocs → baseline MD → AI cleaned → table-to-prose)
    ↓ knowledge service: create/refresh Vertex AI Context Cache on corpus update
Vertex AI Context Cache (Gemini 2.5 Flash, full corpus, ~100K tokens, TTL managed)
    ↑ knowledge service (Cloud Run)
    ↑ Gemini 2.5 Flash: full-context generation, cached_content passed per request
```

**Why full-context beats RAG for this corpus:**
The entire corpus fits in ~10% of Gemini 2.5 Flash's 1M context window.
No retrieval step = no retrieval errors, no chunking artefacts, no graph construction failures.
Matches how NotebookLM works.

**Access control with full-context:**
group_id filtering via Graphiti is eliminated. Per-user source filtering (Sprint 2) is implemented
as prompt-level instruction: "Answer only from these documents: X, Y, Z." For a corpus of 7 docs
and a small user base, prompt-level filtering is sufficient and avoids the cost of per-group caches.

**Citation model:**
Gemini is instructed to return structured JSON via Vertex AI `response_schema`:
```json
{ "answer": str, "citations": [{ "document": str, "excerpt": str }] }
```
`document` is the canonical source_id (e.g. `en_policy1_child_protection`).
`excerpt` is the verbatim sentence(s) Gemini drew from — quote-level, not edge-level.
Knowledge service maps this to the existing `facts` shape channel_web already renders:
`{ answer: str, facts: [{ fact: str, source_id: str }] }` — `fact` = excerpt, `source_id` = document.
No UI changes required.

**Cache lifecycle:**
- Cache created/refreshed by the knowledge service at startup if no valid cache exists.
- TTL: set to cover expected idle periods (minimum 1 hour, extend as needed).
- Corpus update triggers cache invalidation + recreation (delete old cache, create new).
- Cache ID stored in Firestore (or env var for Sprint 2) so all instances share one cache.

**Ingestion pipeline (simplified — Steps 1–4 only, no chunking, no Graphiti):**
```
Step 1: DOCX → Google Docs (Drive API, OAuth)
Step 2: Google Docs → baseline MD (Docs export)
Step 3: AI header cleanup (Gemini Flash Lite) — preserves tables
Step 4: table_to_prose (src/ingestion/table_to_prose.py)
→ Output: data/pipeline/latest/02_ai_cleaned/<source_id>.md (7 canonical files)
→ Trigger: knowledge service cache refresh
```
Step 5 (semantic chunking) and Step 6 (Graphiti ingestion) are removed.

---

## Ingestion pipeline: local data layout

DOCX source files are **not stored in the repo**. Google Drive is the authoritative source.
`data/` is gitignored entirely.

**Staged directory layout — one subfolder per pipeline run:**

```
data/
  pipeline/
    2026-03-22_001/         ← run ID: YYYY-MM-DD_NNN (sortable, human-readable)
      00_docx/              ← downloaded from Drive (source, untouched)
      01_baseline_md/       ← after DOCX→GDocs→MD export
      02_ai_cleaned/        ← after Gemini Flash Lite AI cleanup
      03_chunked/           ← after section splitting + table-to-prose
      04_ingested/          ← marker files (e.g. family-manual.done) after Graphiti
      manifest.json         ← per-file state: step, chunk count, edge count, ingested_at
    2026-03-22_002/         ← re-run after fixing a step — previous run preserved
    latest -> 2026-03-22_001/  ← symlink updated by pipeline; downstream code uses this
```

**Why run ID subfolders (not file prefixes):**
- Each step is independently inspectable: `ls 03_chunked/` shows one run's files cleanly
- Cross-run diffing: `diff 001/02_ai_cleaned/ 002/02_ai_cleaned/` shows exactly what changed
- Deleting a run: `rm -rf 2026-03-22_001/` — no grep-and-delete across mixed files
- `latest/` symlink decouples downstream code from run IDs

**Manifest schema (`manifest.json`):**
```json
{
  "family-manual.docx": {
    "step": "ingested",
    "chunks": 14,
    "edges": 28,
    "ingested_at": "2026-03-22T10:00Z"
  }
}
```

**Pipeline idempotency:** Presence of `04_ingested/<name>.done` skips re-ingestion.
Re-ingest by deleting the marker file and re-running.

**Test fixtures:** A small representative doc lives in `tests/fixtures/pipeline/` (committed).
Full corpus never goes in git.

---

## Sprint 1 — simplified architecture (POC, no gateway)

```
Browser → channel_web (Cloud Run, --allow-unauthenticated)
        → knowledge service (Cloud Run, --no-allow-unauthenticated, ingress=all TEMPORARILY)
        → Neo4j Aura Free (external)        ← BEING REPLACED in Sprint 2
        → OpenAI gpt-4o-mini (external)     ← BEING REPLACED in Sprint 2
```

**Sprint 2 replaces the knowledge service backend:**
Graphiti + Neo4j + OpenAI → Vertex AI Context Caching + Gemini 2.5 Flash.
API contract (`POST /search` → `{ answer, facts }`) is preserved — no channel_web changes.

**Deliberate omissions vs target architecture:**
- No gateway — channel_web calls knowledge service directly via identity token
- No auth service — Google Sign-In in browser + ID token validation in channel_web (Phase 1.4)
- No access service — group_ids=null (all users see all sources)
- No security service — no rate limiting or input screening
- No CI/CD — manual deploy scripts only (`src/*/deploy.sh`)

**TODO before Sprint 2:** restore knowledge service `--ingress=internal`
(currently `all` for development access — change after channel_web E2E validated).

---

## Iteration 1 — local validation (pre-GCP)

Before provisioning any GCP resources, validate Graphiti works against the actual corpus:

**Input:** `REFERENCE_REPOS/MD2RAG/markdowns/` — 6 policy/manual markdown files, already processed and extraction-ready.

**Goal:** Confirm Graphiti correctly:
1. Ingests the markdown files as episodes
2. Extracts entities and temporal relationships
3. Returns cited answers to representative queries

**Acceptance (observable):** Running `python validate.py` produces a cited answer for at least one temporal query (e.g. policy + exception pattern) without hallucination, with source episode reference.

**Stack for local validation:**
- `graphiti-core` Python package
- Neo4j Aura Free instance (dev) — provisioned manually before the session
- Gemini Flash via Vertex AI OR OpenAI (decision: confirm with user before session)
- `text-embedding-004` via Vertex AI OR OpenAI embeddings (same decision)
- Local Python script only — no FastAPI, no Cloud Run

**Outcome of validation determines:**
- Whether Graphiti's entity extraction actually resolves cross-document references in this corpus
- Whether the `group_id` filtering works as documented
- Whether temporal edges are created for date-bounded facts in newsletter-style text
- Any ingestion cost surprises

**If validation fails:** Write findings to `.claude/HEURISTICS.log`, reassess retrieval mechanism in a new spike.

---

## LLM provider decision: pending user confirmation

The retrieval spike specified Vertex AI (Gemini Flash) for entity extraction. For local validation:

- **Option A:** Vertex AI (Gemini Flash + text-embedding-004) — matches production config, requires GCP project + service account setup before validation
- **Option B:** OpenAI (gpt-4o-mini + text-embedding-3-small) — faster to start locally, replaced by Vertex AI before any deployment

This decision is required at the start of the local validation session.
