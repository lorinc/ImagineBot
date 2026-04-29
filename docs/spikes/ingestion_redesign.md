# Spike: Ingestion pipeline redesign
Date: 2026-04-29
Status: IN_PROGRESS — answers recorded, full rewrite pending in next session

## Question
What does the ingestion pipeline need to become a production-grade, multi-tenant, event-driven system — and what is the correct implementation sequence?

---

## Open questions (require user decision before implementation)

### Q1: Observability implementation — ANSWERED
**Decision: B — structured JSON logging, no new SDK dependencies.**
OTel SDK is justified when distributed traces span multiple services. Ingestion is a
standalone batch job; structured JSON logs + Cloud Monitoring alerting covers all
operational needs without the dependency cost. The existing span system
(`{ "service", "name", "attributes", "duration_ms" }`) is request-path/browser-streaming
specific and does not apply here.

### Q2: Alerting destination — ANSWERED
**Decision: two-part Layer 1 error surface.**
1. Add a Drive comment to the failed document with the full error detail (error type,
   reason, actionable instruction). Service account already has Editor access on the
   folder — no new permission needed.
2. Create a plain `.txt` file in the Drive folder:
   - Name: `⚠️ ERROR — <filename> — <timestamp>.txt`
   - Content: `READ COMMENT IN <filename>`
   The txt file is the attention signal; the comment is the content.
3. On successful re-processing of the document: delete the txt file.
   Drive comment may be left as resolved history.

Deferred: GCP-native monitoring and alerting infrastructure (Cloud Monitoring alert
policies, notification channels). Start using Google infrastructure for this in a
future sprint — design separately.

### Q3: Cost cap per run (`MAX_RUN_COST_USD`) — ANSWERED
**Decision: `MAX_RUN_COST_USD = 1.0`**
1 EUR equivalent. A full 6-doc rebuild costs ~$0.01, so hitting $1.00 signals a
massive error requiring immediate intervention. No legitimate run will approach this.

### Q4: Phase sequencing
- **Phase 1 only (this sprint):** Correctness + contract layer — dead code removal,
  structured logging, validation, error handling, large-doc chunking, cost tracking,
  advisory lock fix, `run_report.json`, `tools/status.py`. Gets the pipeline reliable
  and observable.
- **Phase 1 + 2 (this sprint):** Also add incremental per-file processing and Drive
  Changes API `pageToken` (event detection). More scope but eliminates the 1-minute
  polling waste.

### Q5: Drive comment permission — ANSWERED
**Decision: no new permission setup needed.**
Service account already has Editor access on the Drive folder (it was previously
uploading intermediary files). Editor access includes Commenter rights. Both Drive
comment creation and txt file creation work with existing permissions.

### Q6: Failure notification audience — ANSWERED (partially)
**Decision: send Drive comment to the person who copied the file into the folder.
If that is unknown, fall back to the document author.**
Both are available from Drive file metadata (`sharingUser` / `lastModifyingUser`).
Deferred: targeted routing and notification design belongs in the L2/L3 admin UI
sprint. For now the txt file in the folder is visible to everyone with folder access,
which is sufficient for Phase 1.

### Q7: Subfolder recursion — ANSWERED
**Decision: top-level DOCX files only.** No native Google Docs, no subfolders.
This is the contract for L2. Native Google Doc support and subfolder recursion are
named future features, designed separately.

Note: this reverses the earlier recommendation to accept native Google Docs. The
"DOCX-only MIME type filter is a dead end" entry in the dead ends section is wrong
and must be removed. DOCX-only is the correct contract.

### run_id format — ANSWERED
**Decision: `CLOUD_RUN_EXECUTION` env var (already injected by Cloud Run Jobs),
fall back to `datetime.utcnow().isoformat()` when absent (local/dev runs).**
This correlates directly with Cloud Logging execution records.

---

## Root causes of current failures

