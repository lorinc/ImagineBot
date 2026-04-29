"""
GCS I/O helpers for the ingestion job.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from ..log import info


def load_manifest(gcs_client, bucket: str, source_id: str) -> dict:
    """Return manifest dict, or {} if it does not exist yet (first run)."""
    blob = gcs_client.bucket(bucket).blob(f"{source_id}/manifest.json")
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text())


def _fingerprint(f: dict) -> str:
    """Content-change fingerprint: md5Checksum for DOCX, version for Google Docs."""
    return f.get("md5Checksum") or str(f.get("version", ""))


def save_manifest(gcs_client, bucket: str, source_id: str, files: list[dict]) -> None:
    """Write manifest with current file list and fingerprints."""
    manifest = {
        "files": [
            {"name": f["name"], "mimeType": f["mimeType"], "fingerprint": _fingerprint(f)}
            for f in files
        ],
        "last_run": datetime.now(timezone.utc).isoformat(),
    }
    gcs_client.bucket(bucket).blob(f"{source_id}/manifest.json").upload_from_string(
        json.dumps(manifest, indent=2), content_type="application/json"
    )
    info("Manifest saved", source_id=source_id, file_count=len(files))


def upload_index(gcs_client, bucket: str, source_id: str, index_dir: Path) -> None:
    """Upload multi_index.json and all per-doc index_*.json files to GCS."""
    b = gcs_client.bucket(bucket)
    uploaded = []

    multi = index_dir / "multi_index.json"
    if multi.exists():
        b.blob(f"{source_id}/multi_index.json").upload_from_filename(str(multi))
        uploaded.append("multi_index.json")

    for f in sorted(index_dir.glob("index_*.json")):
        b.blob(f"{source_id}/{f.name}").upload_from_filename(str(f))
        uploaded.append(f.name)

    info("Index uploaded to GCS", source_id=source_id, files=uploaded)


def upload_debug_step(
    gcs_client, bucket: str, source_id: str, run_id: str,
    step_dir_name: str, local_dir: Path,
) -> None:
    """Upload all files in local_dir to gs://<bucket>/<source_id>/debug/<run_id>/<step_dir_name>/."""
    b = gcs_client.bucket(bucket)
    prefix = f"{source_id}/debug/{run_id}/{step_dir_name}"
    uploaded = []
    for f in sorted(local_dir.glob("*")):
        if f.is_file():
            b.blob(f"{prefix}/{f.name}").upload_from_filename(str(f))
            uploaded.append(f.name)
    info("Debug step uploaded", step=step_dir_name, run_id=run_id, files=uploaded)


def has_changes(current_files: list[dict], manifest: dict) -> bool:
    """Return True if file set or any content fingerprint differs from the last manifest."""
    manifest_map = {f["name"]: f["fingerprint"] for f in manifest.get("files", [])}
    current_names = {f["name"] for f in current_files}

    if current_names != set(manifest_map):
        return True

    return any(
        _fingerprint(f) != manifest_map[f["name"]]
        for f in current_files
    )
