"""
Ingestion Cloud Run Job entrypoint.

Polls a Google Drive folder for file changes. On any change (add/remove/modify),
runs the full ingestion pipeline (Steps 1–5 + index build) and writes the index to GCS.

Environment variables (see config.py for defaults):
  DRIVE_FOLDER_ID   — Google Drive folder ID to watch
  SOURCE_ID         — GCS path prefix and group_id in the index
  GCS_BUCKET        — GCS bucket name (default: img-dev-index)
"""
import asyncio
import sys
from pathlib import Path

import google.auth
from google.cloud import storage as gcs
from googleapiclient.discovery import build

from .advisory_lock import AlreadyRunning, advisory_lock
from .config import DRIVE_FOLDER_ID, GCS_BUCKET, SOURCE_ID
from .drive_sync import list_accepted_files
from .gcs_io import has_changes, load_manifest, save_manifest, upload_index
from ..build_index import build_all
from ..log import error, info

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]

_SCRATCH = Path("/tmp/pipeline")
_INDEX_DIR = Path("/tmp/index")


def _rebuild(gcs_client, drive_svc, docs_svc) -> None:
    files = list_accepted_files(drive_svc, DRIVE_FOLDER_ID)
    info("Drive files listed", count=len(files))

    manifest = load_manifest(gcs_client, GCS_BUCKET, SOURCE_ID)

    if not has_changes(files, manifest):
        info("No changes detected — exiting")
        return

    info("Changes detected — running full rebuild")

    _SCRATCH.mkdir(parents=True, exist_ok=True)

    from ..pipeline.steps.step1_docx_to_gdocs import run as step1
    gdocs = step1(drive_svc, DRIVE_FOLDER_ID, files)

    from ..pipeline.steps.step2_gdocs_to_md import run as step2
    stems = step2(drive_svc, docs_svc, _SCRATCH, gdocs)

    from ..pipeline.steps.step3_ai_cleanup import run as step3
    stems = step3(_SCRATCH, stems)

    from ..pipeline.steps.step4_table_to_prose import run as step4
    stems = step4(_SCRATCH, stems)

    from ..pipeline.steps.step5_chunk import run as step5
    step5(_SCRATCH, stems)

    asyncio.run(build_all(_SCRATCH / "02_ai_cleaned", _INDEX_DIR))

    upload_index(gcs_client, GCS_BUCKET, SOURCE_ID, _INDEX_DIR)
    save_manifest(gcs_client, GCS_BUCKET, SOURCE_ID, files)

    info("Rebuild complete", gcs_path=f"gs://{GCS_BUCKET}/{SOURCE_ID}/multi_index.json")


def main() -> None:
    info("Job started", folder=DRIVE_FOLDER_ID, source=SOURCE_ID, bucket=GCS_BUCKET)

    creds, _ = google.auth.default(scopes=_DRIVE_SCOPES)
    gcs_client = gcs.Client()

    try:
        with advisory_lock(gcs_client, GCS_BUCKET):
            drive_svc = build("drive", "v3", credentials=creds)
            docs_svc = build("docs", "v1", credentials=creds)
            _rebuild(gcs_client, drive_svc, docs_svc)
    except AlreadyRunning as e:
        info(str(e))
        sys.exit(0)


if __name__ == "__main__":
    main()
