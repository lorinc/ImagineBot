#!/usr/bin/env bash
# Build, push, and create/update the ingestion Cloud Run Job + Cloud Scheduler.
# Run from repo root: bash src/ingestion/job/deploy_job.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT=img-dev-490919
REGION=europe-west1
REGISTRY=europe-west1-docker.pkg.dev/${PROJECT}/services
IMAGE=${REGISTRY}/ingestion-job:latest
JOB_NAME=ingestion-poll
JOB_SA=ingestion-job@${PROJECT}.iam.gserviceaccount.com
SCHEDULER_SA=scheduler-invoker@${PROJECT}.iam.gserviceaccount.com

bash tools/preflight-check.sh

echo ""
echo "=== Building image ==="
docker build -f src/ingestion/job/Dockerfile -t "${IMAGE}" .

echo ""
echo "=== Pushing image ==="
docker push "${IMAGE}"

echo ""
echo "=== Creating/updating Cloud Run Job ==="
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT}" &>/dev/null; then
  gcloud run jobs update "${JOB_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT}" \
    --service-account="${JOB_SA}" \
    --memory=512Mi \
    --task-timeout=3600s \
    --set-env-vars="SOURCE_ID=tech_poc,DRIVE_FOLDER_ID=1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3,GCS_BUCKET=img-dev-index" \
    --set-secrets="GEMINI_API_KEY=ingestion-gemini-key:latest" \
    --clear-volumes --clear-volume-mounts
else
  gcloud run jobs create "${JOB_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT}" \
    --service-account="${JOB_SA}" \
    --memory=512Mi \
    --task-timeout=3600s \
    --set-env-vars="SOURCE_ID=tech_poc,DRIVE_FOLDER_ID=1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3,GCS_BUCKET=img-dev-index" \
    --set-secrets="GEMINI_API_KEY=ingestion-gemini-key:latest"
fi

echo ""
echo "=== Creating Cloud Scheduler job (1-minute poll) ==="
gcloud scheduler jobs create http ingest-poll-1min \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --schedule="* * * * *" \
  --uri="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB_NAME}:run" \
  --message-body='{}' \
  --oauth-service-account-email="${SCHEDULER_SA}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" 2>&1 | grep -v "already exists" || true

echo ""
echo "=== Deploy complete ==="
echo "Smoke test:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT}"
