# [PROJECT NAME] — Claude Code root context

## What this is
[2-3 sentences. What the product does, what problem it solves, who uses it.]
This is a multi-service knowledge system: documents are ingested and kept current,
a knowledge layer serves answers to an LLM, and users interact through channels
(web UI first, WhatsApp later) with access controlled per user per data source.

## Stack
- **Language/Runtime:** Python 3.12
- **Framework:** FastAPI (all services)
- **Database:** Firestore (primary), Neo4j Aura Free (knowledge graph — Graphiti)
- **Knowledge graph:** Graphiti (`graphiti-core`) — temporal entity extraction + hybrid retrieval
- **Embeddings:** Vertex AI `text-embedding-004`
- **LLM (ingestion):** Gemini Flash via Vertex AI (entity extraction only, not query path)
- **Auth:** [TBD — see SPIKE: auth]
- **Frontend:** Jinja2 SSR + [Tailwind or Bootstrap — decision pending]
- **Infra:** GCP — 2 projects: `img-dev` (staging) and `img-prod` (production)
           Cloud Run per service, Firestore, Secret Manager, Artifact Registry, Vertex AI
           Neo4j Aura Free: one instance per environment (external managed service)
- **CI/CD:** GitHub Actions + Workload Identity Federation (one pool per project, no stored keys)

## Service map
```
src/
  gateway/        API gateway. Single entry point for all channels.
                  Channels are thin clients — they call this, nothing else.
                  Routes requests after auth + access checks pass.

  ingestion/      Document intake and freshness. Watches sources, processes
                  changes, writes to the knowledge store. Runs on schedule
                  or webhook trigger, not on user request path.

  knowledge/      Retrieval layer. Given a query + permitted source IDs,
                  returns relevant context for the LLM.
                  Graphiti + Neo4j Aura Free. Spike complete — see docs/spikes/retrieval.md.
                  Enforces group_id = source_id filtering in code before retrieval.

  security/       Rate limiting, abuse detection, malicious input screening.
                  Sits before the LLM call. Stateless where possible.

  auth/           Authentication. Issues and validates tokens.
                  [Design TBD — see SPIKE: auth]

  access/         User-to-data-source mapping. Given a user ID, returns
                  the set of source IDs they may query.
                  [Design TBD — see SPIKE: access control]

  channel_web/    Web UI channel. Jinja2 SSR. Thin client: formats requests
                  for the gateway, renders responses. No business logic here.
```

## Request flow (current understanding)
```
User → channel_web → gateway → [auth] → [access: get permitted sources]
     → [security: rate limit + screen] → [knowledge: retrieve context]
     → LLM call → response → channel_web → User
```
This flow is an assumption. Validate it in the architecture spike before building services.

