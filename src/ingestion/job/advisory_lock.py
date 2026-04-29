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

_LOCK_BLOB = "_lock/ingestion.json"
_TTL_HOURS = 1


class AlreadyRunning(Exception):
    pass


@contextmanager
def advisory_lock(gcs_client, bucket: str):
    blob = gcs_client.bucket(bucket).blob(_LOCK_BLOB)

    # Check for an existing non-expired lock before attempting acquire.
    if blob.exists():
        try:
            lock = json.loads(blob.download_as_text())
            expires_at = datetime.fromisoformat(lock["expires_at"])
            if datetime.now(timezone.utc) < expires_at:
                raise AlreadyRunning(
                    f"[lock] Rebuild already running "
                    f"(started {lock['started_at']}, expires {lock['expires_at']}). Exiting."
                )
            print(f"[lock] Stale lock found (expired {lock.get('expires_at')}). Overwriting.")
            blob.delete()
        except (KeyError, ValueError):
            print("[lock] Malformed lock found. Overwriting.")
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
            if_generation_match=0,  # create-only: fails if another job acquired simultaneously
        )
    except PreconditionFailed:
        raise AlreadyRunning("[lock] Lost acquire race — another job acquired simultaneously.")

    generation = blob.generation
    print(f"[lock] Acquired (generation={generation}, expires {lock_data['expires_at']})")

    try:
        yield
    finally:
        try:
            blob.delete(if_generation_match=generation)
            print("[lock] Released.")
        except PreconditionFailed:
            print("[lock] Lock was already replaced (post-SIGKILL scenario) — not deleting.", file=sys.stderr)
        except Exception as e:
            print(f"[lock] Warning: could not release lock: {e}", file=sys.stderr)
