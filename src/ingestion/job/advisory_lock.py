"""
GCS advisory lock to prevent concurrent ingestion rebuilds.

Lock file: gs://<bucket>/_lock/ingestion.json
TTL: 1 hour (defence against SIGKILL bypassing the release path).

Acquire uses if_generation_match=0 (create-only), so two jobs racing to acquire
will get a PreconditionFailed on the loser — no silent double-acquire.
Release uses if_generation_match=<recorded_generation> so a post-SIGKILL
replacement lock is not accidentally deleted by the recovering job.
"""
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import PreconditionFailed

from ..log import info, warning

_LOCK_BLOB = "_lock/ingestion.json"
_TTL_HOURS = 1


class AlreadyRunning(Exception):
    pass


@contextmanager
def advisory_lock(gcs_client, bucket: str):
    blob = gcs_client.bucket(bucket).blob(_LOCK_BLOB)

    if blob.exists():
        try:
            lock = json.loads(blob.download_as_text())
            expires_at = datetime.fromisoformat(lock["expires_at"])
            if datetime.now(timezone.utc) < expires_at:
                raise AlreadyRunning(
                    f"Rebuild already running (started {lock['started_at']}, "
                    f"expires {lock['expires_at']})"
                )
            warning("Stale lock found — overwriting", expired_at=lock.get("expires_at"))
            blob.delete()
        except (KeyError, ValueError):
            warning("Malformed lock found — overwriting")
            blob.delete()

    now = datetime.now(timezone.utc)
    lock_data = {
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=_TTL_HOURS)).isoformat(),
    }

    try:
        blob.upload_from_string(
            json.dumps(lock_data),
            content_type="application/json",
            if_generation_match=0,
        )
    except PreconditionFailed:
        raise AlreadyRunning("Lost acquire race — another job acquired simultaneously")

    generation = blob.generation
    info("Lock acquired", generation=generation, expires_at=lock_data["expires_at"])

    try:
        yield
    finally:
        try:
            blob.delete(if_generation_match=generation)
            info("Lock released")
        except PreconditionFailed:
            warning("Lock replaced by another job (post-SIGKILL) — not deleting")
        except Exception as e:
            warning(f"Could not release lock: {e}")
