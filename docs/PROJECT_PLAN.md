# Project Plan
# Update when: a phase completes or is added, a sprint boundary is crossed, a spike resolves.
# Does not record bug fixes or session details — those go in .claude/HEURISTICS.log.
# Current session state lives in .claude/SESSION.md, not here.

## Priority guidance

Sprint priorities are guided by `docs/SAAS_MATURITY_FRAMEWORK.md`.
That document maps every operational dimension to four maturity levels (L0–L3) and marks current state.
Before planning a sprint, use it to identify which L0 dimensions block the next milestone:
- **L2 across all dimensions** = production-grade single-tenant deployment
- **L3 across all dimensions** = second customer without engineering involvement

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

**Goal:** Replace Graphiti + Neo4j + OpenAI with a Vertex AI + Gemini pipeline.
API contract preserved — no channel_web changes required.

### Phase 2.1 — Knowledge service rebuild — DEPLOYED 2026-04-22

**Architecture chosen:** PageIndex (poc1 validated) — not Context Caching as originally planned.
Context Caching was a viable interim approach; PageIndex is the better long-term architecture
(evaluated via POC1/POC2/POC3 track). See POC track section for rationale.

**What was built:**
- `src/knowledge/indexer/` — PageIndex pipeline (verbatim from poc1, 9 modules)
- `src/knowledge/main.py` — rewritten: loads multi_index.json at startup, 3-stage query pipeline
- `tools/build_index.py` — offline index build tool (last step of ingestion pipeline)
- `tools/archive/create_cache.py` — original Context Cache tool, archived with Firestore reuse notes
- `data/index/` — pre-built 6-doc index (gitignored; baked into Docker image for UAT)
- `src/knowledge/TODO.md` — open work tracking (group_ids, structured citations, index lifecycle)

**Known stubs (documented in TODO.md):**
- `group_ids`: accepted but ignored — future access-control filter
- `facts`: derived from selected nodes (section title + doc_id), not structured citations

**API contract (unchanged):**
```
POST /search
  Request:  { "query": str, "group_ids": list[str] | null }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str, "valid_at": null }] }
```

**Deploy:**
```bash
git add src/knowledge/ tools/
git commit -m "Migrate knowledge service to PageIndex (poc1 → src/knowledge)"
bash src/knowledge/deploy.sh
```

**Acceptance:**
```bash
curl -s -X POST https://knowledge-jeyczovqfa-ew.a.run.app/search \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"query": "What time does school start?"}' | python3 -m json.tool
# → {"answer": "...", "facts": [{"fact": "...", "source_id": "en_..."}]}
```

### Phase 2.3 — Pipeline tracing + version stamps + 👎👍 feedback — IMPLEMENTATION COMPLETE 2026-04-24

**What was built:**
- Firestore `traces/{trace_id}` written fire-and-forget after every chat request
- Schema: trace_id, session_id, timestamp, versions, pipeline_path, input, classifier, rewrite, topics, knowledge, output, feedback
- Frugal storage (~800 bytes/trace): decisions + IDs only — no prompt text, no corpus summary, no node text
- Per-service version stamps via `MODULE_GIT_REV=$(git log -1 --format="%H" -- src/<service>/)` injected at deploy time
- Knowledge service returns `selected_nodes: [{doc_id, node_id}]` in SearchResponse + `X-Service-Version` header
- Gateway reads version header → `versions.knowledge` in trace
- `POST /feedback` on gateway updates `traces/{trace_id}.feedback.*` in Firestore
- `POST /feedback` on channel_web forwards to gateway (thin client pattern preserved)
- 👎👍 buttons in UI: 👍 fires immediately, 👎 shows comment form; both attach `trace_id` from SSE