| Symptom | Root cause |
|---|---|
| Executions pile up | Scheduler fires every minute; jobs take >60s; advisory lock is the only protection |
| Zero logs for 20+ minutes | `PYTHONUNBUFFERED=1` was missing; stdout buffered and lost on SIGKILL |
| OAuth hang | `_save(creds)` inside try-block; Secret Manager read-only → PermissionError caught → browser flow hang |
| Gemini hang (EN_Policies_5) | `requests.post()` with no timeout; stuck in C socket; SIGTERM cannot interrupt |
| 1.6MB hallucination | EN_Policies_3 (88K chars) passed to Gemini; no output size guard |
| Stale lock | SIGKILL bypasses `finally`; TTL is the only protection |
| `en_*.md` filter | Local workflow used manually-named files; Drive-native filenames didn't match |
| Symlink ordering bug | `_update_symlink` called after `build_index.py`; Cloud Run has no persistent filesystem |
| Step 2 HttpError 500 | No retry logic; file silently skipped; index built without that document |
| Silent partial corpus | Pipeline exits 0 on per-file failures; degraded index served with no signal |

---

## Input file contract

This is the product-level contract. Anything outside it is **rejected loudly, not
skipped silently.** The previous "catch, log, continue" policy is eliminated.

### Accepted files

| Criterion | Rule |
|---|---|
| Location | Top-level in the configured Drive folder. No subfolder recursion until explicitly designed (see Q7). |
| Format | `.docx` file OR native Google Doc (`application/vnd.google-apps.document`). No Slides, Sheets, PDFs, uploaded images. |
| Access | Readable by the ingestion service account. A permission error is a configuration fault, not a document fault — it does not block processing of other documents. |
| Convertibility | Step 2 (Docs export) must produce ≥ 200 chars of Markdown. Empty or near-empty export = corrupt or locked document. |
| Minimum structure | Converted Markdown must contain at least one heading (`#` or `##`). A document with no headings cannot be chunked and produces an undifferentiated blob that retrieval cannot use. |
| Size | No hard size cap. All documents — any size — are processed via `_split_at_headings()`. Size is a pipeline concern, not a contract violation. |

### Rejection table

| Violation | `error_type` | Human-readable cause | Actionable instruction |
|---|---|---|---|
| Unsupported format | `UNSUPPORTED_FORMAT` | "This file type cannot be processed" | "Convert to a Word document (.docx) or Google Doc and re-upload" |
| Permission denied | `PERMISSION_DENIED` | "ImagineBot cannot access this document" | "Share the document with [service-account-email] (Viewer)" |
| Export returns < 200 chars | `EXPORT_EMPTY` | "This document appears to be locked, encrypted, or empty" | "Open the document in Google Docs and verify it contains readable text" |
| No headings after conversion | `NO_HEADINGS` | "This document has no section headings" | "Add at least one heading (bold title or Heading 1/2 style) so the document can be divided into topics" |
| Step 2 HttpError (non-permission) | `EXPORT_SERVER_ERROR` | "Google could not export this document (server error)" | "Wait 10 minutes and trigger a manual refresh. If the problem persists, re-save the document in Google Docs." |
| Step 3–5 exhausted retries | `PIPELINE_FAILURE` | "Processing failed after 3 attempts" | "Check run_report.json for the step and error detail." |

### Pre-flight policy
The job runs ALL files through Steps 1–2 (Drive → Markdown) and validates the results
**before** any file enters Steps 3–5. This means:
- Validation failures are collected in bulk and reported together.
- No Gemini cost is incurred before the corpus is confirmed structurally valid.
- If any file fails pre-flight, the run exits early with a clear report. Steps 3–5 do
  not start on the remaining valid files — the whole run is aborted.

**Rationale:** building an index from a partial validated set risks serving a corpus
that silently omits a document the operator believes is included. Abort-and-report is
safer than partial success.

---

## Error surface design (UX-first)

The person who can fix a document problem is the **school administrator** — not the
engineer watching Cloud Monitoring. The error must reach them where they already work,
without requiring a new admin UI.

### Layer 1 — Drive comment on the failed document (in-context, immediate)

When a document fails validation or any pipeline step, the job adds a Drive comment to
that specific document:

