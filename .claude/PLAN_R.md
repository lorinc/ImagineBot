# Plan — Item R: Drive polling stub
# Written: 2026-04-28. Implement in next session.

## Goal
Cloud Run Job polls a single Google Drive folder every minute. On any top-level DOCX
change (new / removed / modified), runs the full ingestion pipeline and writes the
index to GCS. Knowledge service reads index from GCS on startup.

## Constraints
- Personal OAuth (`oauth/token.pickle`) — no service account yet
- Single folder, single source (no Firestore sources collection)
- Full rebuild on any change (no incremental)
- `tools/build_index.py` moves into `src/ingestion/` before the Dockerfile is written

---

## Files to create

### `src/ingestion/job/__init__.py`
Empty.

### `src/ingestion/job/main.py`
Entrypoint for the Cloud Run Job. Reads env vars, orchestrates the full flow.

```
DRIVE_FOLDER_ID  — top-level Drive folder to watch
SOURCE_ID        — used as GCS path prefix and group_id in the index
OAUTH_TOKEN_PATH — path to token.pickle (default: oauth/token.pickle)
```

Flow:
1. Build drive_service + docs_service via `get_drive_service()` / `get_docs_service()`
2. `files = list_docx_files(drive_service, DRIVE_FOLDER_ID)`
3. `manifest = load_manifest(gcs_client, SOURCE_ID)`  — {} on first run
4. `if not has_changes(files, manifest): sys.exit(0)`
5. `download_docx_to_local(drive_service, files)`  — writes to `data/docx/`
6. `run_id, run_dir = setup_run_dir()`
7. Call step1 through step5 directly (import from pipeline.steps)
8. `subprocess.run(["python3", "src/ingestion/build_index.py"])` — exits non-zero on failure
9. `upload_intermediaries(drive_service, run_dir, DRIVE_FOLDER_ID)`
10. `upload_index_to_gcs(gcs_client, SOURCE_ID)`
11. `save_manifest(gcs_client, SOURCE_ID, files)`

Exit 0 on success (no-op or completed rebuild). Exit non-zero on any failure.

### `src/ingestion/job/drive_sync.py`
Three functions:

**`list_docx_files(drive_service, folder_id) -> list[dict]`**
- Drive query: `'{folder_id}' in parents AND mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document' AND trashed=false`
- Fields: `files(id, name, modifiedTime)`
- Returns `[{id, name, modified_time}]`

**`download_docx_to_local(drive_service, files: list[dict], dest_dir: Path)`**
- Clears `dest_dir` first (full rebuild — stale files must not persist)
- For each file: `drive_service.files().get_media(fileId=id)` → write to `dest_dir/<name>.docx`

**`upload_intermediaries(drive_service, run_dir: Path, parent_folder_id: str)`**
- For each local subdir in run_dir (`01_baseline_md`, `02_ai_cleaned`, `03_chunked`):
  - `find_or_create_folder(drive_service, subdir_name, parent_id=parent_folder_id)`
  - Upload every file in that subdir (overwrite by name — idempotent)
- Also upload `data/index/multi_index.json` to an `index/` subfolder

Upload mime type: `text/plain` for .md and .json files.
Use `MediaInMemoryUpload`. Check if file exists by name before uploading; update if exists,
create if not.

### `src/ingestion/job/gcs_io.py`
Uses `google-cloud-storage`. Client constructed once and passed in.

**`load_manifest(gcs_client, bucket: str, source_id: str) -> dict`**
- Download `gs://{bucket}/{source_id}/manifest.json`
- Return `{}` if blob does not exist (first run)
- Manifest schema: `{files: [{name, modified_time}], last_run: ISO timestamp}`

**`save_manifest(gcs_client, bucket: str, source_id: str, files: list[dict])`**
- Write `{files: [...], last_run: utcnow().isoformat()}` to the manifest path

