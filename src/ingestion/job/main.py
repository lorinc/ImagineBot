"""
Ingestion Cloud Run Job entrypoint.

Polls a single Google Drive folder for DOCX changes. On any change (add/remove/modify),
runs the full ingestion pipeline (Steps 1–5 + index build) and writes the index to GCS.

Environment variables (see config.py for defaults):
  DRIVE_FOLDER_ID   — Google Drive folder ID to watch
  SOURCE_ID         — GCS path prefix and group_id in the index
  GCS_BUCKET        — GCS bucket name (default: img-dev-index)
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import google.auth
from google.cloud import storage as gcs
from googleapiclient.discovery import build

from .advisory_lock import AlreadyRunning, advisory_lock
from .config import DRIVE_FOLDER_ID, GCS_BUCKET, SOURCE_ID
from .drive_sync import download_docx_to_local, list_docx_files, upload_intermediaries
from .gcs_io import has_changes, load_manifest, save_manifest, upload_index
from ..pipeline.config import DOCX_DIR, PIPELINE_DIR

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]


def _next_run_id() -> str:
    today = date.today().strftime("%Y-%m-%d")
    existing = sorted(PIPELINE_DIR.glob(f"{today}_*")) if PIPELINE_DIR.exists() else []
    n = len(existing) + 1
    return f"{today}_{n:03d}"


def _setup_run_dir() -> tuple[str, Path]:
    run_id = _next_run_id()
    run_dir = PIPELINE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({"run_id": run_id, "files": {}}, indent=2))
    return run_id, run_dir


def _update_symlink(run_dir: Path) -> None:
    latest = PIPELINE_DIR / "latest"
    if latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir.name)


def _rebuild(gcs_client, drive_svc, docs_svc) -> None:
    files = list_docx_files(drive_svc, DRIVE_FOLDER_ID)
    print(f"  Drive: {len(files)} DOCX file(s)")

    manifest = load_manifest(gcs_client, GCS_BUCKET, SOURCE_ID)

    if not has_changes(files, manifest):
        print("  No changes detected. Exiting.")
        return

    print("  Changes detected — running full rebuild.")

    download_docx_to_local(drive_svc, files, DOCX_DIR)

    run_id, run_dir = _setup_run_dir()
    print(f"  Run ID: {run_id}  dir: {run_dir}")

    from ..pipeline.steps.step1_docx_to_gdocs import run as step1
    gdocs = step1(drive_svc, run_dir, parent_folder_id=DRIVE_FOLDER_ID)

    from ..pipeline.steps.step2_gdocs_to_md import run as step2
    stems = step2(drive_svc, docs_svc, run_dir, gdocs, parent_folder_id=DRIVE_FOLDER_ID)

    from ..pipeline.steps.step3_ai_cleanup import run as step3
    stems = step3(run_dir, stems)

    from ..pipeline.steps.step4_table_to_prose import run as step4
    stems = step4(run_dir, stems)

    from ..pipeline.steps.step5_chunk import run as step5
    step5(run_dir, stems)

    _update_symlink(run_dir)

    result = subprocess.run(
        [sys.executable, "src/ingestion/build_index.py"],
        check=False,
    )
    if result.returncode != 0:
        print("ERROR: build_index.py failed", file=sys.stderr)
        sys.exit(result.returncode)

    upload_intermediaries(drive_svc, run_dir, DRIVE_FOLDER_ID)

    index_dir = Path("data/index")
    upload_index(gcs_client, GCS_BUCKET, SOURCE_ID, index_dir)

    save_manifest(gcs_client, GCS_BUCKET, SOURCE_ID, files)

    print(f"[ingestion-job] Done. Index at gs://{GCS_BUCKET}/{SOURCE_ID}/multi_index.json")


def main() -> None:
    print(f"[ingestion-job] folder={DRIVE_FOLDER_ID} source={SOURCE_ID} bucket={GCS_BUCKET}")

    creds, _ = google.auth.default(scopes=_DRIVE_SCOPES)
    gcs_client = gcs.Client()

    try:
        with advisory_lock(gcs_client, GCS_BUCKET):
            drive_svc = build("drive", "v3", credentials=creds)
            docs_svc = build("docs", "v1", credentials=creds)
            _rebuild(gcs_client, drive_svc, docs_svc)
    except AlreadyRunning as e:
        print(str(e))
        sys.exit(0)


if __name__ == "__main__":
    main()