```
⚠️ ImagineBot could not process this document (2026-04-29 14:32 UTC)
Reason: This document has no section headings.
Action: Add at least one heading (bold title or Heading 1/2 style) so the
        document can be divided into topics, then save. The system will
        retry automatically.
```

Requires Commenter access on the Drive folder (see Q5). If the comment write fails,
fall back to Layer 2 only — do not let a comment failure abort the error reporting path.

Retry semantics: before adding a comment, check for an existing ImagineBot comment on
that document. If one exists from this error type, update it (new timestamp) rather than
duplicating. This prevents comment spam on documents that stay broken across multiple runs.

### Layer 2 — `run_report.json` in GCS (machine-readable, ops-queryable)

Every run — success or failure — writes to:
```
gs://<GCS_BUCKET>/<SOURCE_ID>/run_report.json
```

Schema:
```json
{
  "run_id": "2026-04-29T14:30:00Z",
  "status": "ok | partial_failure | failed | aborted",
  "started_at": "2026-04-29T14:30:00Z",
  "finished_at": "2026-04-29T14:33:00Z",
  "trigger": "scheduler | manual",
  "index_updated": false,
  "index_version_live": "2026-04-28T09:00:00Z",
  "index_age_hours": 14.5,
  "files": [
    {
      "name": "EN_Admissions.docx",
      "status": "ok",
      "steps_completed": [1, 2, 3, 4, 5],
      "chunks": 12,
      "cost_usd": 0.0003
    },
    {
      "name": "EN_Policies_3.docx",
      "status": "failed",
      "failed_at_step": 2,
      "error_type": "NO_HEADINGS",
      "error_detail": "Converted markdown contained no # or ## headings.",
      "actionable": "Add at least one heading to the document.",
      "drive_url": "https://docs.google.com/..."
    }
  ],
  "cost_total_usd": 0.0003,
  "lock_acquired_at": "2026-04-29T14:30:01Z",
  "lock_released_at": "2026-04-29T14:33:05Z"
}
```

`run_report.json` is written atomically at job end. It is the authoritative record of
what happened. Cloud Logging contains the full structured log; `run_report.json`
contains the summary the operator and agent need.

`run_id` is a UTC ISO timestamp (the job start time), not a directory name.
The Cloud Run execution ID is also captured in the structured log for correlation.

### Layer 3 — Knowledge service warning in the answer SSE event (user-visible)

The knowledge service reads `run_report.json` at startup and on each `/health` check.
If the report status is not `ok` and it is newer than the live index timestamp:

```
event: answer
data: {
  "answer": "...",
  "warning": "The knowledge base could not be updated on 2026-04-29. Some recent document changes may not be reflected."
}
```

This uses the existing `warning` field in the SSE answer event (already defined in
`ARCHITECTURE.md`) — no protocol change required. No admin UI required.

### Invariant: stale-good beats partial-unknown

`index_updated: false` means the **previous known-good index remains live**. The
knowledge service does not serve a partial corpus — it serves the last fully validated
corpus with a visible warning. This is a freshness degradation, not a correctness
degradation.

---

## Agent observability

The coding agent must never fabricate `gcloud logging read` queries. The agent's
entry point for pipeline state is a single script:

```bash
python3 tools/status.py           # current state summary
python3 tools/status.py --debug   # list available debug artifact runs in GCS
python3 tools/status.py --debug <run_id>  # download a specific debug run to /tmp/debug/
```

`tools/status.py` reads `run_report.json` from GCS, reads the manifest timestamp,
computes index age, and prints structured JSON. One command, complete state, no
GCP CLI knowledge required. This is documented in `src/ingestion/CLAUDE.md` as
THE way to check pipeline state.

Design principle: if information is needed by the agent to reason about pipeline
health, it belongs in `run_report.json`, not in Cloud Logging.

---

## Local workflow residue

The pipeline was adapted from a local CLI implementation. The following patterns are
inherited from that context and are incorrect or suboptimal in the GCP+Drive environment.
Each is treated as a dead end — see "Dead ends" below for rationale.

### Residue 1: Drive used as a processing artifact store

