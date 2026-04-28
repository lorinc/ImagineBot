"""
GCS advisory lock to prevent concurrent ingestion rebuilds.

Lock file: gs://<bucket>/_lock/ingestion.json
TTL: 1 hour. A stale lock (expired or malformed) is overwritten.

GCS does not provide atomic compare-and-swap on regular blobs, so two executions
that start within milliseconds of each other could both acquire the lock. The
Cloud Scheduler fires every minute and a full rebuild takes ~30 minutes, so the
practical collision rate is negligible. The lock exists to prevent the steady-state
pile-up, not to be a hard mutex.
"""
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

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
                    f"[lock] Rebuild already running "
                    f"(started {lock['started_at']}, expires {lock['expires_at']}). Exiting."
                )
            print(f"[lock] Stale lock found (expired {lock.get('expires_at')}). Overwriting.")
        except (KeyError, ValueError):
            print("[lock] Malformed lock found. Overwriting.")

    now = datetime.now(timezone.utc)
    lock_data = {
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=_TTL_HOURS)).isoformat(),
    }
    blob.upload_from_string(json.dumps(lock_data), content_type="application/json")
    print(f"[lock] Acquired (expires {lock_data['expires_at']})")

    try:
        yield
    finally:
        try:
            blob.delete()
            print("[lock] Released.")
        except Exception as e:
            print(f"[lock] Warning: could not release lock: {e}", file=sys.stderr)