**Files created/modified:**
- `src/gateway/services/trace_writer.py` (new)
- `src/gateway/routers/chat.py`, `src/gateway/config.py`, `src/gateway/requirements.txt`, `src/gateway/deploy.sh`
- `src/knowledge/main.py`, `src/knowledge/deploy.sh`
- `src/channel_web/main.py`, `src/channel_web/static/app.js`, `src/channel_web/deploy.sh`

**Status:** DEPLOYED 2026-04-24. All three services live at bb2f256. Smoke test passed (trace doc verified in Firestore). Browser UAT pending.

### Phase 2.4 — Feedback editing + short-circuit feedback buttons — DEPLOYED 2026-04-25

**What was built:**
- Feedback editing: both 👍 and 👎 open comment form; re-clicking a selected thumb re-opens form pre-filled with prior comment
- Short-circuit exits (out-of-scope, orientation) now emit `trace_id` in SSE event → 👍/👎 buttons appear on those answers
- `src/gateway/routers/chat.py` — add `trace_id` field to `out_of_scope` and `orientation` answer events
- `src/channel_web/static/app.js` — feedback editing state machine; pre-fill on re-click
- `src/channel_web/static/style.css` — `.action-btn-selected` CSS class

**Status:** DEPLOYED 2026-04-25. Browser UAT PASSED (commits 0277339, ffcade7).

### Phase 2.5 — Pipeline observability: spans + thinking panel — DEPLOYED 2026-04-25

**Architecture:** OTel-inspired spans, stdlib only, no SDK dependency. Each service emits
its own spans via a ContextVar. Gateway aggregates + persists. Display prose lives in
`step_messages.py` — not in pipeline code.

**What was built:**
- `src/knowledge/indexer/observability.py` — `QueryContext` + ContextVar; `emit_span`, `get_query_spans`
- `src/knowledge/indexer/multi.py` — 4 span points: `knowledge.routing`, `knowledge.selection`, `knowledge.synthesis_started`, `knowledge.synthesis_done`
- `src/knowledge/main.py` — `QueryContext` wired into `/search` (spans in response) and `/search/stream` (real-time `event: span` SSE)
- `src/gateway/services/observability.py` — `SpanCollector` (gateway spans + relay of knowledge spans)
- `src/gateway/services/step_messages.py` — all display prose; `format_span()` — no prose in pipeline code
- `src/gateway/services/knowledge_client.py` — `X-Trace-Id` header on all calls; `search_stream()` replaces `search()`
- `src/gateway/routers/chat.py` — `SpanCollector` per request; `event: thinking` SSE; `trace["spans"]` in Firestore
- `src/gateway/services/trace_writer.py` — `tenant_id` seam (`_trace_ref` helper; always `None` until auth lands)
- `src/channel_web/static/app.js` — pending card with live thinking list; `buildAnswerCard` adds collapsed `<details>` panel
- `src/channel_web/static/style.css` — `.pending-card`, `.thinking-details`, `.thinking-steps`, `.thinking-step`, `.step-ms`

**Firestore trace schema addendum:** `spans: list[Span]` added to `traces/{trace_id}`. Each span: `{service, name, attributes, duration_ms}`. Existing fields unchanged.

**Smoke test (2026-04-25):** 8 spans in Firestore for a single `/chat` call:
  `[gateway]` classify, rewrite.skipped, topics, breadth.focused
  `[knowledge]` knowledge.routing, knowledge.selection, knowledge.synthesis_started, knowledge.synthesis_done

**Status:** DEPLOYED 2026-04-25 (commits 7215269, 310bc16, b7943ab). Browser UAT PASSED 2026-04-26.

### Phase 2.5.1 — 0-chunk synthesis hallucination fix — DEPLOYED 2026-04-26

**Bug:** When routing selected 0 nodes, `multi.py` passed the routing outline as fallback
synthesis context. LLM answered from training data with no retrieval. Answer looked valid;
trace showed "Selected 0 chunks (11582 chars) to LLM".

**Fix:** Short-circuit in `multi.py` before synthesis call: if `section_parts` is empty,
return canned `"The knowledge base does not contain relevant information for this question."`
directly. Routing outline is never passed as synthesis context under any circumstances.