`upload_intermediaries()` uploads `01_baseline_md/`, `02_ai_cleaned/`, `03_chunked/`
and `multi_index.json` back into the Drive folder after each run. Drive is the
**source** of documents. Pipeline artifacts belong in GCS, not Drive.

**Replacement: GCS debug prefix.** When `DEBUG_MODE=true` (env var, default false),
after each step copy its output to:
```
gs://<GCS_BUCKET>/<SOURCE_ID>/debug/<run_id>/01_baseline_md/
gs://<GCS_BUCKET>/<SOURCE_ID>/debug/<run_id>/02_ai_cleaned/
gs://<GCS_BUCKET>/<SOURCE_ID>/debug/<run_id>/03_chunked/
```

Drive stays source-only unconditionally — no mode, no flag changes that invariant.
GCS is already authenticated, already in the stack, zero new permissions.
The agent reads any intermediary with one command:
```bash
python3 tools/status.py --debug <run_id>
# downloads to /tmp/debug/<run_id>/ for local inspection
```
GCS lifecycle rule: auto-delete the `debug/` prefix after 7 days.

Why not Drive? Drive is not a good interface for diffing `.md` files across runs.
Drive write access must then always be available, even in production runs. Drive
artifacts are not auto-cleaned. The agent cannot easily reach Drive files without
additional auth plumbing. GCS solves all of these cleanly.

### Residue 2: DOCX download → re-upload roundtrip for format conversion

Step 1 downloads each DOCX from Drive to local disk, then re-uploads it as a Google
Doc. The DOCX is already in Drive. The Drive API supports **server-side conversion**:

```python
drive.files().copy(
    fileId=source_docx_id,
    body={"name": stem, "mimeType": "application/vnd.google-apps.document",
          "parents": [folder_id]}
).execute()
```

No local I/O, no `download_docx_to_local()`, no `data/docx/` directory needed.

Related: `list_docx_files()` filters on DOCX MIME type only
(`application/vnd.openxmlformats-officedocument.wordprocessingml.document`). The
accepted file contract includes native Google Docs (`application/vnd.google-apps.document`),
which the current filter silently excludes. The filter must accept both MIME types.
For native Google Docs, Step 1 is a no-op — they are already in the right format.

### Residue 3: Numbered run directories and the `latest/` symlink

```
data/pipeline/YYYY-MM-DD_001/
  01_baseline_md/
  02_ai_cleaned/
  03_chunked/
data/pipeline/latest → YYYY-MM-DD_001/
```

This structure exists so a developer can inspect intermediaries between runs and
re-run individual steps (`--from-step2`, `--step3`). In Cloud Run:
- The container is ephemeral — these directories exist only during one execution.
- No human can inspect them mid-run.
- The `latest/` symlink is meaningless; it only points within the current container.
- Re-running from a specific step is not possible in a Cloud Run Job — the job always
  runs from the beginning.

**Replacement:** a single flat `/tmp/pipeline/` scratch directory per container
execution. No numbering, no symlink, no `_next_run_id()` counter.
The `run_id` concept is preserved as a metadata field in `run_report.json`,
derived from the Cloud Run execution ID (`CLOUD_RUN_EXECUTION` env var, available
in all Cloud Run Jobs).

### Residue 4: Change detection via `modifiedTime` when `md5Checksum` is available

`has_changes()` compares `modifiedTime` strings from Drive file metadata. `modifiedTime`
changes on any metadata edit (rename, permission change, comment) that does not affect
document content — triggering unnecessary rebuilds.

Drive's Files API already returns `md5Checksum` for user-uploaded binary files (DOCX)
in the same `files().list()` call — no download required. `md5Checksum` is the
authoritative content fingerprint. For native Google Docs (which have no binary
checksum), Drive exposes a `version` integer that increments only on content changes.

Change detection should use:
- DOCX files: `md5Checksum` from Drive metadata
- Native Google Docs: `version` from Drive metadata
- Both available via: `fields="files(id, name, modifiedTime, md5Checksum, mimeType, version)"`

The Phase 2 `pageToken` approach supersedes this entirely. But while Phase 1's
manifest-diff approach is in use, `md5Checksum`/`version` are the correct signals.

