#!/usr/bin/env bash
set -euo pipefail

PROJECT=img-dev-490919
REGION=europe-west1
REPO=europe-west1-docker.pkg.dev/${PROJECT}/services
IMAGE=${REPO}/knowledge:latest
SERVICE=knowledge
SA=knowledge-sa@${PROJECT}.iam.gserviceaccount.com

cd "$(dirname "$0")"

echo "=== Granting IAM roles to knowledge-sa ==="
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/aiplatform.user" \
  --condition=None

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.user" \
  --condition=None

echo "=== Building image ==="
docker build -t "${IMAGE}" .

echo "=== Pushing image ==="
docker push "${IMAGE}"

echo "=== Deploying to Cloud Run ==="
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --service-account="${SA}" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=0 \
  --max-instances=3 \
  --memory=512Mi \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},VERTEX_AI_LOCATION=${REGION}"

echo "=== Done ==="
gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --format="value(status.url)"
