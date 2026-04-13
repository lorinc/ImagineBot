# Project Plan
# Update when: a phase completes or is added, a sprint boundary is crossed, a spike resolves.
# Does not record bug fixes or session details — those go in .claude/HEURISTICS.log.
# Current session state lives in .claude/SESSION.md, not here.

## Sprint Overview

| Sprint | Duration | Focus | Status |
|--------|----------|-------|--------|
| Sprint 1 | 2 days | Chatbot POC — Graphiti RAG, Google Sign-In auth | ✅ Complete (pending browser UAT) |
| Sprint 2 | TBD | Knowledge service rebuild (Context Caching), gateway, auth service, access control | 📋 Planned |
| Sprint 3 | TBD | Ingestion pipeline (DOCX2MD → Steps 1–4 → cache refresh), staged data layout | 📋 Planned |
| Sprint 4 | TBD | Production hardening, CI/CD, monitoring | 📋 Planned |

---

## Sprint 1 — Chatbot POC (2 days)

**Goal:** Three Google Workspace users can open a URL in a browser, log in with Google,
and ask questions answered from the school document corpus via Graphiti RAG.

**What is deliberately NOT built in this sprint:**
- No gateway service (channel_web calls knowledge service directly)
- No auth service, no access service, no security service
- No per-user source filtering (all users see all sources, group_ids=null)
- No ingestion pipeline (corpus already ingested by validate.py)
- No CI/CD (manual deploy scripts only)
- No production project (img-dev only)

**LLM note:** OpenAI gpt-4o-mini used for answer synthesis. Replace with Vertex AI
(Gemini Flash) before any production deployment.

---

### Phase 1.1 — GCP Foundation
**When:** Day 1, first ~3 hours
**Type:** Manual setup — no code, only gcloud commands

**Prerequisite (blocker):** A domain or subdomain you control is required for the HTTPS
Load Balancer. Cloud IAP requires HTTPS. Google-managed SSL certificates require DNS
validation. Confirm this before starting the sprint.

**Deliverables:**
- img-dev project created and linked to billing account
- APIs enabled: `run.googleapis.com`, `artifactregistry.googleapis.com`,
  `iap.googleapis.com`, `secretmanager.googleapis.com`, `compute.googleapis.com`
- Artifact Registry repo: `europe-west1-docker.pkg.dev/img-dev/services`
- Service accounts created:
  - `knowledge-sa@img-dev.iam.gserviceaccount.com`
  - `channel-web-sa@img-dev.iam.gserviceaccount.com`
- IAM roles assigned:
  - `knowledge-sa`: `roles/secretmanager.secretAccessor`
  - `channel-web-sa`: `roles/secretmanager.secretAccessor`
  - `channel-web-sa`: `roles/run.invoker` on knowledge service (granted after 1.2 deploys)
- Secrets stored in Secret Manager: `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_PASSWORD`
- Static IP reserved: `channel-web-ip` (global)
- OAuth consent screen configured (Internal — Google Workspace only)
- Docker configured locally: `gcloud auth configure-docker europe-west1-docker.pkg.dev`

**Acceptance (observable):**
- `gcloud secrets list --project=img-dev` returns 3 secrets
- `gcloud iam service-accounts list --project=img-dev` shows both service accounts
- `gcloud compute addresses list --project=img-dev` shows `channel-web-ip`

---

### Phase 1.2 — Knowledge Service
**When:** Day 1, ~4 hours after foundation is done
**Service:** `src/knowledge/`

**Files created:**
```
src/knowledge/
  main.py
  requirements.txt
  Dockerfile
  deploy.sh          (manual deploy script, not CI/CD)
tests/knowledge/
  test_knowledge.py
```

**API contract:**
```
POST /search
  Request:  { "query": str, "group_ids": list[str] | null }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str, "valid_at": str | null }] }

GET /health
  Response: { "status": "healthy" }
```

**Behaviour:**
1. On startup: connect to Neo4j via graphiti-core (credentials from Secret Manager)
2. `graphiti.search(query, group_ids=group_ids, num_results=5)` → list of EdgeResult
3. Build context: one line per edge — `[source_id] fact_text (valid from: valid_at)`
4. Call OpenAI gpt-4o-mini with system prompt and context
5. Return `{ answer, facts }` — facts are the raw Graphiti edges, not generated

**System prompt (non-negotiable constraints):**
- Answer ONLY from the provided facts
- Cite the source_id for every claim
- If facts are insufficient: respond "I don't have that information in the school documents."
- Never invent, extrapolate, or guess

