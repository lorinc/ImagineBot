# Google Drive integration plan — multi-tenant corpus management

## What tenants do

1. Put documents (DOCX, Google Docs, Markdown) into a Google Drive folder
2. Share that folder with the ingestion service account (Viewer access)
3. Paste the folder URL into the admin UI and press "Connect"
4. Index builds automatically; tenant presses "Rebuild" after corpus updates

Steps 1–5 of the pipeline run invisibly in the background. Tenants never see
pipeline intermediates, folder naming conventions, or Drive API details.

## Accepted file formats

- DOCX — converted to Google Docs (current Step 1), then exported as Markdown
- Native Google Docs — exported directly as Markdown (Step 2, skip Step 1)
- Markdown — used as-is (skip Steps 1–2)

PDFs are not in scope for v1.

## Service account model

One service account: `ingestion@img-prod.iam.gserviceaccount.com`

Tenants grant Viewer access on their Drive folder to this single identity.
The service account uses Workload Identity (no key files, no stored credentials).
It has no project-level Drive access — only the folders explicitly shared with it.

Security properties:
- Cross-tenant Drive access is impossible; each folder grant is isolated
- Viewer-only — the service account cannot modify, delete, or reshare documents
- A compromised service account credential cannot alter source documents

## Source registry (Firestore)

```
sources/{source_id}
  tenant_id:            str
  name:                 str           # e.g. "Westfield Primary 2025–26"
  drive_folder_id:      str           # extracted from folder URL
  drive_changes_token:  str | null    # page token for incremental change polling
  last_ingested_at:     timestamp | null
  index_gcs_path:       str           # gs://img-{env}-index/{source_id}/multi_index.json
  status:               "active" | "pending_first_ingest" | "error"
  error_message:        str | null
```

`source_id` equals `group_id` in the PageIndex — the access service returns permitted
`source_ids` per user; the knowledge service filters by `group_ids`. No new abstraction
needed; the existing isolation boundary is the right one.

## Source registration flow

1. Tenant shares their Drive folder with the service account
2. Admin (tenant or ops, depending on auth design) enters the folder URL in the admin UI
3. `POST /admin/sources { tenant_id, name, drive_folder_url }`
   - Extract folder ID from URL
   - Call Drive API to verify the service account can list the folder
   - On failure: return 400 "Please share the folder with ingestion@img-prod.iam.gserviceaccount.com"
   - On success: create Firestore document with status `pending_first_ingest`
4. Trigger initial ingest job asynchronously
5. Admin UI polls `GET /admin/sources/{source_id}` until status is `active`

The verification step is mandatory — it surfaces misconfigured sharing immediately
rather than silently failing hours later.

## Change detection

**v1: Manual trigger only**
`POST /admin/sources/{source_id}/ingest` kicks off a full rebuild for that source.
Tenant presses "Rebuild" after uploading new documents.

**v2: Scheduled polling**
Cloud Scheduler fires every N minutes. Ingestion service calls `drive.changes.list`
with the stored `drive_changes_token` per source. If any files changed, trigger rebuild
for that source and update the token.

Drive Push Notifications (webhooks) are explicitly deferred:
- Watches expire after 7 days and require a renewal job — a scheduler is needed anyway
- Near-real-time freshness is not a requirement for this corpus type
- Push notifications are not cryptographically signed; verification relies on a secret
  token in the channel ID, which is weaker than the polling model's service account auth

## Index storage

Current: `data/index/multi_index.json` — local disk, single tenant, lost on machine death.
Target: `gs://img-{env}-index/{source_id}/multi_index.json`

The knowledge service reads the index on startup. With GCS paths stored in Firestore,
multiple Cloud Run instances and multiple tenants all work without coordination.

## Pipeline changes required

The pipeline job becomes parameterized on `source_id`:
1. Read `drive_folder_id` from `sources/{source_id}` in Firestore
2. Run Steps 1–5 scoped to that folder (service account identity, not personal OAuth)
3. Write index to `index_gcs_path`
4. Update `last_ingested_at`, `status`, `drive_changes_token` in Firestore

Each source's pipeline run is fully independent — parallel runs for different tenants
do not share any state.

## What to build (ordered)

| # | Component | Where |
|---|-----------|-------|
| 1 | GCS index bucket + IAM | GCP |
| 2 | Workload Identity for ingestion SA | GCP |
| 3 | `sources` Firestore schema | `src/admin/` |
| 4 | `POST /admin/sources` with Drive verify | `src/admin/` |
| 5 | Parameterized pipeline job (source_id in, GCS index out) | `src/ingestion/` |
| 6 | `POST /admin/sources/{id}/ingest` manual trigger | `src/admin/` |
| 7 | Knowledge service reads index from GCS | `src/knowledge/` |
| 8 | Scheduled polling (Cloud Scheduler + changes.list) | `src/ingestion/` |

Items 1–7 are v1. Item 8 is v2.

## Open questions (resolve before implementing items 4–7)

- Who has access to the admin UI — tenants self-service, or ops only? Determines auth
  design for the admin service. See `src/admin/CLAUDE.md`.
- Subfolder recursion: does the pipeline read only the top-level folder, or recurse?
  Flat is simpler; decide based on what tenants actually need.
- Deleted files: full rebuild on any change handles deletions correctly. Track Drive
  file IDs in `manifest.json` per run if incremental rebuilds are ever needed.