**Files:** `src/knowledge/indexer/multi.py`
**Status:** DEPLOYED 2026-04-26 (revision knowledge-00012-4n7).

### Cross-cutting — ARCHITECTURE.md authored 2026-04-26

ARCHITECTURE.md created for all 8 `src/` modules. Documents boundaries, contracts,
guardrails derived from code + heuristics. Surfaced 4 new issues (see SESSION.md).

**Status:** Written. Not yet committed.

### Phase 2.6 — Smoke tests + trace output fix — COMPLETE 2026-04-26

**What was built:**
- `tests/smoke/test_gateway_smoke.py` — asserts HTTP 200, SSE shape, progress→answer ordering, facts non-empty, trace_id present (SW_QA.md §2.1)
- `tests/smoke/test_trace_firestore.py` — polls Firestore traces/{trace_id}, asserts all required fields, output.answer + facts, spans non-empty (SW_QA.md §2.2)
- Fixed `trace["output"]` bug in `src/gateway/routers/chat.py`: all three pipeline paths now include `facts` in output per architecture spec
- Fixed `src/gateway/Dockerfile`: missing `COPY src/gateway/models.py .` caused ModuleNotFoundError on Cloud Run

**Coverage matrix after this phase:**
- gateway smoke: ✅ `test_gateway_smoke.py`
- knowledge smoke: ✅ `test_trace_firestore.py` (covers knowledge indirectly via gateway)

**Status:** DEPLOYED 2026-04-26 (gateway revision gateway-00013-7pz). Tests: 2/2 passing in 18s.

---

### Phase 2.7 — Pipeline integrity check + smoke dep pinning — COMPLETE 2026-04-26

**What was built:**
- `tools/check_pipeline.sh` — 4-check bash script: 02_ai_cleaned non-empty, all indexed sources present, node count ≥10, step 4 prose files in 03_chunked (SW_QA.md §2.3)
- `tests/smoke/requirements.txt` — pinned `httpx>=0.27.2`, `google-cloud-firestore>=2.19.0`
- Updated `docs/design/SW_QA.md`: pipeline row → ✅; documented prose marker spec deviation

**Note:** SW_QA.md §2.3 spec called for a `<!-- prose -->` marker check; `step4_table_to_prose.py` does not emit this marker. Check #4 implemented as: `03_chunked/*_prose.md` files exist, which is the actual step 4 output.

**Status:** COMPLETE 2026-04-26. bash tools/check_pipeline.sh → 4 passed, 0 failed.

---

### Phase 2.8 — Eval harness question set design — COMPLETE 2026-04-26

**What was produced:**
- `docs/design/BOT_QA.md` — complete question taxonomy for eval harness: 18 families, ~33 items, no fixed ceiling
- Eval runner target changed from knowledge `/search` to gateway `/chat` (tests full gateway+knowledge pipeline)
- Families added beyond SW_QA.md §3.3: exception omission, L1 vocabulary mismatch, procedure truncation, dual-version synthesis blend, model knowledge supplement, in-scope undocumented, scope gate false positive, multi-turn follow-up
- `golden.jsonl` schema extended with `prior_turns` for multi-turn items
- Generation workflow: 4 LLM-assisted prompts + hand-curation gate, all specified in BOT_QA.md §Generation workflow
- Architecture-specific failure modes (table carry-forward dropped — not a failure mode for PageIndex; replaced with parent-context loss + cross-doc routing miss)

**Status:** COMPLETE 2026-04-26. Next: execute generation workflow (BOT_QA.md Steps 1–5) to produce draft `golden.jsonl` candidates for human review.

---

### Phase 2.9 — Benchmark question candidates — COMPLETE 2026-04-27

