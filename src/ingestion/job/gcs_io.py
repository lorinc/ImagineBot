"""
GCS I/O helpers for the ingestion job.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def load_manifest(gcs_client, bucket: str, source_id: str) -> dict:
    """Return manifest dict, or {} if it does not exist yet (first run)."""
    blob = gcs_client.bucket(bucket).blob(f"{source_id}/manifest.json")
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text())


def save_manifest(gcs_client, bucket: str, source_id: str, files: list[dict]) -> None:
    """Write manifest with current file list and timestamp."""
    manifest = {
        "files": [{"name": f["name"], "modified_time": f["modified_time"]} for f in files],
        "last_run": datetime.now(timezone.utc).isoformat(),
    }
    gcs_client.bucket(bucket).blob(f"{source_id}/manifest.json").upload_from_string(
        json.dumps(manifest, indent=2), content_type="application/json"
    )


def upload_index(gcs_client, bucket: str, source_id: str, index_dir: Path) -> None:
    """Upload multi_index.json and all per-doc index_*.json files to GCS."""
    b = gcs_client.bucket(bucket)

    multi = index_dir / "multi_index.json"
    if multi.exists():
        b.blob(f"{source_id}/multi_index.json").upload_from_filename(str(multi))
        print(f"  GCS: uploaded multi_index.json")

    for f in sorted(index_dir.glob("index_*.json")):
        b.blob(f"{source_id}/{f.name}").upload_from_filename(str(f))
        print(f"  GCS: uploaded {f.name}")


def has_changes(current_files: list[dict], manifest: dict) -> bool:
    """Return True if the Drive file list differs from the last saved manifest."""
    manifest_map = {
        f["name"]: f["modified_time"]
        for f in manifest.get("files", [])
    }
    current_names = {f["name"] for f in current_files}

    if current_names != set(manifest_map):
        return True

    return any(
        f["modified_time"] != manifest_map[f["name"]]
        for f in current_files
    )
