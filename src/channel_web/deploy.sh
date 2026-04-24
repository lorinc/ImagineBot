#!/usr/bin/env bash
# Deploy channel_web to Cloud Run (img-dev).
# Run from repo root: bash src/channel_web/deploy.sh

set -euo pipefail

PROJECT=img-dev-490919
REGION=europe-west1
REGISTRY=${REGION}-docker.pkg.dev/${PROJECT}/services
IMAGE=${REGISTRY}/channel-web
SA=channel-web-sa@${PROJECT}.iam.gserviceaccount.com

# Load OAUTH_CLIENT_ID from credentials file (continuation-line aware)
OAUTH_CLIENT_ID=$(python3 - <<'EOF'
import re, pathlib
text = pathlib.Path('credentials').read_text()
text = re.sub(r'\n\s+', '', text)   # join continuation lines
for line in text.splitlines():
    if line.startswith('OAUTH_CLIENT_ID='):
        print(line.split('=', 1)[1].strip())
        break
EOF
)

GATEWAY_SERVICE_URL=https://gateway-jeyczovqfa-ew.a.run.app

echo "Building image..."
docker build -t "${IMAGE}:latest" src/channel_web/

echo "Pushing image..."
docker push "${IMAGE}:latest"

echo "Deploying to Cloud Run..."
MODULE_GIT_REV=$(git log -1 --format="%H" -- src/channel_web/)
gcloud run deploy channel-web \
  --image="${IMAGE}:latest" \
  --platform=managed \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --service-account="${SA}" \
  --allow-unauthenticated \
  --set-env-vars="GATEWAY_SERVICE_URL=${GATEWAY_SERVICE_URL},GOOGLE_CLIENT_ID=${OAUTH_CLIENT_ID},MODULE_GIT_REV=${MODULE_GIT_REV}" \
  --set-secrets="/secrets/allowed_emails/ALLOWED_EMAILS=ALLOWED_EMAILS:latest" \
  --memory=256Mi \
  --min-instances=0 \
  --max-instances=2

echo "Done."
gcloud run services describe channel-web \
  --region="${REGION}" --project="${PROJECT}" \
  --format="value(status.url)"