**What was produced:**
- `docs/design/BENCHMARK_QUESTIONS.md` — 37 question candidates across 19 families; all TBD source verifications resolved
- `tests/eval/golden.jsonl` — 37 items, 35 active, 2 skipped (rg-001, pt-001: separate Fire Safety Policy not indexed)
- `tests/eval/run_eval.py` — SSE-aware eval harness stub; flags: --gateway, --filter, --verbose
- Corpus gaps found: fire evacuation procedure ("See separate policy") not indexed; supervision ratios absent (us-001 reclassified out-of-corpus)
- Workflow change: all candidates kept; empirical pass/fail determines redundancy

**Status:** COMPLETE 2026-04-27. Eval harness ready to run against live gateway.

---

### Phase 3.1 — GDrive integration UAT plan — SCOPED 2026-04-24

**Plan:** `~/.claude/plans/awesome-do-a-gap-dynamic-stardust.md`

**Scope (agreed):** Ops-triggered ingest via CLI (no admin UI). Single corpus. Flat Drive folder. No multi-tenant isolation.

**Gap summary:**
- Ingestion: personal OAuth → service account auth; hardcoded folder name → `--drive-folder-id` param; local index → GCS write
- Knowledge: Docker-baked index → GCS download at startup
- GCP: create `ingestion-sa`, GCS bucket `img-dev-index`, grant roles, SA key in Secret Manager

**Explicitly deferred:** admin service, Firestore `sources` collection, `group_ids` enforcement, scheduled polling, subfolder recursion, DOCX-via-SA.

**Status:** Plan written. Not started.

---

### Phase 2.2 — Gateway orchestration layer — DEPLOYED 2026-04-22

**What was built:**
- `src/gateway/` — new FastAPI service, single entry point for all channels
- Pipeline: sanitize → classify (scope+specificity, 1 LLM call) → Tier 3/Tier 2 routing → standalone rewrite → Stage A (topics) → Stage B (synthesis) → SSE response
- Session tracking: in-memory dict keyed by UUID, 10-turn cap, flows browser ↔ gateway via session_id field
- Specificity gate: vague queries ("What are the rules?") get orientation response; no KB call
- Breadth detection: Stage A calls GET /topics on knowledge service; if > MAX_TOPIC_PATHS (5) after sibling consolidation → auto-deliver overview via overview synthesis prompt
- `src/gateway/TODO.md` — full backlog: PRF, rate limiting, NLI faithfulness, ReAct loop, etc.
- `src/channel_web/` updated: calls GATEWAY_SERVICE_URL/chat instead of knowledge/search/stream; app.js tracks session_id
- Tests: 14/14 gateway (sanitize: 8, flow: 6) + 10/10 channel_web still passing

**API contract (gateway — unchanged):**
```
POST /chat
  Request:  { "message": str, "session_id": str | null }
  Response: SSE stream — progress events + answer event
  Answer event data: { "answer": str, "facts": [...], "session_id": str }

GET /health
  Response: { "status": "healthy" }
```

**New knowledge endpoints (added for gateway):**
```
GET /summary
  Response: { "outline": str }   ← L1 routing outline for classifier prompt

POST /topics
  Request:  { "query": str, "group_ids": list[str] | null }
  Response: { "l1_topics": [{ "doc_id": str, "id": str, "title": str }] }
```

**Deploy:**
```bash
git add src/gateway/ src/channel_web/ src/knowledge/ tests/gateway/ tests/channel_web/
git commit -m "Add specificity gate, breadth detection, and overview mode to gateway + knowledge"
bash src/knowledge/deploy.sh   # deploy first — gateway needs new endpoints
bash src/gateway/deploy.sh     # creates gateway-sa, IAM grants, builds + deploys
bash src/channel_web/deploy.sh
```

**Acceptance:**
- `POST /chat` "What are the rules?" → orientation response, facts=[]
- `POST /chat` broad question → answer prefixed with "Your question covers several…"
- `POST /chat` school policy question → SSE answer with citations
- `POST /chat` out-of-scope question → canned refusal, no knowledge call
- Browser: follow-up question rewritten to standalone; session_id persists across turns

