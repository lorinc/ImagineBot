"""run_report.json builder and GCS uploader."""
import json
from datetime import datetime, timezone

from ..log import info


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_report(
    *,
    run_id: str,
    status: str,
    started_at: str,
    trigger: str,
    files: list[dict],
    index_updated: bool = False,
    index_version_live: str | None = None,
) -> dict:
    finished_at = _now_iso()
    index_age_hours: float | None = None
    if index_version_live:
        try:
            live_dt = datetime.fromisoformat(index_version_live)
            now_dt = datetime.now(timezone.utc)
            index_age_hours = round((now_dt - live_dt).total_seconds() / 3600, 1)
        except ValueError:
            pass

    return {
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "trigger": trigger,
        "index_updated": index_updated,
        "index_version_live": index_version_live,
        "index_age_hours": index_age_hours,
        "files": files,
        "cost_total_usd": sum(f.get("cost_usd", 0.0) for f in files),
    }


def file_ok(name: str, steps_completed: list[int], chunks: int = 0) -> dict:
    return {
        "name": name,
        "status": "ok",
        "steps_completed": steps_completed,
        "chunks": chunks,
        "cost_usd": 0.0,
    }


def file_failed(err) -> dict:
    """Build a failed file entry from a ValidationError."""
    d = {
        "name": err.name,
        "status": "failed",
        "error_type": err.error_type,
        "error_detail": err.error_detail,
        "actionable": err.actionable,
        "drive_url": err.drive_url,
    }
    if hasattr(err, "step"):
        d["failed_at_step"] = err.step
    return d


def write_report(gcs_client, bucket: str, source_id: str, report: dict) -> None:
    blob = gcs_client.bucket(bucket).blob(f"{source_id}/run_report.json")
    blob.upload_from_string(
        json.dumps(report, indent=2),
        content_type="application/json",
    )
    info("run_report.json written", source_id=source_id, status=report["status"])