## Active work
```
CURRENT_SPRINT:  1 — Chatbot POC (2-day sprint)
CURRENT_PHASE:   Sprint 1 COMPLETE — pending browser UAT
LAST_STABLE:     [set after first commit]
PHASE_1.1_DONE:  GCP Foundation complete (2026-03-21)
  - img-dev-490919: APIs enabled, Artifact Registry, service accounts, IAM, secrets
  - Secrets in Secret Manager: OPENAI_API_KEY (v2 full key), NEO4J_URI, NEO4J_PASSWORD, ALLOWED_EMAILS
  - OAuth client ID: in credentials file (OAUTH_CLIENT_ID key)
  - Test users: mariano@imaginemontessori.es, sandra@imaginemontessori.es, lorinc@gmail.com
  - Docker installed (v29.3.0), docker group configured
PHASE_1.2_DONE:  Knowledge Service complete (2026-03-21)
  - Deployed: https://knowledge-jeyczovqfa-ew.a.run.app (revision knowledge-00002-cdt)
  - Ingress: TEMPORARILY all — restore to internal after channel_web E2E (TODO E0)
  - Auth: --no-allow-unauthenticated
  - Secrets: volume-mounted, one unique parent dir per secret (Cloud Run constraint)
  - Tests: 5/5 passing
PHASE_1.3_DONE:  Channel Web complete (2026-03-21)
  - Deployed: https://channel-web-jeyczovqfa-ew.a.run.app (revision channel-web-00004-6gz)
  - UI: pixel-perfect Vercel demo replica (vanilla HTML/CSS/JS, hand-written CSS)
  - Questions/categories: src/channel_web/static/questions.json — edit without code changes
  - Source citations: <details> showing fact text + source_id per fact
  - Language toggle: EN/ES, cookie-persisted
  - Tests: 9/9 passing
  - IAM: channel-web-sa granted run.invoker on knowledge service ✅
PHASE_1.4_DONE:  Google Sign-In auth complete (2026-03-21)
  - Google Sign-In (GIS) on frontend — login overlay until authenticated
  - Backend: google.oauth2.id_token.verify_oauth2_token + ALLOWED_EMAILS gate on /chat
  - ALLOWED_EMAILS from /secrets/allowed_emails/ALLOWED_EMAILS (Secret Manager volume mount)
  - GOOGLE_CLIENT_ID passed as env var (from credentials file OAUTH_CLIENT_ID key)
  - Fixed CHAT-ERR: missing requests package — google.auth.transport.requests requires it
  - Tests: 9/9 passing
  - Auth acceptance: curl POST /chat (no token) → 401 ✅
  - PENDING: browser UAT — sign in with permitted account, ask a question, see cited answer
CLOUD_RUN_SECRET_MOUNT_RULE: Each secret needs a unique parent directory.
  /secrets/foo/BAR=BAR:latest → file at /secrets/foo/BAR. Never share parent dirs.
CREDENTIALS_FILE_RULE: Always parse credentials file with _load_creds_file() from
  validate.py. Never use grep/cut — the file uses continuation lines for long values.
STATIC_ASSET_RULE: Never use url_for() in Jinja2 templates for static asset paths.
  Use root-relative paths (/static/style.css). url_for() generates http:// absolute URLs
  which are blocked as mixed content on HTTPS Cloud Run deployments.
GOOGLE_AUTH_TRANSPORT_RULE: Always add `requests` to requirements.txt alongside `google-auth`.
  google.auth.transport.requests.Request() is used by both fetch_id_token() and
  verify_oauth2_token(). google-auth does NOT install requests automatically.
SPIKES_PENDING:
  - auth design (auth service)
  - access control design (access service)
SPIKES_COMPLETE:
  - retrieval mechanism (knowledge service) — Graphiti + Neo4j Aura Free, see docs/spikes/retrieval.md
  - local validation — validate.py passed against Neo4j Aura Free (corpus ingested, queries working)
    OpenAI selected as LLM for Sprint 1 (replace with Vertex AI before production)
    Stub saved: src/ingestion/validate_graphiti.py
  - frontend CSS framework — hand-written CSS chosen (no framework, no build step, no CDN dependency)
DECISIONS_COMPLETE:
  - GCP project structure — 2 projects (img-dev, img-prod), not per-service. See docs/ARCHITECTURE.md.
  - Sprint 1 architecture — knowledge (internal Cloud Run) + channel_web (*.run.app, no LB/IAP)
    No gateway, no auth service, no access control, no CI/CD in Sprint 1. See docs/PROJECT_PLAN.md.
  - Sprint 1 auth — Google Sign-In (frontend) + ID token validation (backend), allowed-email list
SPRINT_1_TODO_BEFORE_SPRINT_2:
  - E0: Browser UAT — open https://channel-web-jeyczovqfa-ew.a.run.app in incognito, sign in, ask a question
  - E1: After UAT passes — restore knowledge service ingress to --ingress=internal
CORPUS_STATE:
  - 149 RELATES_TO edges across 6 documents (health-safety:40, family-manual:28, child-protection:23, technology-policy:22, trips-outings:21, code-of-conduct:15)
  - family-manual has ONLY staff name/role facts — no hours, no contact, no policies
  - Root cause: each doc ingested as single episode; Graphiti extraction fixated on staff directory
  - Fix: re-ingest with section-level chunking (split by ## headers) + table-to-prose preprocessing
PIPELINE_DECISIONS (2026-03-22):
  - Local DOCX files: data/docx/ (7 files, renamed to en_policy[N]_*, es_family_manual_*, en_family_manual_*)
  - Pipeline output: local filesystem, staged dirs data/pipeline/<YYYY-MM-DD_NNN>/ (gitignored)
    See docs/ARCHITECTURE.md "Ingestion pipeline: local data layout" for full layout + rationale
  - table_to_prose: IMPLEMENTED — src/ingestion/table_to_prose.py, 19 tests passing
    Inheritance rule: inherit empty cells only when first column is also empty (continuation row)
    See heuristics.log 2026-03-22 for why this heuristic is non-obvious and what it prevents
  - Professional Drive auth: service account + DWD (impersonate ingestion-bot@imaginemontessori.es)
    Dev: OAuth token.json acceptable. Production: DWD required. See TODO.md A1.
ARCHITECTURE_PIVOT (2026-03-23):
  - Graphiti + Neo4j + OpenAI REPLACED by Vertex AI Context Caching + Gemini 2.5 Flash
  - Rationale: ~100K token corpus fits in one cache; full-context > RAG for this corpus size;
    500 queries/day max; citations returned as structured JSON via response_schema
  - API contract unchanged: POST /search → { answer, facts: [{ fact, source_id, valid_at }] }
  - Ingestion pipeline simplified: Steps 1–4 only (no chunking, no Graphiti)
  - See docs/ARCHITECTURE.md "Knowledge service: retrieval architecture" for full design
  - See docs/PROJECT_PLAN.md Sprint 2 Phase 2.1 for implementation spec

NEXT_SESSION — KNOWLEDGE SERVICE REBUILD (Sprint 2 Phase 2.1):
  - FIRST: browser UAT (Sprint 1 E0) — confirm current deployment works before touching anything
  - THEN: restore knowledge service --ingress=internal (Sprint 1 E1)
  - THEN: rebuild src/knowledge/ per docs/PROJECT_PLAN.md Sprint 2 Phase 2.1
  - Canonical file set: en_/es_ prefixed files only from data/pipeline/latest/02_ai_cleaned/
  - Cache ID persisted in Firestore config/context_cache
  - IAM: add roles/aiplatform.user to knowledge-sa before deploy
```