---

## Sprint 1 cleanup (before Sprint 2 begins)

| Item | Action | When |
|------|--------|------|
| knowledge service ingress | Restore `--ingress=internal` (changed to `all` for local testing) | After channel_web E2E validated |

---

---

## Spike Track — Process and Tooling

### Spike: Story-driven spec → design transition — NOT STARTED

**Question:** How do we author per-module acceptance criteria and cross-cutting principles
such that tests are derived from human intent, not from agent implementation?

**Why this matters:** Currently the agent authors both implementations and tests in the
same session, creating circularity — tests ratify what was built, not what was intended.
`docs/specs/` stub exists but all principles are currently status STUB (derived from
implementation). The eval harness (SW_QA.md §3) and any future acceptance-criteria-driven
test work depend on this being resolved first.

**Dependency:** SW_QA.md §3 (eval harness), SW_QA.md §5 unit coverage targets.

**Scope of the spike:**
- What is the right authoring workflow? (human writes specs up front; agent flags conflicts)
- How do per-module specs (`docs/specs/<module>.md`) integrate with the SW_QA.md autonomy protocol?
- How do PRINCIPLES.md invariants get enforced in tests without agent circular authorship?
- What does the review/approval gate look like in practice?

**Output:** Updated `docs/specs/PRINCIPLES.md` status → APPROVED (reviewed with human);
one pilot module spec (gateway or knowledge) at APPROVED status; updated SW_QA.md §4
autonomy protocol to reference specs as the authoritative input for acceptance criteria.

**Status:** NOT STARTED — pending human availability to co-author specs.

---

## POC Track — Retrieval Architecture Validation

**Goal:** Empirically answer the open questions in `docs/design/RAG -- System Design.md`
before committing to a retrieval architecture for Sprint 3+.
These run in parallel with Sprint 2 — they are exploratory only, no production commits.

### POC1 — Single-document PageIndex

#### Iteration 3 — DONE 2026-04-13
**Params:** MAX=5000, MIN=1500 (unchanged)
**Files:** poc1 phase (deleted 2026-04-26)

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

#### Indexer hardened — DONE 2026-04-13
Single-file pageindex.py split into 7-module package: config, node, parser, llm, prompts,
observability, pageindex (orchestrator). Eval confirmed identical behaviour post-refactor.
Known gap: module-level globals in observability.py — ContextVar migration pending.

### POC2 — Multi-document routing

#### Two-stage routing — DONE 2026-04-14
**Architecture:** compact routing outline (L1 nodes, 6 topics each) → structural model selects
1–2 doc IDs → per-doc node selection (existing single-doc pipeline, concurrent) → cross-doc synthesis.

**Files:** `indexer/multi.py`, `run/run_multi_eval.py`, `eval/queries_multi.json`

**Eval results (7 queries, 6 docs — `eval/results_multi_v1.json`):**
- 6/7 queries: correct routing and meaningful answer
- Q6 (fire drill): routing correct, per-doc selection failed — under investigation
- Routing always selects 2 docs (conservative); no routing misses
- avg latency: 16.6s  avg cost: $0.0019/query  (routing ~12% of total cost)

**Status (2026-04-15):**
- Hierarchical selection (walk-until-leaves): stage 1 routes over L1 nodes, stage 2+ discriminates within children, recurses until all selected are leaves. Backward-compatible step1 view.
- Structured synthesis prompt: CORE RULE / EXCEPTIONS AND CONDITIONS / FINAL ANSWER — conditional clauses now extracted explicitly.
- All prompts rewritten to terse/technical format.
- Discrimination: recall-oriented framing ("err inclusive"). Anchor-on-one approach attempted and reverted — precision gain causes recall loss on compound queries given lossy 300-char topic descriptions.
- Evals: P3H 6/6, P1H 6/6 (§1.13 miss in P1H5 is Stage 0 vocabulary gap, not Stage 2).
- Hard eval suite committed: queries_policy1_hard.json, queries_policy3_hard.json + result snapshots.
- Next: Priority 3 — retrieval framing shift (Stage 0, no rebuild).

