#!/usr/bin/env bash
# Delete all Cloud Run revisions that are not currently serving traffic.
# Run automatically at the end of each service's deploy.sh.
# Usage: tools/cleanup_revisions.sh [--dry-run]

set -euo pipefail

PROJECT=img-dev-490919
REGION=europe-west1
SERVICES=(knowledge gateway channel-web)
DRY_RUN=${1:-}

for SERVICE in "${SERVICES[@]}"; do
    echo "=== $SERVICE ==="

    # Revisions currently allocated traffic (may be more than one during a rollout)
    ACTIVE=$(gcloud run services describe "$SERVICE" \
        --project "$PROJECT" \
        --region "$REGION" \
        --format="value(status.traffic[].revisionName)" 2>/dev/null \
        | tr ';' '\n' | grep -v '^$')

    ALL=$(gcloud run revisions list \
        --service "$SERVICE" \
        --project "$PROJECT" \
        --region "$REGION" \
        --format="value(metadata.name)" 2>/dev/null)

    for REV in $ALL; do
        if echo "$ACTIVE" | grep -qx "$REV"; then
            echo "  keep:   $REV (active)"
        elif [[ "$DRY_RUN" == "--dry-run" ]]; then
            echo "  would delete: $REV"
        else
            echo "  delete: $REV"
            gcloud run revisions delete "$REV" \
                --project "$PROJECT" \
                --region "$REGION" \
                --quiet
        fi
    done
done