Update this block at the end of every session.

## Session protocol
Before starting work, create `SESSION.md` in repo root (gitignored).

```
PHASE: [PLAN|EXPLORE|IMPLEMENT|VERIFY|DOCUMENT]
TASK: [one sentence — what specifically is being done this session]
SERVICE: [which service directory, or "cross-cutting"]
ROLLBACK_TO: [git commit hash or "clean — nothing committed yet"]
ATTEMPT: [n] of 3
ACCEPTANCE: [measurable, observable — not "implementation complete"]
IN_SCOPE: [explicit file list — if it's not here, don't touch it]
CONTEXT_PCT: [check /cost — note token usage at each SESSION.md update]
HEURISTICS_WRITTEN: [yes|no]
```

Rules:
- At attempt 3, or if task is not converging: STOP.
  Write findings to heuristics.log. Declare "needs fresh session." No 4th attempt.
- At attempt 2: run `/compact` before continuing. Note context % in SESSION.md.
- ACCEPTANCE must be observable without trusting my own report.
  "Staging URL returns correct JSON shape" beats "implementation complete."
- If a file is not in IN_SCOPE, do not touch it. Ask first.
- Spikes are EXPLORE phase only. No commits during EXPLORE.

## Spike protocol
For any SPIKE_PENDING item:
1. Open SESSION.md with PHASE: EXPLORE
2. Read existing code and docs. Do not write production code.
3. Write findings to `docs/spikes/[topic].md` — options, tradeoffs, recommendation
4. Write a heuristics.log entry for any dead ends discovered
5. Declare spike complete. New session for implementation.

## Heuristics log format
File: `heuristics.log` — append only, never edit past entries.

```
[YYYY-MM-DD HH:MM]
CATEGORY: CONTRACT_VIOLATION | ENV_PARITY | TRANSACTION_BUG | PATH_BUG | UI_BUG | AUTH_BUG | CONFIG_BUG | RETRIEVAL_BUG | ACCESS_BUG | OTHER
SERVICE: [which service]
TASK: [what was being built]
SYMPTOM: [what the user or logs reported]
ROOT_CAUSE: [actual cause]
PREVENTED_BY: [structural change that would have caught this automatically]
SOLUTION: [what fixed it]
DEAD_ENDS: [what didn't work and why]
```

`PREVENTED_BY` is the most important field. It drives hook and contract additions.

## Dependency policy
This project is deliberately conservative on dependencies.
Before adding any package:
1. State what problem it solves
2. State what the alternative without it would be
3. Get explicit approval

Never add a package to solve a problem that three lines of Python would solve.
Never add a Node.js toolchain dependency. Frontend must be serveable without a build step.

## External enforcement checklist
Must be complete before sprint 1 feature development begins.

- [ ] CI runs on every push (lint → contracts → unit → integration)
- [ ] CI blocks merge on failure (branch protection on main)
- [ ] Integration tests run against Firestore emulator in CI
- [ ] Staging deploy is automatic on merge to main
- [ ] Staging smoke tests run after deploy, open GitHub issue on failure
- [ ] Production deploy is manual trigger only
- [ ] Secrets in environment variables only — never in code
- [ ] `SESSION.md` is in `.gitignore`
- [ ] `.claude/settings.local.json` is in `.gitignore`
- [ ] Contract tests exist for every field the gateway exposes

## What I don't know yet (clear when read)
- [ ] Full contents of each service directory (load per-service CLAUDE.md when working there)
- [ ] Spike outcomes for: auth, access control, CSS framework
- [x] Spike outcome: retrieval — Graphiti + Neo4j Aura Free (docs/spikes/retrieval.md)
- [x] GCP project structure — 2 projects, service accounts for isolation (docs/ARCHITECTURE.md)

Load the CLAUDE.md in the service directory you're working in before making changes.
