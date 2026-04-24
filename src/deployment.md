# Deployment

Each service deploys independently via `src/<service>/deploy.sh`, run from the repo root.
There is no deploy-all script and no coordination between services.

## Ordering constraint

Services that call other services over HTTP have the peer URL hardcoded in their deploy script.
When a breaking API change spans two services, deploy the provider first, then the consumer.
There is no health-check gate between steps — it is manual.

## What each script does

1. Re-applies IAM bindings (idempotent)
2. Builds and pushes a Docker image
3. Deploys a new Cloud Run revision (zero-downtime rolling)

## Rollback

Cloud Run keeps previous revisions. To roll back:

```bash
gcloud run services update-traffic <service> \
  --to-revisions=<revision-id>=100 \
  --region=europe-west1 --project=img-dev-490919
```

List revisions: `gcloud run revisions list --service=<service> --region=europe-west1`

## Limitations

- Runs from a developer's local machine — requires active `gcloud` credentials
- No rollback automation; no post-deploy smoke test gate
- No staging → production promotion path yet (all scripts target `img-dev`)
