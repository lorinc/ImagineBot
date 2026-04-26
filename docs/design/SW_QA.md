# SW QA — ImagineBot

Strategic QA reference. Operational commands live in `tests/CLAUDE.md`.
This file is the operating manual for autonomous improvement work tied to `docs/SAAS_MATURITY_FRAMEWORK.md`.

---

## 1. Current coverage matrix

Legend: ✅ exists and meaningful | 🟡 exists but shallow | ❌ absent

| Service | contracts | unit | integration | smoke | eval |
|---|---|---|---|---|---|
| gateway | ✅ `test_gateway_contract.py` — ChatRequest, FeedbackRequest | 🟡 `test_chat_flow, test_sanitize, test_scope_gate` — mocked deps, no SSE shape assertions | ❌ | ❌ | ❌ |
| knowledge | ✅ `test_knowledge_contract.py` — SearchRequest, SearchResponse, Fact, TopicsRequest, TopicsResponse, TopicNode | 🟡 `test_knowledge.py` — tests old context-cache version; stale | ❌ | ❌ | ❌ |
| channel_web | ✅ `test_channel_web_contract.py` — ChatRequest, FeedbackRequest | 🟡 `test_channel_web.py` — auth mocked | ❌ | ❌ | ❌ |
| ingestion | ❌ | ✅ `test_table_to_prose.py` — step 4 only; steps 1-3, 5 uncovered | ❌ | ❌ | ❌ |

All models extracted to `src/<service>/models.py`. Contract tests use `importlib.util.spec_from_file_location`
with distinct module names (`gateway.models`, `knowledge.models`, `channel_web.models`) to avoid
`sys.modules['models']` collision when all three are collected in one pytest invocation.

Existing unit tests in `tests/<service>/` (old layout). Migration to `tests/unit/` pending.

**Known pre-existing issue:** `tests/gateway/` unit tests fail with `ModuleNotFoundError: vertexai`
when run against the shared `.venv`. The gateway service deps are not installed there. Out of scope
for this task; tracked as a test infrastructure gap.

**Key gaps driving development friction:**
- No deployed-system perception — can't verify a deploy worked without manual browser/console check
- No Firestore trace verification — can't confirm observability is intact after a change
- No answer quality signal — can't know if retrieval/prompt changes improved or degraded quality

---

## 2. Scripted perception tools

Tools that give autonomous eyes on the deployed system. None exist yet. Each tool below has an exact
spec so any session can implement it without re-designing.

### 2.1 Smoke test — `tests/smoke/test_gateway_smoke.py`

**Purpose:** Verify a deployed gateway returns a valid SSE stream with correct event sequence.
**Dependencies:** live staging URL, valid Google ID token for a test user.
**What it asserts:**
1. HTTP 200 with `Content-Type: text/event-stream`
2. `event: progress` appears at least once before `event: answer`
3. `event: answer` data contains non-empty `answer`, non-empty `facts` array, `session_id`, `trace_id`
4. No `event: error` in stream
5. Full stream completes within 60s

**Env vars required:**
```
SMOKE_GATEWAY_URL    https://gateway-jeyczovqfa-ew.a.run.app
SMOKE_ID_TOKEN       <valid Google ID token for allowed test user>
SMOKE_QUERY          What happens after a fire drill?   # known in-corpus query
```

**Implementation note:** Use `httpx` with `stream()` + SSE line parsing. Do not use `requests` (sync only).
Test user token must be refreshed before each run — do not cache it in any file.

### 2.2 Trace verifier — `tests/smoke/test_trace_firestore.py`

**Purpose:** After a smoke query, assert the trace landed in Firestore with all required fields.
**Dependencies:** `GOOGLE_APPLICATION_CREDENTIALS` or ADC; `GCP_PROJECT_ID=img-dev`; `trace_id` from smoke test output.
**What it asserts (against `traces/{trace_id}`):**
1. Document exists within 10s of query completion
2. All top-level required fields present: `trace_id, session_id, timestamp, versions, pipeline_path, input, output`
3. `output.answer` non-empty, `output.facts` is a list (may be empty)
4. `spans` is a non-empty list
5. `feedback` field absent or null (not pre-populated)

