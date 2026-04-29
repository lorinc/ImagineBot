"""
Ingestion Cloud Run Job entrypoint.

Polls a Google Drive folder for file changes. On any change (add/remove/modify),
runs the full ingestion pipeline (Steps 1–5 + index build) and writes the index to GCS.

Environment variables (see config.py for defaults):
  DRIVE_FOLDER_ID    — Google Drive folder ID to watch
  SOURCE_ID          — GCS path prefix and group_id in the index
  GCS_BUCKET         — GCS bucket name (default: img-dev-index)
  INGESTION_TRIGGER  — "scheduler" | "manual" (default: "scheduler")
"""
import asyncio
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import google.auth
from google.cloud import storage as gcs
from googleapiclient.discovery import build

from .advisory_lock import AlreadyRunning, advisory_lock
from .config import DRIVE_FOLDER_ID, GCS_BUCKET, SOURCE_ID, TRIGGER
from .drive_sync import list_accepted_files
from .gcs_io import has_changes, load_manifest, save_manifest, upload_index
from .run_report import build_report, file_failed, file_ok, write_report
from ..build_index import build_all
from ..errors import IngestionError, retry
from ..log import error, info

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]

_SCRATCH = Path("/tmp/pipeline")
_INDEX_DIR = Path("/tmp/index")

_GDOC_EDITOR_URL = "https://docs.google.com/document/d/{id}/edit"


def _rebuild(gcs_client, drive_svc, docs_svc, run_id: str, started_at: str) -> None:
    files = list_accepted_files(drive_svc, DRIVE_FOLDER_ID)
    info("Drive files listed", count=len(files))

    manifest = load_manifest(gcs_client, GCS_BUCKET, SOURCE_ID)
    index_version_live = manifest.get("last_run")

    if not has_changes(files, manifest):
        info("No changes detected — exiting")
        write_report(
            gcs_client, GCS_BUCKET, SOURCE_ID,
            build_report(
                run_id=run_id, status="ok", started_at=started_at, trigger=TRIGGER,
                files=[], index_updated=False, index_version_live=index_version_live,
            ),
        )
        return

    info("Changes detected — running full rebuild")
    _SCRATCH.mkdir(parents=True, exist_ok=True)

    # --- Pre-flight: Steps 1 and 2 for all files ---
    from ..pipeline.steps.step1_docx_to_gdocs import run as step1
    gdocs, s1_errors = step1(drive_svc, DRIVE_FOLDER_ID, files)

    from ..pipeline.steps.step2_gdocs_to_md import run as step2
    stems, s2_errors = step2(drive_svc, docs_svc, _SCRATCH, gdocs)

    all_errors = s1_errors + s2_errors
    if all_errors:
        for err in all_errors:
            error("Pre-flight validation failed", stem=err.name, error_type=err.error_type)
        write_report(
            gcs_client, GCS_BUCKET, SOURCE_ID,
            build_report(
                run_id=run_id, status="aborted", started_at=started_at, trigger=TRIGGER,
                files=[file_failed(e) for e in all_errors],
                index_updated=False, index_version_live=index_version_live,
            ),
        )
        sys.exit(1)

    # --- Steps 3–5: each file wrapped in retry ---
    from ..pipeline.steps.step3_ai_cleanup import run as _step3_run
    from ..pipeline.steps.step4_table_to_prose import run as _step4_run
    from ..pipeline.steps.step5_chunk import run as _step5_run

    file_reports: list[dict] = []

    for stem in stems:
        # Build drive_url for this stem from the gdocs list
        gdoc_entry = next((g for g in gdocs if g["name"] == stem), None)
        drive_url = (
            _GDOC_EDITOR_URL.format(id=gdoc_entry["gdoc_id"])
            if gdoc_entry else ""
        )

        try:
            retry(
                lambda: _step3_run(_SCRATCH, [stem]),
                name=stem, drive_url=drive_url, step=3,
            )
            retry(
                lambda: _step4_run(_SCRATCH, [stem]),
                name=stem, drive_url=drive_url, step=4,
            )
            retry(
                lambda: _step5_run(_SCRATCH, [stem]),
                name=stem, drive_url=drive_url, step=5,
            )
            file_reports.append(file_ok(stem, steps_completed=[1, 2, 3, 4, 5]))
        except IngestionError as e:
            error("Pipeline step failed", stem=stem, error_type=e.error_type, detail=str(e))
            file_reports.append(file_failed(e))

    failed = [r for r in file_reports if r["status"] == "failed"]
    if failed:
        write_report(
            gcs_client, GCS_BUCKET, SOURCE_ID,
            build_report(
                run_id=run_id, status="partial_failure", started_at=started_at, trigger=TRIGGER,
                files=file_reports, index_updated=False, index_version_live=index_version_live,
            ),
        )
        sys.exit(1)

    asyncio.run(build_all(_SCRATCH / "02_ai_cleaned", _INDEX_DIR))
    upload_index(gcs_client, GCS_BUCKET, SOURCE_ID, _INDEX_DIR)
    save_manifest(gcs_client, GCS_BUCKET, SOURCE_ID, files)

    info("Rebuild complete", gcs_path=f"gs://{GCS_BUCKET}/{SOURCE_ID}/multi_index.json")

    write_report(
        gcs_client, GCS_BUCKET, SOURCE_ID,
        build_report(
            run_id=run_id, status="ok", started_at=started_at, trigger=TRIGGER,
            files=file_reports, index_updated=True, index_version_live=index_version_live,
        ),
    )


def main() -> None:
    run_id = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started_at = run_id
    info("Job started", run_id=run_id, folder=DRIVE_FOLDER_ID, source=SOURCE_ID, bucket=GCS_BUCKET)

    creds, _ = google.auth.default(scopes=_DRIVE_SCOPES)
    gcs_client = gcs.Client()

    try:
        with advisory_lock(gcs_client, GCS_BUCKET):
            drive_svc = build("drive", "v3", credentials=creds)
            docs_svc = build("docs", "v1", credentials=creds)
            _rebuild(gcs_client, drive_svc, docs_svc, run_id, started_at)
    except AlreadyRunning as e:
        info(str(e))
        sys.exit(0)
    except Exception:
        error("Unexpected error", detail=traceback.format_exc())
        try:
            write_report(
                gcs_client, GCS_BUCKET, SOURCE_ID,
                build_report(
                    run_id=run_id, status="failed", started_at=started_at,
                    trigger=TRIGGER, files=[],
                ),
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
