#!/usr/bin/env bash
# Deploy gateway to Cloud Run (img-dev).
# Run from repo root: bash src/gateway/deploy.sh
# After this script completes, run: bash src/channel_web/deploy.sh

set -euo pipefail

PROJECT=img-dev-490919
REGION=europe-west1
REGISTRY=${REGION}-docker.pkg.dev/${PROJECT}/services
IMAGE=${REGISTRY}/gateway
SA=gateway-sa@${PROJECT}.iam.gserviceaccount.com
CHANNEL_WEB_SA=channel-web-sa@${PROJECT}.iam.gserviceaccount.com
KNOWLEDGE_SERVICE_URL=https://knowledge-jeyczovqfa-ew.a.run.app

echo "=== Ensuring gateway-sa service account ==="
gcloud iam service-accounts describe "${SA}" --project="${PROJECT}" 2>/dev/null \
  || gcloud iam service-accounts create gateway-sa \
       --display-name="Gateway service" \
       --project="${PROJECT}"

echo "=== Granting IAM roles to gateway-sa ==="
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/aiplatform.user" \
  --condition=None

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.user" \
  --condition=None

# Allow gateway-sa to call knowledge service
gcloud run services add-iam-policy-binding knowledge \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/run.invoker"

echo "=== Building image (context: repo root) ==="
docker build -t "${IMAGE}:latest" -f src/gateway/Dockerfile .

echo "=== Pushing image ==="
docker push "${IMAGE}:latest"

echo "=== Deploying to Cloud Run ==="
MODULE_GIT_REV=$(git log -1 --format="%H" -- src/gateway/)
gcloud run deploy gateway \
  --image="${IMAGE}:latest" \
  --platform=managed \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --service-account="${SA}" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=0 \
  --max-instances=2 \
  --memory=256Mi \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},VERTEX_AI_LOCATION=${REGION},KNOWLEDGE_SERVICE_URL=${KNOWLEDGE_SERVICE_URL},MODULE_GIT_REV=${MODULE_GIT_REV}"

echo "=== Granting channel-web-sa invoker on gateway ==="
gcloud run services add-iam-policy-binding gateway \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${CHANNEL_WEB_SA}" \
  --role="roles/run.invoker"

echo "=== Done ==="
GATEWAY_URL=$(gcloud run services describe gateway \
  --region="${REGION}" --project="${PROJECT}" \
  --format="value(status.url)")
echo "Gateway URL: ${GATEWAY_URL}"

echo "=== Cleaning up old revisions ==="
bash "$(dirname "$0")/../../tools/cleanup_revisions.sh"

echo ""
echo "Next step: bash src/channel_web/deploy.sh"