**Implementation note:** Poll with 1s retry up to 10s before failing. Firestore writes are fire-and-forget;
a small delay is expected.

### 2.3 Pipeline integrity check — `tools/check_pipeline.sh`

**Purpose:** Verify the ingestion pipeline's data flow is consistent end-to-end without running the full pipeline.
**What it checks:**
1. `data/pipeline/latest/02_ai_cleaned/` is non-empty
2. Every `.md` file in `02_ai_cleaned/` has a corresponding entry in `data/index/multi_index.json`
3. `multi_index.json` contains at least 10 nodes (sanity floor)
4. Step 4 prose marker: at least one file in `02_ai_cleaned/` contains the string `<!-- prose -->`
   (verifies step 4 rewrites are landing in the right directory)

**Implementation:** 30-line bash script. No Python required. Run after any pipeline rebuild.

### 2.4 UI perception — `tests/smoke/test_ui_playwright.py`

**Purpose:** Verify the channel_web frontend renders and is interactive.
**Dependencies:** `playwright` (Python), live staging URL, valid test user with Google account.
**What it asserts:**
1. Chat input field is visible and accepts text
2. Submitting a query triggers at least one progress indicator
3. An answer block appears within 90s
4. Feedback thumbs buttons are present in the answer block
5. No JS console errors

**Implementation note:** Requires `playwright install chromium`. Token injection: use `page.evaluate()` to
set `localStorage['id_token']` before navigating, OR use a test-specific bypass header if one is added.
Until auth bypass exists, this test requires a full Google Sign-In flow via `playwright` — fragile.
**Status:** Do not implement until `tests/smoke/test_gateway_smoke.py` is working.

---

## 3. Eval harness

**Purpose:** Measure answer quality across a fixed golden dataset. Run before/after changes to retrieval,
chunking, prompts, or index. A numeric score gates whether a change ships.

### 3.1 Golden dataset format

File: `tests/eval/golden.jsonl` — one JSON object per line:

```json
{
  "id": "fd-001",
  "query": "What must staff do immediately after a fire drill?",
  "expected_facts": ["personnel headcount", "staff check"],
  "expected_source_ids": ["policy_fire_safety"],
  "must_not_contain": ["evacuation route"],
  "notes": "Tests step-4 table extraction — facts come from a converted prose table"
}
```

Fields:
- `id` — stable identifier, never reuse
- `query` — exact string sent to knowledge service
- `expected_facts` — list of substrings; answer must contain at least one
- `expected_source_ids` — list of source_id values that must appear in `facts` array
- `must_not_contain` — list of substrings that must NOT appear in answer (hallucination check)
- `notes` — human context, not used by harness

### 3.2 Eval runner — `tests/eval/run_eval.py`

Calls the knowledge `/search` endpoint directly (bypasses gateway — tests retrieval+synthesis only).
Outputs per-query pass/fail + aggregate scores:

| Metric | Definition |
|---|---|
| `fact_recall` | fraction of queries where answer contains ≥1 expected fact |
| `source_precision` | fraction of queries where ≥1 expected source_id appears in facts |
| `hallucination_rate` | fraction of queries where answer contains a `must_not_contain` string |
| `pass_rate` | fraction of queries passing all three checks |

Baseline: capture scores before a change. Regression threshold: `pass_rate` must not drop >5pp from baseline.
Baseline file: `tests/eval/baseline.json` — committed, updated intentionally (not on every run).

### 3.3 Minimum viable golden dataset

Start with 20 queries covering:
- 5 direct fact lookups (single-document answers)
- 5 policy queries (conditional clauses, "if/then" structures)
- 3 multi-document queries (answer requires two sources)
- 3 out-of-scope queries (must return the canned "not in scope" answer)
- 2 vague queries (must trigger the "not specific enough" path, not an answer)
- 2 regression cases from HEURISTICS.log (known past failures)

---

## 4. Autonomy protocol

When the user says "improve dimension X from SAAS_MATURITY_FRAMEWORK.md":