### POC3 — OpenKB comparison — COMPLETE 2026-04-21

**Question:** Is OpenKB's wiki-compilation + agent approach a better retrieval architecture
than poc1's PageIndex + hierarchical selection?

**Files:** openkb_eval phase (deleted 2026-04-26)

**Eval results (4 docs, same query batteries as poc1):**

| Document      | OpenKB accuracy | avg latency | avg cost   | avg chars read |
|---------------|-----------------|-------------|------------|----------------|
| policy1_hard  | 5/6 PASS        | 4,342ms     | $0.00174   | 8,172          |
| policy3_hard  | 2/6 PASS        | 6,982ms     | $0.00275   | 18,388         |
| policy5       | no gold         | —           | —          | —              |
| family_manual | no gold         | —           | —          | —              |

poc1 node precision (different metric, not directly comparable): P1H 6/6, P3H 6/6.
OpenKB policy3 2/6 is a clear signal of degradation on procedural content.

**Rejection reasons:**

1. **Lower accuracy on complex documents.** policy3 (health/safety reporting, procedural
   content) scored 2/6. Procedural knowledge — sequences, conditions, reporting chains —
   does not compress well into concept pages. The concept-building LLM drops steps.

2. **Retrieval surface is lossy.** Concept pages are full rewrites by the LLM. Each time
   a new document contributes to an existing concept, the page is rewritten from scratch
   (confirmed from compiler.py `_CONCEPT_UPDATE_USER`: "Rewrite the full page... do not
   just append"). Details from earlier documents can be silently dropped.
   Quality ceiling = concept-building LLM's fidelity. poc1's ceiling = synthesis LLM's
   capability over the original source text.

3. **Cross-document merging hides provenance.** Once content from doc A and doc B is
   merged into a concept page, there is no way to retrieve just doc A's version. The
   sources frontmatter tracks which docs contributed, but the content is one blob.

**Latency finding (carried back to poc1):**
OpenKB is 2–6× faster despite running 3–7 sequential LLM calls vs poc1's ~3.
Root cause: poc1 synthesis call receives ~15k chars of raw section text, which triggers
Gemini 2.5 Flash's extended thinking budget. OpenKB's concept pages are pre-compressed;
individual calls stay small and thinking-light.

**Lessons carried into poc1 TODO (Stage 4 + Stage 5):**
- Distilled section text: lossless per-section compression to reduce synthesis prompt size
- Corpus context card: org-level grounding injected into every synthesis call
- Topic lookup table + embedding cross-references: multi-doc infrastructure (deferred)

---

## Known gaps (to address in Sprint 2+)

| Gap | Impact | Sprint |
|-----|--------|--------|
| ~~Graphiti + Neo4j underperforms on this corpus~~ | ~~Poor answer quality; high cost~~ | ✅ Closed 2026-04-22 — PageIndex deployed |
| ~~OpenAI (not Vertex AI/Gemini) for answer synthesis~~ | ~~Wrong LLM stack~~ | ✅ Closed 2026-04-22 — Gemini 2.5 Flash via Vertex AI |
| group_ids=null — all users see all sources | No access control per user | Sprint 2 — stub in place, enforcement pending |
| No gateway — channel_web calls knowledge directly | Tight coupling, no routing layer | Sprint 2 |
| No CI/CD — manual deploy scripts only | Error-prone deploys | Sprint 4 |
| App-level token validation (not Cloud IAP) | Acceptable for POC; replace with IAP + LB in production | Sprint 4 |
| Suggestion pill default questions not cached | Every click hits LLM; identical queries re-run | Sprint 2 — less critical with PageIndex |

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