**`upload_index(gcs_client, bucket: str, source_id: str, index_dir: Path)`**
- Upload `index_dir/multi_index.json` → `gs://{bucket}/{source_id}/multi_index.json`
- Upload all `index_dir/index_*.json` → `gs://{bucket}/{source_id}/index_*.json`
  (per-doc index files; knowledge service resolves them relative to multi_index.json)

**`has_changes(current_files: list[dict], manifest: dict) -> bool`**
- Build sets: manifest_files = {f['name']: f['modified_time'] for f in manifest.get('files', [])}
- Return True if: any name not in manifest_files, any manifest name not in current names,
  or any modified_time differs

### `src/ingestion/job/Dockerfile`
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY src/ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY tools/ tools/        # temporary — remove after build_index moves into src/
COPY oauth/ oauth/        # token.pickle (dev builds only; prod uses secret mount)
ENV PYTHONPATH=/app
CMD ["python3", "-m", "src.ingestion.job.main"]
```

### `src/ingestion/job/requirements.txt`
Extend existing ingestion requirements with:
- `google-cloud-storage`
(google-api-python-client, google-auth, google-auth-oauthlib already in ingestion requirements)

---

## Files to modify

### `src/ingestion/build_index.py`  (moved from `tools/build_index.py`)
- Move the file. No logic changes.
- Update internal `sys.path.insert` to reflect new location:
  `sys.path.insert(0, str(Path(__file__).parents[2] / "knowledge"))`
  — from `src/ingestion/build_index.py`, knowledge is at `../../knowledge` = `src/knowledge`
- Add `if __name__ == "__main__": asyncio.run(main())` wrapper if not present.
- `tools/build_index.py` becomes a one-liner shim:
  `exec(open("src/ingestion/build_index.py").read())` — preserves existing dev CLI path
  OR just delete `tools/build_index.py` and update CLAUDE.md docs command.

### `src/ingestion/pipeline/steps/step1_docx_to_gdocs.py`
- `run(drive_service, run_dir, parent_folder_id=None)`
- Change: `folder_id = find_or_create_folder(drive_service, DRIVE_GDOCS_FOLDER, parent_id=parent_folder_id)`
- No other logic changes.

### `src/ingestion/pipeline/steps/step2_gdocs_to_md.py`
- `run(drive_service, docs_service, run_dir, gdocs, parent_folder_id=None)`
- Change: when locating the gdocs folder, pass `parent_id=parent_folder_id` to `find_or_create_folder`
- No other logic changes.

### `src/ingestion/pipeline/auth_oauth.py`
- Add: `TOKEN_FILE = Path(os.getenv("OAUTH_TOKEN_PATH", str(OAUTH_DIR / "token.pickle")))`
  (replace the hardcoded `OAUTH_DIR / "token.pickle"` constant)
- No other changes.

### `src/knowledge/main.py`
Add at the top of the `lifespan` function, before the `KNOWLEDGE_INDEX_PATH.exists()` check:

```python
gcs_index_path = os.getenv("INDEX_GCS_PATH")
if gcs_index_path:
    from google.cloud import storage as gcs
    local_index = Path("/tmp/multi_index.json")
    local_index_dir = Path("/tmp/index")
    local_index_dir.mkdir(exist_ok=True)
    client = gcs.Client()
    # parse gs://bucket/prefix
    bucket_name, prefix = gcs_index_path[5:].split("/", 1)
    bucket = client.bucket(bucket_name)
    # download multi_index.json
    bucket.blob(f"{prefix}/multi_index.json").download_to_filename(str(local_index_dir / "multi_index.json"))
    # download all per-doc index files listed in multi_index.json
    raw = json.loads((local_index_dir / "multi_index.json").read_text())
    for doc in raw.get("documents", []):
        fname = Path(doc["index_path"]).name
        bucket.blob(f"{prefix}/{fname}").download_to_filename(str(local_index_dir / fname))
    # point KNOWLEDGE_INDEX_PATH at the local copy
    global KNOWLEDGE_INDEX_PATH
    KNOWLEDGE_INDEX_PATH = local_index_dir / "multi_index.json"