**Deployment:**
- Cloud Run, `--no-allow-unauthenticated` (internal — only channel-web-sa can invoke)
- Service account: `knowledge-sa`
- Ingress: `internal` (not reachable from public internet at all)
- Region: europe-west1
- Min instances: 0, max: 3, memory: 512Mi
- All secrets via Secret Manager volume mounts (not env vars)

**Tests:**
- `test_health_returns_200`
- `test_search_returns_expected_shape` (mock graphiti.search + openai)
- `test_group_ids_passed_through_to_graphiti` (assert search called with correct group_ids)
- `test_empty_results_returns_i_dont_know` (mock returns [], assert "I don't have" in answer)

**Acceptance (observable):**
```bash
curl -X POST https://[knowledge-cloud-run-url]/search \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"query": "What time does school start?", "group_ids": ["family-manual"]}'
# → {"answer": "...", "facts": [...]}
```

---

### Phase 1.3 — Channel Web (COMPLETE 2026-03-21)
**Service:** `src/channel_web/`
**Deployed:** https://channel-web-jeyczovqfa-ew.a.run.app (revision channel-web-00002-9cp)
**Tests:** 5/5 passing
**Known issue:** POST /chat → "Service temporarily unavailable" — investigate at start of Phase 1.4
**UI note:** Pixel-perfect replica of Vercel demo. Hand-written CSS (no framework, no build step).
  Questions/categories editable in `src/channel_web/static/questions.json`.

**Original spec:**

**Files created:**
```
src/channel_web/
  main.py
  templates/
    index.html
  requirements.txt
  Dockerfile
  deploy.sh
tests/channel_web/
  test_channel_web.py
```

**API contract:**
```
GET /
  Response: HTML chatbot page

POST /chat
  Request:  { "message": str }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str }] }

GET /health
  Response: { "status": "healthy" }
```

**Behaviour:**
- `POST /chat` calls `POST {KNOWLEDGE_SERVICE_URL}/search` with `group_ids: null`
- Attaches service account identity token to knowledge service call
  (`google.auth.transport.requests` — not hardcoded credentials)
- All errors returned as JSON `{ "error": str }` — never expose stack traces to browser

**UI (vanilla HTML/CSS/JS — no framework, no build step):**
- Single page, white background, centered container, max-width 700px
- Chat input field + send button at bottom (fixed)
- Message thread above: user messages right-aligned (blue), bot answers left-aligned (gray)
- Citations below each answer: collapsible `<details>` element, source_id + fact text
- Spinner visible while waiting for response; input disabled during request
- Enter key submits message
- Error responses displayed as bot messages in red

**Deployment:**
- Cloud Run, `--allow-unauthenticated` (login page must load before auth; app enforces auth)
- Service account: `channel-web-sa`
- Region: europe-west1
- Min instances: 0, max: 2, memory: 256Mi
- `KNOWLEDGE_SERVICE_URL` env var (Cloud Run URL of knowledge service)
- `GOOGLE_CLIENT_ID` env var (OAuth client ID — safe to expose to frontend)

**Tests:**
- `test_health_returns_200`
- `test_chat_proxies_to_knowledge_service` (mock httpx call, assert forwarded correctly)
- `test_chat_error_from_knowledge_service_returns_500` (mock throws, assert error response)

**Acceptance (observable):**
```bash
curl -X POST https://[channel-web-cloud-run-url]/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "What are the school hours?"}'
# → 401 (no token)
```

---

