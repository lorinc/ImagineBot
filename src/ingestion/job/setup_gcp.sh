#!/usr/bin/env bash
# One-time idempotent GCP setup for the ingestion job.
# Safe to re-run — all steps tolerate already-existing resources.
# Run from repo root: bash src/ingestion/job/setup_gcp.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT=img-dev-490919
REGION=europe-west1
BUCKET=img-dev-index
JOB_SA=ingestion-job@${PROJECT}.iam.gserviceaccount.com
KNOWLEDGE_SA=knowledge-sa@${PROJECT}.iam.gserviceaccount.com
SCHEDULER_SA=scheduler-invoker@${PROJECT}.iam.gserviceaccount.com

bash tools/preflight-check.sh

echo ""
echo "=== 1. GCS bucket ==="
gcloud storage buckets create "gs://${BUCKET}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --uniform-bucket-level-access 2>&1 | grep -v "already exists" || true
echo "gs://${BUCKET} ready"

echo ""
echo "=== 2. Service account: ingestion-job ==="
gcloud iam service-accounts create ingestion-job \
  --project="${PROJECT}" \
  --display-name="Ingestion Job" 2>&1 | grep -v "already exists" || true
echo "${JOB_SA} ready"

echo ""
echo "=== 3. Grant ingestion-job: storage.objectAdmin on ${BUCKET} ==="
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/storage.objectAdmin"

echo ""
echo "=== 4. Grant knowledge-sa: storage.objectViewer on ${BUCKET} ==="
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${KNOWLEDGE_SA}" \
  --role="roles/storage.objectViewer"

echo ""
echo "=== 5-7. Secret: ingestion-oauth-token ==="
gcloud secrets create ingestion-oauth-token \
  --project="${PROJECT}" \
  --replication-policy=automatic 2>&1 | grep -v "already exists" || true

gcloud secrets versions add ingestion-oauth-token \
  --project="${PROJECT}" \
  --data-file="oauth/token.pickle"
echo "ingestion-oauth-token version added"

gcloud secrets add-iam-policy-binding ingestion-oauth-token \
  --project="${PROJECT}" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/secretmanager.secretAccessor"

echo ""
echo "=== 8-10. Secret: ingestion-gemini-key ==="
GEMINI_API_KEY=$(python3 - <<'EOF'
import re, pathlib
text = pathlib.Path('credentials').read_text()
text = re.sub(r'\n\s+', '', text)
for line in text.splitlines():
    if line.startswith('GEMINI_API_KEY='):
        print(line.split('=', 1)[1].strip())
        break
EOF
)

gcloud secrets create ingestion-gemini-key \
  --project="${PROJECT}" \
  --replication-policy=automatic 2>&1 | grep -v "already exists" || true

printf '%s' "${GEMINI_API_KEY}" | gcloud secrets versions add ingestion-gemini-key \
  --project="${PROJECT}" \
  --data-file=-
echo "ingestion-gemini-key version added"

gcloud secrets add-iam-policy-binding ingestion-gemini-key \
  --project="${PROJECT}" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/secretmanager.secretAccessor"

echo ""
echo "=== 11. Service account: scheduler-invoker ==="
gcloud iam service-accounts create scheduler-invoker \
  --project="${PROJECT}" \
  --display-name="Cloud Scheduler Invoker" 2>&1 | grep -v "already exists" || true
echo "${SCHEDULER_SA} ready"

echo ""
echo "=== 12. Grant scheduler-invoker: roles/run.invoker on project ==="
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --role="roles/run.invoker" \
  --condition=None

echo ""
echo "=== Setup complete ==="
