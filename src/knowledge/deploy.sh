#!/usr/bin/env bash
set -euo pipefail

PROJECT=img-dev-490919
REGION=europe-west1
REPO=europe-west1-docker.pkg.dev/${PROJECT}/services
IMAGE=${REPO}/knowledge:latest
SERVICE=knowledge
SA=knowledge-sa@${PROJECT}.iam.gserviceaccount.com

# Build context is repo root so Dockerfile can COPY data/index/ into the image.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== Granting IAM roles to knowledge-sa ==="
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/aiplatform.user" \
  --condition=None

# datastore.user retained: reuse when vector-based cache layer is added.
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.user" \
  --condition=None

echo "=== Building image (context: ${REPO_ROOT}) ==="
docker build -t "${IMAGE}" -f "${REPO_ROOT}/src/knowledge/Dockerfile" "${REPO_ROOT}"

echo "=== Pushing image ==="
docker push "${IMAGE}"

echo "=== Deploying to Cloud Run ==="
MODULE_GIT_REV=$(git log -1 --format="%H" -- src/knowledge/)
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --service-account="${SA}" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=0 \
  --max-instances=3 \
  --memory=1Gi \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},VERTEX_AI_LOCATION=${REGION},KNOWLEDGE_INDEX_PATH=/app/index/multi_index.json,MODULE_GIT_REV=${MODULE_GIT_REV}"

echo "=== Done ==="
gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --format="value(status.url)"