### Phase 1.4 — Google Sign-In Auth
**When:** Day 2, ~1.5 hours (alongside Phase 1.3 — it's part of the same service)
**Note:** No Load Balancer, no custom domain required. Cloud Run URL (`*.run.app`) is
already HTTPS. Cloud IAP + LB is the production pattern (Sprint 4); this is the POC pattern.

**Deliverables:**
- OAuth 2.0 client ID created in img-dev (for Google Sign-In)
- channel_web validates Google ID tokens and enforces allowed-email list
- Allowed emails stored in Secret Manager as `ALLOWED_EMAILS` (comma-separated)
- Three test users can log in; all other Google accounts are rejected

**How it works:**
1. User opens `*.run.app` URL → served the login page
2. Page shows "Sign in with Google" button (Google Identity Services JS library)
3. User completes Google OAuth → browser receives a signed ID token
4. Frontend stores token in memory; sends it as `Authorization: Bearer <token>` on every `/chat` request
5. Backend validates token signature using Google's public keys (`google-auth` library)
6. Backend checks `email` claim against `ALLOWED_EMAILS` list → 403 if not in list
7. Token expiry handled: frontend re-authenticates silently if token is expired

**Files changed vs Phase 1.3:**
- `src/channel_web/main.py` — add token validation middleware (~20 lines)
- `src/channel_web/templates/index.html` — add Google Sign-In button + token handling (~25 lines JS)

**Deployment change:**
- channel_web: `--allow-unauthenticated` (login page must load before auth)
- `GOOGLE_CLIENT_ID` env var (not a secret — safe to expose to frontend)
- `ALLOWED_EMAILS` from Secret Manager

**Tests added:**
- `test_chat_rejects_missing_token` → 401
- `test_chat_rejects_invalid_token` → 401
- `test_chat_rejects_unlisted_email` → 403
- `test_chat_accepts_valid_token_and_listed_email` (mock google-auth verify)

**Acceptance (observable, primary):**
- Open `https://channel-web-[hash].run.app` in an incognito browser window
- Page shows "Sign in with Google" button
- Log in with a permitted Google Workspace account → chatbot page loads
- Log in with a non-permitted Google account → 403 error shown in page
- Ask "What time does school start?" → answer with citations appears

**Acceptance (negative):**
- `curl -X POST https://channel-web-[hash].run.app/chat -d '{"message":"hi"}'` (no token) → 401
- Valid Google token but email not in `ALLOWED_EMAILS` → 403

---

## Sprint 1 Acceptance Criteria (all must pass)

| # | Criterion | How to verify |
|---|-----------|--------------|
| 1 | Permitted user can access chatbot via browser | Open `*.run.app` URL in incognito, sign in with permitted account |
| 2 | Non-permitted user is rejected | Sign in with any non-listed Google account → 403 |
| 3 | `/chat` without token returns 401 | `curl -X POST .../chat -d '{"message":"hi"}'` |
| 4 | Knowledge service unreachable without identity token | `curl https://knowledge-[hash].run.app/health` → 403 |
| 5 | Chatbot returns a cited answer | Ask "What happens if a child is missing on a school trip?" |
| 6 | Chatbot says "I don't have that" for out-of-scope questions | Ask "What is the capital of France?" |

---

---

## Sprint 2 — Knowledge service rebuild + gateway

**Goal:** Replace Graphiti + Neo4j + OpenAI with Vertex AI Context Caching + Gemini 2.5 Flash.
API contract preserved — no channel_web changes required.

### Phase 2.1 — Knowledge service rebuild

**What changes:**
- Remove: `graphiti-core`, `neo4j` dependencies; all Graphiti search logic
- Remove: OpenAI dependency and call
- Add: `google-cloud-aiplatform` (Vertex AI SDK) for context cache management + generation
- Add: cache lifecycle management (create/refresh/expire)

**New behaviour:**
1. On startup: check for a valid Vertex AI Context Cache. If none, create one from the 7 canonical
   markdown files in `data/pipeline/latest/02_ai_cleaned/` (en_/es_ prefixed files only).
2. `POST /search`: call Gemini 2.5 Flash with `cached_content=<cache_id>` + query
3. System prompt instructs: answer only from context; return JSON `{ answer, citations: [{ document, excerpt }] }`
4. Map citations → existing `facts` shape: `{ answer, facts: [{ fact: str, source_id: str }] }`
5. Access filtering: pass permitted `source_ids` in system prompt ("answer only from: X, Y, Z")

**Cache lifecycle:**
- Cache ID stored in Firestore doc `config/context_cache` (`{ cache_name: str, created_at: ts, expires_at: ts }`)
- TTL: 24h (renewed on each restart; corpus updates once per sprint at most)
- Corpus update flow: delete old cache → create new cache → update Firestore doc

**Secrets/config changes:**
- Remove: `NEO4J_URI`, `NEO4J_PASSWORD` from Secret Manager (after rebuild verified)
- Remove: `OPENAI_API_KEY` from Secret Manager (after rebuild verified)
- `knowledge-sa` IAM: add `roles/aiplatform.user` (Vertex AI calls)
- No new secrets — service account auth handles Vertex AI (no API key needed)

**API contract (unchanged):**
```
POST /search
  Request:  { "query": str, "group_ids": list[str] | null }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str, "valid_at": null }] }
```
`valid_at` is always `null` (no temporal model in context caching).

**Files changed:**
```
src/knowledge/main.py          — rewrite search logic; add cache management
src/knowledge/requirements.txt — swap graphiti-core/neo4j/openai → google-cloud-aiplatform
tests/knowledge/test_knowledge.py — update mocks (Vertex AI instead of Graphiti/OpenAI)
```

**Acceptance:**
```bash
curl -X POST https://[knowledge-url]/search \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"query": "What time does school start?", "group_ids": null}'
# → { "answer": "...", "facts": [{ "fact": "...", "source_id": "en_family_manual_24_25" }] }
```

---

## Sprint 1 cleanup (before Sprint 2 begins)

| Item | Action | When |
|------|--------|------|
| knowledge service ingress | Restore `--ingress=internal` (changed to `all` for local testing) | After channel_web E2E validated |

---

---

## POC Track — Retrieval Architecture Validation

**Goal:** Empirically answer the open questions in `docs/design/RAG -- System Design.md`
before committing to a retrieval architecture for Sprint 3+.
These run in parallel with Sprint 2 — they are exploratory only, no production commits.

### POC1 — Single-document PageIndex

#### Iteration 3 — DONE 2026-04-13
**Params:** MAX=5000, MIN=1500 (unchanged)
**Files:** `poc/poc1_single_doc/` — see `post_mortem/iter3_design.md` for protocol

**Architecture under test:**
- Parse → hoist preamble (step 2) → split oversized leaves on full_text_chars (steps 3–5) →
  thin small nodes, at least one < MIN, preamble force-merged (step 7) →
  summarise unprocessed leaves (step 6) → rewrite intermediates bottom-up from children only (step 8) → validate
- Topics: semicolon-separated 1–5 word phrases per node; titles rewritten to index anchors
- Query: LLM sees outline of titles + topics → selects node IDs → full text → synthesis
- Models: gemini-2.5-flash-lite (structural), gemini-2.5-flash (quality)
- Build emits `<index>.build.log`; eval emits `<results>.log` (build + query pipeline combined)

**Eval results (4 docs, 16 queries):**
- avg chars→synth: ~10,000
- policy3 + family_manual: clean — all queries under 8K, 0 parent selections
- policy5 Q7: EXPLOSION 59,569c — cross-section query selects parent nodes
- policy1 Q2/Q3: over target 22,893c / 18,820c

#### Iteration 4 — DONE 2026-04-13
**Target:** avg chars→synth ≤ 5K; eliminate cross-section explosions
**Approach:** (1) outline annotates parents `[+N children — do not select]`; prompt instructs leaf-only selection. (2) post-selection fallback: expand any parent to direct children.

**Eval results (4 docs, 16 queries):**
- avg chars→synth: 5,518 (target: ≤5K)
- max chars→synth: 17,563 (policy1 Q2 — multi-section disclosure query, not explosion)
- parent selections: 0/16 — lever 1 fully effective
- avg query cost: ~$0.0015 (~660 queries/$)
- 0 explosions (>40K) across all queries

### POC2 — Multi-document routing
**Status:** BLOCKED on POC1 post-mortem — design TBD

---

## Known gaps (to address in Sprint 2+)

| Gap | Impact | Sprint |
|-----|--------|--------|
| Graphiti + Neo4j underperforms on this corpus | Poor answer quality; high cost | Sprint 2 — full rebuild |
| OpenAI (not Vertex AI/Gemini) for answer synthesis | Wrong LLM stack; cost unpredictability | Sprint 2 — replaced by Context Caching |
| group_ids=null — all users see all sources | No access control per user | Sprint 2 — prompt-level filtering |
| No gateway — channel_web calls knowledge directly | Tight coupling, no routing layer | Sprint 2 |
| No CI/CD — manual deploy scripts only | Error-prone deploys | Sprint 4 |
| App-level token validation (not Cloud IAP) | Acceptable for POC; replace with IAP + LB in production | Sprint 4 |
| Suggestion pill default questions not cached | Every click hits LLM; identical queries re-run | Sprint 2 — less critical with caching |

### Caching note (suggestion pill questions)
The questions in `src/channel_web/static/questions.json` are predefined and static.
Their answers should be cached at the knowledge service layer (or a thin cache in channel_web)
so repeated identical queries do not hit the LLM and Neo4j graph.
Cache invalidation must be triggered when the corpus is updated (ingestion pipeline event).
Design deferred to Sprint 2 alongside the gateway and access control work.

---

## Success criteria for Sprint 1

A non-technical user with a Google Workspace account can:
1. Open a URL in a browser with no setup
2. Log in with their school Google account
3. Ask a question in natural language
4. Receive a cited answer grounded in school documents

That is the only measure of success. All other concerns are Sprint 2+.