### Step 0 — Understand the target
1. Read `docs/SAAS_MATURITY_FRAMEWORK.md` — find dimension X, identify current level and target level
2. Read the relevant service `CLAUDE.md` and `ARCHITECTURE.md`
3. Read `docs/ARCHITECTURE.md` for cross-cutting constraints
4. State the delta: "Currently L0 because [reason]. L1 requires [specific observable change]."
   **Stop and confirm with user before proceeding if scope is >1 service or >1 day of work.**

### Step 1 — Design acceptance criteria
Write 3–5 acceptance criteria in the form:
- "Given [setup], when [action], then [observable output]"
- Each criterion must be verifiable without trusting Claude's own report
- At least one criterion must be a scripted check (smoke test, script output, Firestore query)
**Stop and confirm acceptance criteria with user before implementing.**

### Step 2 — Implement
- Stay within the scope agreed in Step 0
- Do not touch services not listed in IN_SCOPE
- Write tests first if the change is logic-bearing; write tests after for infra changes
- Commit incrementally — one logical unit per commit

### Step 3 — Verify
Run in this order, stopping on first failure:
```bash
# Contracts + unit (always)
pytest tests/contracts/ tests/unit/ tests/gateway/ tests/channel_web/ tests/knowledge/ tests/ingestion/ -v

# Integration (if Firestore-touching code changed)
gcloud emulators firestore start --host-port=localhost:8080 &
FIRESTORE_EMULATOR_HOST=localhost:8080 GCP_PROJECT_ID=test-project pytest tests/integration/ -v

# Deploy (if service code changed)
cd src/<service> && bash deploy.sh

# Smoke (after deploy)
pytest tests/smoke/test_gateway_smoke.py -v
pytest tests/smoke/test_trace_firestore.py -v

# Eval (if retrieval, prompts, or chunking changed)
python3 tests/eval/run_eval.py --compare-baseline
```

### Step 4 — Document
1. Update `docs/SAAS_MATURITY_FRAMEWORK.md` — advance `◀ now` marker for dimension X
2. Append to `.claude/HEURISTICS.log` if a non-obvious decision was made
3. Update service `CLAUDE.md` if a new operational pattern was introduced
4. Update `docs/ARCHITECTURE.md` if a cross-service contract changed

### Step 5 — Report
Provide the user with:
1. What changed (files, services)
2. What was verified automatically (test output, script output)
3. **Manual verification instructions** — exactly what the user should do and what they should see
   Format: numbered steps, expected output per step, "this is wrong if you see X"
4. Any known limitations or follow-on work

---

## 5. Coverage targets (not yet achieved)

These are the targets, not the current state. Implement layer by layer.

| Layer | Target | Current |
|---|---|---|
| contracts | One file per API boundary (gateway /chat, knowledge /search) | ✅ 35 tests, all passing |
| unit | All business logic covered; mocks only at service boundaries | 🟡 partial |
| integration | gateway→knowledge full request cycle against real Firestore emulator | ❌ none |
| smoke | `test_gateway_smoke.py` + `test_trace_firestore.py` after every staging deploy | ❌ none |
| eval | `run_eval.py` against golden.jsonl before any knowledge/prompt change | ❌ none |
| pipeline | `check_pipeline.sh` after any ingestion run | ❌ none |
| UI | `test_ui_playwright.py` after any channel_web deploy | ❌ blocked on auth |

Milestone: when contracts + unit + smoke are all ✅, autonomy is sufficient for most maturity improvements.
Milestone: when eval harness exists with ≥20 golden queries, prompt/retrieval changes can ship without manual review.

---

## 6. What cannot be automated (manual steps per capability area)

Some checks require human eyes or physical access. Document them so they are acknowledged, not forgotten.

| Check | Why manual | Frequency |
|---|---|---|
| UI rendering correctness (visual layout, mobile) | No headless browser yet; Playwright blocked on auth | Per channel_web deploy |
| Google Sign-In flow end-to-end | Requires real browser + Google account | Per auth change |
| Firestore console — data integrity | Complementary to `test_trace_firestore.py` but catches schema drift | Monthly |
| Cloud Run logs — cold start timing | No metric export yet | Per deploy |
| Vertex AI quota remaining | No alert configured | Weekly |
