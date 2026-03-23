# .github/ — Claude Code context

## Pipeline overview
```
ci.yml              Runs on every push to any branch.
                    Blocks merge if it fails (branch protection enforced on main).
                    Steps: lint → contracts → unit → integration (with emulator)

deploy-staging.yml  Runs on merge to main.
                    Builds images → pushes to Artifact Registry → deploys each service
                    to Cloud Run → runs smoke tests → opens GitHub issue on failure.

deploy-production.yml  Manual trigger only. Requires explicit approval.
                       Same pipeline as staging, targets production project.

[rollback.yml]         Optional. Redeploys a specific revision by commit hash.
```

## Multi-service build strategy
Each service has its own Dockerfile and is deployed as a separate Cloud Run service.
CI builds only the services whose `src/[service]/` directory has changed (path filters).
This keeps build times reasonable as the project grows.

```yaml
# Path filter pattern in ci.yml:
on:
  push:
    paths:
      - 'src/gateway/**'
      - 'tests/**'
```

## GCP authentication (Workload Identity Federation — no stored credentials)
One-time setup. After this, GitHub Actions authenticates to GCP with short-lived tokens.
No service account key files. No credentials in GitHub Secrets.

```bash
# Run once from a GCP admin account:

# 1. Create Workload Identity Pool
gcloud iam workload-identity-pools create "github-pool" \
  --project=[PROJECT_ID] \
  --location="global" \
  --display-name="GitHub Actions Pool"

# 2. Create OIDC provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=[PROJECT_ID] \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# 3. Grant the pool permission to impersonate the CI service account
gcloud iam service-accounts add-iam-policy-binding \
  [SA_NAME]@[PROJECT_ID].iam.gserviceaccount.com \
  --project=[PROJECT_ID] \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/[PROJECT_NUMBER]/locations/global/workloadIdentityPools/github-pool/attribute.repository/[GITHUB_ORG]/[REPO_NAME]"

# 4. Get the provider resource name (needed for workflow yaml)
gcloud iam workload-identity-pools providers describe "github-provider" \
  --project=[PROJECT_ID] --location="global" \
  --workload-identity-pool="github-pool" \
  --format="value(name)"
```

GitHub Secrets to set (identifiers only — not credentials):
- `WIF_PROVIDER` — provider resource name from step 4
- `WIF_SERVICE_ACCOUNT` — `[SA_NAME]@[PROJECT_ID].iam.gserviceaccount.com`
- `STAGING_URL` — base URL of staging gateway (for smoke tests)

Workflow auth block (paste into every workflow that needs GCP):
```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
    service_account: ${{ secrets.WIF_SERVICE_ACCOUNT }}
```

## Service account permissions (minimum)
```
roles/run.admin               Deploy Cloud Run services
roles/storage.admin           Push to Artifact Registry
roles/iam.serviceAccountUser  Act as the runtime service account
roles/datastore.user          Firestore read/write (for integration tests)
```

## CI workflow pattern (ci.yml)
```yaml
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Start Firestore emulator
        run: |
          gcloud emulators firestore start --host-port=localhost:8080 &
          sleep 3

      - name: Lint
        run: ruff check src/

      - name: Contract tests
        run: pytest tests/contracts/ -v

      - name: Unit tests
        run: pytest tests/unit/ -v

      - name: Integration tests
        env:
          FIRESTORE_EMULATOR_HOST: localhost:8080
          GCP_PROJECT_ID: test-project
        run: pytest tests/integration/ -v
```

## Branch protection (set in GitHub repo settings → Branches)
```
Branch: main
  Require pull request before merging: YES
  Require status checks: ci.yml / test (all jobs)
  Require branches to be up to date: YES
  Do not allow bypassing: YES
  Allow force pushes: NO
  Allow deletions: NO
```

## Smoke test pattern (runs after staging deploy)
```python
# tests/smoke/test_staging.py
import httpx, os, pytest

BASE = os.environ["STAGING_URL"]
TOKEN = os.environ["STAGING_TOKEN"]

def test_health():
    r = httpx.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_query_returns_answer():
    r = httpx.post(
        f"{BASE}/query",
        json={"query": "smoke test query", "session_id": "smoke-test"},
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert body["answer"] != ""
```

Smoke tests must leave no permanent state in staging.
