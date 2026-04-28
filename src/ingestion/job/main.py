"""
Ingestion Cloud Run Job entrypoint.

Polls a single Google Drive folder for DOCX changes. On any change (add/remove/modify),
runs the full ingestion pipeline (Steps 1–5 + index build) and writes the index to GCS.

Environment variables (see config.py for defaults):
  DRIVE_FOLDER_ID   — Google Drive folder ID to watch
  SOURCE_ID         — GCS path prefix and group_id in the index
  GCS_BUCKET        — GCS bucket name (default: img-dev-index)
  OAUTH_TOKEN_PATH  — path to token.pickle (default: oauth/token.pickle)
  GEMINI_API_KEY    — required for Step 3 (AI header cleanup)
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from google.cloud import storage as gcs

from .config import DRIVE_FOLDER_ID, SOURCE_ID, GCS_BUCKET, OAUTH_TOKEN_PATH
from .drive_sync import download_docx_to_local, list_docx_files, upload_intermediaries
from .gcs_io import has_changes, load_manifest, save_manifest, upload_index
from ..pipeline.auth_oauth import get_docs_service, get_drive_service
from ..pipeline.config import DOCX_DIR, PIPELINE_DIR


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


def main() -> None:
    print(f"[ingestion-job] folder={DRIVE_FOLDER_ID} source={SOURCE_ID} bucket={GCS_BUCKET}")

    drive_service = get_drive_service()
    docs_service = get_docs_service()
    gcs_client = gcs.Client()

    files = list_docx_files(drive_service, DRIVE_FOLDER_ID)
    print(f"  Drive: {len(files)} DOCX file(s)")

    manifest = load_manifest(gcs_client, GCS_BUCKET, SOURCE_ID)

    if not has_changes(files, manifest):
        print("  No changes detected. Exiting.")
        sys.exit(0)

    print("  Changes detected — running full rebuild.")

    download_docx_to_local(drive_service, files, DOCX_DIR)

    run_id, run_dir = _setup_run_dir()
    print(f"  Run ID: {run_id}  dir: {run_dir}")

    from ..pipeline.steps.step1_docx_to_gdocs import run as step1
    gdocs = step1(drive_service, run_dir, parent_folder_id=DRIVE_FOLDER_ID)

    from ..pipeline.steps.step2_gdocs_to_md import run as step2
    stems = step2(drive_service, docs_service, run_dir, gdocs, parent_folder_id=DRIVE_FOLDER_ID)

    from ..pipeline.steps.step3_ai_cleanup import run as step3
    stems = step3(run_dir, stems)

    from ..pipeline.steps.step4_table_to_prose import run as step4
    stems = step4(run_dir, stems)

    from ..pipeline.steps.step5_chunk import run as step5
    step5(run_dir, stems)

    result = subprocess.run(
        [sys.executable, "src/ingestion/build_index.py"],
        check=False,
    )
    if result.returncode != 0:
        print("ERROR: build_index.py failed", file=sys.stderr)
        sys.exit(result.returncode)

    _update_symlink(run_dir)

    upload_intermediaries(drive_service, run_dir, DRIVE_FOLDER_ID)

    index_dir = Path("data/index")
    upload_index(gcs_client, GCS_BUCKET, SOURCE_ID, index_dir)

    save_manifest(gcs_client, GCS_BUCKET, SOURCE_ID, files)

    print(f"[ingestion-job] Done. Index at gs://{GCS_BUCKET}/{SOURCE_ID}/multi_index.json")


if __name__ == "__main__":
    main()