---

## Options considered per design dimension

### Trigger model

**Option A: Drive Push Notifications (webhooks)**
- How it works: `drive.changes.watch()` registers a channel pointing at a Cloud Run
  service endpoint. Drive sends POST within seconds of any change. Channel expires after
  7 days, requires renewal.
- Pros: True event-driven; sub-minute latency; zero unnecessary executions.
- Cons: Requires a new persistent Cloud Run service (webhook receiver); channel renewal
  logic; new IAM bindings (Scheduler → webhook service → Cloud Run Jobs Admin API).
- Estimated complexity: High — new service, new deployment, channel lifecycle management.

**Option B: Drive Changes API with `pageToken` (recommended for Phase 2)**
- How it works: Drive maintains a server-side change log. Job reads `pageToken` from
  GCS, calls `drive.changes.list(pageToken=...)`, processes only files that changed
  since last run. Scheduler interval: 15 minutes.
- Pros: True event detection (only actual changes trigger work); zero new services;
  `pageToken` persisted in GCS alongside manifest; simple implementation.
- Cons: Up to 15-minute latency from file change to index update (acceptable for a
  background pipeline).
- Estimated complexity: Low — replaces `list_docx_files()` + manifest diff with
  `changes.list()` + `pageToken`.

**Dead end: current 1-minute scheduler + full manifest diff.** Eliminated — produces
pile-up; wastes 60× per hour on no-op executions; full folder scan on every trigger.

### Build model

**Option A: Full rebuild on any change (current)**
- Eliminated: one modified doc → Gemini runs on all 6 docs. Expensive and slow.

**Option B: Incremental per-file rebuild (recommended)**
- How it works: Per-file content fingerprint in manifest (`md5Checksum` for DOCX,
  `version` for native Google Docs — both from Drive metadata, no download needed).
  Only files whose fingerprint changed run through Steps 3–5. Steps 1–2 are
  Drive-native and already idempotent. Step-2 baseline markdown cached in GCS per file.
  Index build always runs in full (partial index update is unsafe — routing index
  depends on the full document set).
- Pros: O(changed_files) cost instead of O(all_files); Gemini called only for actually
  changed documents; fingerprint from metadata requires no download.
- Cons: GCS baseline cache adds ~10KB per doc; download step at job start.
- Estimated complexity: Medium — `gcs_io.py` additions + `main.py` delta logic.

### Large document handling

**Option A: Skip (current)**
- Eliminated: silently omits AI header cleanup; quality degrades without any signal.