```

`INDEX_GCS_PATH` format: `gs://img-dev-index/school-01` (bucket + source_id prefix, no trailing slash).
`google-cloud-storage` must be added to `src/knowledge/requirements.txt`.

---

## GCP setup (R-1) — run these after code is committed

```bash
# Bucket
gsutil mb -l europe-west1 -p img-dev-490919 gs://img-dev-index

# Service account for the job
gcloud iam service-accounts create ingestion-job \
  --display-name="Ingestion Job" --project img-dev

# GCS permissions
gsutil iam ch \
  serviceAccount:ingestion-job@img-dev-490919.iam.gserviceaccount.com:objectAdmin \
  gs://img-dev-index

# Store OAuth token in Secret Manager
gcloud secrets create ingestion-oauth-token --project img-dev
gcloud secrets versions add ingestion-oauth-token \
  --data-file=oauth/token.pickle --project img-dev

# Grant job SA access to the secret
gcloud secrets add-iam-policy-binding ingestion-oauth-token \
  --member=serviceAccount:ingestion-job@img-dev-490919.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor --project img-dev
```

## Cloud Run Job + Scheduler (R-8) — run after image is pushed

```bash
# Build + push image
docker build -f src/ingestion/job/Dockerfile -t europe-west1-docker.pkg.dev/img-dev-490919/services/ingestion-job:latest .
docker push europe-west1-docker.pkg.dev/img-dev-490919/services/ingestion-job:latest

# Create Cloud Run Job
gcloud run jobs create ingestion-poll \
  --image europe-west1-docker.pkg.dev/img-dev-490919/services/ingestion-job:latest \
  --region europe-west1 \
  --service-account ingestion-job@img-dev-490919.iam.gserviceaccount.com \
  --set-env-vars "SOURCE_ID=school-01,OAUTH_TOKEN_PATH=/secrets/oauth_token/token.pickle" \
  --set-secrets "/secrets/oauth_token/token.pickle=ingestion-oauth-token:latest" \
  --project img-dev
  # DRIVE_FOLDER_ID set separately (user provides at job creation time)

# Service account for Cloud Scheduler to invoke the job
gcloud iam service-accounts create scheduler-invoker \
  --display-name="Scheduler Job Invoker" --project img-dev

gcloud projects add-iam-policy-binding img-dev-490919 \
  --member=serviceAccount:scheduler-invoker@img-dev-490919.iam.gserviceaccount.com \
  --role=roles/run.invoker

# Cloud Scheduler job (1-minute poll)
gcloud scheduler jobs create http ingest-poll-1min \
  --location europe-west1 \
  --schedule "* * * * *" \
  --uri "https://run.googleapis.com/v2/projects/img-dev-490919/locations/europe-west1/jobs/ingestion-poll:run" \
  --message-body "{}" \
  --oauth-service-account-email scheduler-invoker@img-dev-490919.iam.gserviceaccount.com \
  --project img-dev
```

---

## Order of implementation in the session

1. Move `tools/build_index.py` → `src/ingestion/build_index.py`; update path; shim or delete tools version
2. Modify step1, step2 (add parent_folder_id param)
3. Modify auth_oauth.py (OAUTH_TOKEN_PATH env var)
4. Create `src/ingestion/job/` package (drive_sync, gcs_io, main, Dockerfile, requirements.txt)
5. Modify knowledge/main.py (INDEX_GCS_PATH startup download)
6. Add google-cloud-storage to knowledge/requirements.txt
7. Run GCP setup commands (R-1) — user runs or approves each
8. Build + push image, create Cloud Run Job, create Scheduler (R-8)

## Testing

- Unit tests for `has_changes()` in `gcs_io.py` (pure function, no mocks needed)
- Unit tests for `list_docx_files()` with a mocked Drive response
- Manual smoke test: drop a DOCX in the Drive folder, wait up to 1 minute, verify
  knowledge service returns answers from the new document after redeploy

## Open before starting

- User must provide `DRIVE_FOLDER_ID` (the folder ID from the Drive URL they create)
- Confirm `SOURCE_ID` value to use (suggested: `school-01`)
