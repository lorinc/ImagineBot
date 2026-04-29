# Deployment Plan — Item R: Drive Polling Job
# Written: 2026-04-28. Supersedes the GCP setup sections of .claude/PLAN_R.md.

## Canonical constants

```
PROJECT_ID  = img-dev-490919      # GCP project ID (name: img-dev)
REGION      = europe-west1
REGISTRY    = europe-west1-docker.pkg.dev/img-dev-490919/services
JOB_SA      = ingestion-job@img-dev-490919.iam.gserviceaccount.com
KNOWLEDGE_SA= knowledge-sa@img-dev-490919.iam.gserviceaccount.com
SCHEDULER_SA= scheduler-invoker@img-dev-490919.iam.gserviceaccount.com
BUCKET      = img-dev-index
JOB_NAME    = ingestion-poll
IMAGE       = europe-west1-docker.pkg.dev/img-dev-490919/services/ingestion-job:latest
```

These values are hardcoded in every script below. Nothing reads from `gcloud config`.

---

## Credentials and secrets inventory

| Credential | Where it lives locally | How it gets into Cloud Run |
|---|---|---|
| OAuth token (`token.pickle`) | `oauth/token.pickle` | Secret Manager: `ingestion-oauth-token` → volume mount at `/secrets/oauth_token/token.pickle` |
| Gemini API key | `credentials` file, key `GEMINI_API_KEY` | Secret Manager: `ingestion-gemini-key` → env var `GEMINI_API_KEY` |
| Google OAuth client ID | `credentials` file, key `OAUTH_CLIENT_ID` | Already in `channel_web` deploy — not needed by ingestion job |

The ingestion job does NOT use Vertex AI ADC (no `google-cloud-aiplatform`). Step 3 calls
Gemini via REST API using `GEMINI_API_KEY`. Step 1–2 use personal OAuth via `token.pickle`.

---

## Scripts to create

### 1. `tools/preflight-check.sh`
Adapted from `CascadeProjects/weighin.link/infrastructure/scripts/preflight-check.sh`.
Run before every deploy and setup. Hard-codes the expected project ID — catches wrong
gcloud config before any resources are touched.

Checks:
- `gcloud auth list` — at least one credentialed account
- `gcloud projects describe img-dev-490919` — project is accessible
- `docker info` — Docker daemon is running
- `git status --porcelain` — warn (not block) if uncommitted changes

Does NOT read `gcloud config get-value project`. Verifies the project directly.

### 2. `src/ingestion/job/setup_gcp.sh`
One-time, idempotent. Creates all GCP resources. Run once before first deploy.
Sources `tools/preflight-check.sh` first.

Sequence:
```
1. Create GCS bucket gs://img-dev-index in europe-west1
2. Create service account ingestion-job@img-dev-490919.iam.gserviceaccount.com
3. Grant ingestion-job SA: storage.objectAdmin on gs://img-dev-index
4. Grant knowledge-sa SA: storage.objectViewer on gs://img-dev-index
5. Create Secret Manager secret: ingestion-oauth-token
6. Upload oauth/token.pickle as first version of ingestion-oauth-token
7. Grant ingestion-job SA: secretmanager.secretAccessor on ingestion-oauth-token
8. Create Secret Manager secret: ingestion-gemini-key
9. Read GEMINI_API_KEY from credentials file, store as first version of ingestion-gemini-key
10. Grant ingestion-job SA: secretmanager.secretAccessor on ingestion-gemini-key
11. Create service account scheduler-invoker@img-dev-490919.iam.gserviceaccount.com
12. Grant scheduler-invoker SA: roles/run.invoker on project img-dev-490919
```

All steps use `|| echo "already exists"` or `2>/dev/null` so re-runs are safe.
GEMINI_API_KEY is read from the local `credentials` file via python3 (same pattern
as `channel_web/deploy.sh` reads OAUTH_CLIENT_ID) — never hard-coded in the script.

### 3. `src/ingestion/job/deploy_job.sh`
Build, push, and create/update the Cloud Run Job + Cloud Scheduler.
Sources `tools/preflight-check.sh` first.
Follows exact pattern of existing `src/*/deploy.sh` scripts.

Sequence:
```
1. preflight-check.sh
2. docker build -f src/ingestion/job/Dockerfile -t ${IMAGE} .
3. docker push ${IMAGE}
4. gcloud run jobs create ingestion-poll ... || gcloud run jobs update ingestion-poll ...
5. gcloud scheduler jobs create http ingest-poll-1min ... || echo "already exists"
```

Cloud Run Job env vars:
```
SOURCE_ID=tech_poc
DRIVE_FOLDER_ID=1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3
GCS_BUCKET=img-dev-index
OAUTH_TOKEN_PATH=/secrets/oauth_token/token.pickle
```

Cloud Run Job secrets:
```
/secrets/oauth_token/token.pickle = ingestion-oauth-token:latest   (volume mount)
GEMINI_API_KEY                    = ingestion-gemini-key:latest     (env var)
```

Note on secret mount path: ARCHITECTURE.md requires each secret in its own parent
directory. `token.pickle` is at `/secrets/oauth_token/token.pickle`, not
`/secrets/token.pickle`.

### 4. Update `src/knowledge/deploy.sh`
Add `INDEX_GCS_PATH=gs://img-dev-index/tech_poc` to the `--set-env-vars` line of
`gcloud run deploy knowledge`. Knowledge SA already has objectViewer granted by
`setup_gcp.sh` (step 4 above).

---

## Execution order

```
Session: GCP setup + deploy

Step 1 — Run setup_gcp.sh (one-time):
  bash src/ingestion/job/setup_gcp.sh

Step 2 — Deploy ingestion job:
  bash src/ingestion/job/deploy_job.sh

Step 3 — Redeploy knowledge service (adds INDEX_GCS_PATH + google-cloud-storage):
  bash src/knowledge/deploy.sh

Step 4 — Smoke test:
  a. Drop or modify a DOCX in Drive folder 1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3
  b. gcloud run jobs execute ingestion-poll --region europe-west1 --project img-dev-490919
  c. Wait for job to complete
  d. Ask the knowledge service a question from the new document
```

---

## Open issues in PLAN_R.md to fix

`PLAN_R.md` and `SESSION.md` use `img-dev` as the project ID in all gcloud commands.
These must be updated to `img-dev-490919` before the scripts are written.

---

## Files changed by this plan

| File | Action |
|---|---|
| `tools/preflight-check.sh` | Create |
| `src/ingestion/job/setup_gcp.sh` | Create |
| `src/ingestion/job/deploy_job.sh` | Create |
| `src/knowledge/deploy.sh` | Edit — add INDEX_GCS_PATH to env vars |
| `.claude/PLAN_R.md` | Edit — fix project ID |
| `.claude/SESSION.md` | Edit — fix project ID |