**Option B: Section-chunked AI processing (recommended)**
- How it works: Split at heading boundaries (`^#+ `). Each chunk ≤ 55K chars (≈14K
  tokens, within Gemini Flash Lite's 1M context). Process each chunk independently.
  Concatenate cleaned chunks.
- Output size guard: if `len(output) > 3 × len(input)`, reject output, log WARNING,
  use input as fallback. Catches the 1.6MB hallucination case (which was 18× input).
- Pros: All documents get AI cleanup; no quality cliff at 80K chars; hallucination
  guard prevents runaway output.
- Cons: N Gemini calls per large doc instead of 1. Cost is proportional, not amplified.
- Estimated complexity: Low — `_split_at_headings()` + `_process_large_doc()` in
  `step3_ai_cleanup.py`.

### Error handling

**Option A: Catch, log, continue (current)**
- Eliminated: pipeline completes "successfully" with partial corpus; missing documents
  are never flagged; index is silently degraded.

**Option B: Retry + raise (recommended)**
- How it works: 3 attempts with exponential backoff (5s/10s/20s) per file per step.
  On exhaustion: raise `StepError(step, stem, cause)`. `main.py` catches at top level,
  logs ERROR with full traceback, writes `run_report.json`, exits non-zero. Cloud Run
  records execution as FAILED. Cloud Monitoring alert fires.
- **Partial corpus policy:** Either all documents succeed or the run fails. Manifest
  and index updated only on full success. Previous good index remains live.
- Estimated complexity: Low — retry wrapper + exception hierarchy.

### Advisory lock — SIGKILL safety

**Current:** `finally` block attempts delete. SIGKILL bypasses `finally`. TTL is the
only protection. Race condition: two jobs can both see an expired lock and both
overwrite it.

**Fix:** GCS conditional operations.
- Acquire: `blob.upload_from_string(payload, if_generation_match=0)` — creates only,
  never overwrites. Raises `PreconditionFailed` if another job acquired it simultaneously.
- Release: `blob.delete(if_generation_match=<recorded_generation>)` — only deletes
  our own lock, not a new lock created by a subsequent job after SIGKILL.

### Multi-tenant

**Option A: One Cloud Run Job per tenant (current model extended)**
- Each tenant = separate job deployment with different `DRIVE_FOLDER_ID` + `SOURCE_ID`
  env vars. Scheduler fires each job independently.
- Pros: Complete isolation; one tenant's failure doesn't affect others.
- Cons: Operational overhead scales linearly with tenants; duplicated infrastructure.

**Option B: Tenant registry in GCS + single job processes all tenants (recommended)**
- Registry: `gs://<BUCKET>/tenants.json` — list of `{tenant_id, drive_folder_id,
  enabled}`. Admin service (when implemented) is the sole writer.
- Job reads registry at startup, processes enabled tenants sequentially, per-tenant
  advisory lock and per-tenant `run_report.json`.
- Per-tenant GCS layout: `gs://<BUCKET>/{tenant_id}/` — manifest, index, baseline
  cache, lock, run_report, debug/.
- Migration: `tech_poc` becomes first entry; existing GCS paths unchanged.
- Pros: Single deployment; tenant config in data (not infrastructure); scales without
  new Cloud Run Jobs.
- Cons: A pathologically slow tenant delays subsequent tenants (mitigated by per-file
  incremental).
- Estimated complexity: Medium — new `tenants.py`, `main.py` iteration loop, GCS
  layout update.

---

## Dead ends

**Personal OAuth for Drive access in Cloud Run:** Token refresh requires a writable
credential store. Secret Manager mounts are read-only. When `_save(creds)` failed
inside the except block, the code fell through to `run_local_server()` which hung
indefinitely. Personal OAuth is fundamentally incompatible with headless Cloud Run.
Replaced by service account ADC + Drive folder sharing.

**GCS-backed OAuth token store:** Still personal OAuth at heart. If the token expires,
a human must re-authorize. Not a production architecture.

**`MAX_DOCUMENT_SIZE_FOR_AI = 400_000` (original):** Allowed EN_Policies_5 (378K
chars) into Gemini with no timeout on `requests.post()`. Resulted in indefinite hang.
Later lowered to 80_000 (skip). Correct fix is chunked processing.

**`subprocess.run([sys.executable, "src/ingestion/build_index.py"])` for index
build:** Loses tracing context, requires correct working directory, obscures errors.
Should be `await build_all(corpus_dir, index_dir)` as a direct function call.

**`latest/` symlink as pipeline state:** Cloud Run containers have no persistent
filesystem. The symlink only exists for the duration of one container instance. Any
design that relies on `data/pipeline/latest/` existing from a previous run is broken
in Cloud Run. Replaced by `/tmp/pipeline/` flat scratch space per container execution.

**`en_*.md` file filter in `build_index.py`:** Designed for manually-named local
files. Drive-native filenames (`EN_Policies_1. CHILD PROTECTION.md`) don't match.
Fixed in last session; requires commit.

**Catch-log-continue error handling:** Pipeline exits 0 on per-file failures; degraded
index is served with no signal. Eliminated in favour of abort-and-report.

**Fabricated `gcloud` queries for agent observability:** Agent cannot reliably
construct Cloud Logging filter syntax. Replaced by `tools/status.py` + `run_report.json`
as the single authoritative status entry point.

**`upload_intermediaries()` writing pipeline artifacts to Drive:** Drive is the source
of documents, not a sink for pipeline artifacts. Pollutes the administrator's Drive
folder with uneditable `.md` files. No auto-cleanup. Replaced by GCS debug prefix
(`gs://<bucket>/<source_id>/debug/<run_id>/`) controlled by `DEBUG_MODE` env var,
with 7-day lifecycle auto-delete.

**DOCX download → re-upload roundtrip for format conversion:** `download_docx_to_local()`
downloads the DOCX from Drive to local disk; Step 1 then re-uploads it as a Google Doc.
The DOCX is already in Drive. Drive's `files().copy()` with
`mimeType=application/vnd.google-apps.document` performs server-side conversion
with no local I/O. Eliminates `data/docx/` directory and the download step entirely.

**DOCX-only MIME type filter:** `list_docx_files()` filters on DOCX MIME type only,
silently excluding native Google Docs from the corpus. If a school administrator
creates a document natively in Google Docs (the natural workflow), the pipeline ignores
it. Filter must accept both
`application/vnd.openxmlformats-officedocument.wordprocessingml.document` and
`application/vnd.google-apps.document`. For native Google Docs, Step 1 is a no-op.

**Numbered run directories (`YYYY-MM-DD_NNN/`) and `_next_run_id()` counter:**
Designed for local multi-run inspection. In Cloud Run, the container is ephemeral
and only ever runs one job. The numbering, the counter, and the symlink are all
infrastructure for a workflow that cannot exist in Cloud Run. Replaced by
`/tmp/pipeline/` flat scratch space; `run_id` is the Cloud Run execution timestamp,
stored as metadata in `run_report.json` only.

**Step-resume CLI flags (`--from-step2`, `--step3`, etc.):** Useful locally when
intermediaries persist on disk between re-runs. In Cloud Run, `/tmp/` is cleared
on each container start — there is nothing to resume from. These flags are dead code
in the Cloud Run Job context. The job always runs from Step 1.

**`modifiedTime` for change detection:** Changes on any metadata edit (rename,
permission change, comment) not just content changes — triggering unnecessary
rebuilds. Drive already returns `md5Checksum` (DOCX) and `version` (native Google
Docs) in the same `files().list()` API call with no download required. These are
the correct content-change signals.

---

## Decision (pending Q2–Q7 answers)

**Trigger model:** Drive Changes API with `pageToken` (Phase 2). Current scheduler
polling (Phase 1) with 15-minute interval.

**Build model:** Incremental per-file. Fingerprint = `md5Checksum` (DOCX) or
`version` (native Google Doc), both from Drive metadata. GCS baseline cache for
Step-2 outputs.

**Large docs:** Section-chunked Gemini calls + output size guard. No skipping.

**Error handling:** Retry + raise + abort-and-report. Partial corpus = run failure.
Previous good index remains live.

**Observability:** Structured JSON logging (Q1 answered). `run_report.json` is the
agent and ops entry point. `tools/status.py` is the one-command status check.

**Error surfacing:** Three layers — Drive comment (Layer 1, pending Q5), GCS
`run_report.json` (Layer 2, always), knowledge service SSE warning (Layer 3, always).

**Debug artifacts:** GCS debug prefix (`debug/<run_id>/`) controlled by `DEBUG_MODE`
env var. Drive stays source-only unconditionally. 7-day auto-delete via GCS lifecycle.

**Multi-tenant:** GCS tenant registry. Single job, sequential tenant processing.

**Advisory lock:** `if_generation_match` on both acquire and release.

**Input file contract:** Validated pre-flight before Steps 3–5. Violation = reject
with typed error + actionable message. No silent skipping.

**Accepted MIME types:** DOCX and native Google Doc. For native Google Docs, Step 1
is a no-op.

**Step 1 implementation:** Drive server-side `files().copy()` with mimeType conversion.
No local DOCX download. `data/docx/` directory eliminated.

**Scratch space:** `/tmp/pipeline/` flat directory per container execution. No
numbered subdirectories, no symlink. `run_id` = UTC ISO timestamp of job start,
stored in `run_report.json` only.

---

## Implementation sequence

### Phase 1 — Correctness + Contract (immediate)

1. Commit uncommitted files from previous session: `step3_ai_cleanup.py`, `config.py`,
   `build_index.py`
2. Delete dead code: `auth_oauth.py`, `OAUTH_TOKEN_PATH` from `config.py`,
   `upload_intermediaries()`, `download_docx_to_local()`, `_next_run_id()`,
   `_setup_run_dir()`, `_update_symlink()`, `data/docx/` references,
   step-resume CLI flags (`--from-step2`, `--step3`, etc.)
3. Replace `subprocess.run(build_index.py)` with `await build_all()` function call
4. Fix Step 1: Drive server-side `files().copy()` with mimeType conversion; no
   local download
5. Fix MIME filter: `list_accepted_files()` accepts both DOCX and native Google Doc
   MIME types; native Google Docs skip Step 1
6. Fix change detection: use `md5Checksum` (DOCX) and `version` (native Google Doc)
   from Drive metadata; add both fields to `files().list()` call
7. Replace `data/pipeline/YYYY-MM-DD_NNN/` with `/tmp/pipeline/` flat scratch space;
   `run_id` = `datetime.utcnow().isoformat()` stored in `run_report.json` only
8. Fix advisory lock: `if_generation_match` on acquire + release
9. Structured JSON logging: replace all `print()` across job + pipeline steps
10. `ValidationError` hierarchy: one subclass per `error_type` in the rejection table;
    each carries `name`, `error_type`, `error_detail`, `actionable`, `drive_url`
11. Pre-flight validation pass: run all files through Steps 1–2, collect all
    `ValidationError`s, abort before Step 3 if any file fails
12. Error handling: retry wrapper (3× exponential backoff) + `StepError` hierarchy +
    top-level catch that writes `run_report.json` and exits non-zero
13. `run_report.json` writer: called on every exit path (success and failure); schema
    as defined in "Error surface design" above
14. GCS debug prefix: when `DEBUG_MODE=true`, copy each step's `/tmp/pipeline/` output
    to `gs://<bucket>/<source_id>/debug/<run_id>/` after that step completes;
    add 7-day lifecycle rule to `setup_gcp.sh`
15. `tools/status.py`: reads `run_report.json`, prints structured summary; `--debug`
    flag lists and downloads debug run artifacts; document in `src/ingestion/CLAUDE.md`
16. Layer 1 (Drive comment): write comment on validation failure; check for existing
    ImagineBot comment before adding; update timestamp if present (pending Q5)
17. Layer 3 (knowledge service warning): read `run_report.json` at startup and on
    `/health`; emit `warning` in SSE answer if status ≠ `ok` and report is newer than
    live index
18. Large doc handling: `_split_at_headings()` + `_process_large_doc()` + output size
    guard (reject if output > 3× input)
19. Cost tracking: token accumulation per run, `MAX_RUN_COST_USD` abort threshold
20. Cloud Monitoring alert on job failure + GCP Budget Alert (in `setup_gcp.sh`)
21. Update `src/ingestion/ARCHITECTURE.md` and `CLAUDE.md` to reflect all of the above

### Phase 2 — Event detection + incremental

1. Drive Changes API: `pageToken` in GCS, `drive.changes.list()` replacing manifest
   diff
2. GCS baseline cache for Step-2 outputs (`baseline/{stem}.md`)
3. `main.py` delta logic: only process files whose fingerprint changed through Steps
   3–5; fingerprint already captured in Phase 1 item 6
4. Cloud Scheduler interval → 15 minutes

### Phase 3 — Multi-tenant

1. `tenants.py`: `TenantConfig`, `load_tenants()`, `save_tenants()`
2. Initial `tenants.json` with `tech_poc` entry written by `setup_gcp.sh`
3. Per-tenant GCS prefix, advisory lock, `run_report.json`, and `debug/` prefix
4. `main.py`: iterate tenants, per-tenant pipeline execution
5. Remove `DRIVE_FOLDER_ID` and `SOURCE_ID` from job env vars

### Phase 4 — Webhooks (future sprint)

- Drive Push Notifications receiver (new Cloud Run service)
- Channel renewal via weekly Scheduler
- Eliminates Scheduler-triggered polling entirely
