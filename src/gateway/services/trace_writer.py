import logging
import os

from google.cloud import firestore

logger = logging.getLogger(__name__)

_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        project = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
        _db = firestore.AsyncClient(project=project)
    return _db


def _trace_ref(db, trace_id: str, tenant_id: str | None):
    if tenant_id:
        return db.collection("tenants").document(tenant_id).collection("traces").document(trace_id)
    return db.collection("traces").document(trace_id)


async def write_trace(trace: dict, tenant_id: str | None = None) -> None:
    try:
        db = _get_db()
        await _trace_ref(db, trace["trace_id"], tenant_id).set(trace)
    except Exception as e:
        logger.warning("Trace write failed (non-fatal): %s", e)


async def update_feedback(trace_id: str, rating: int, comment: str | None, tenant_id: str | None = None) -> None:
    from datetime import datetime, timezone

    try:
        db = _get_db()
        await _trace_ref(db, trace_id, tenant_id).update(
            {
                "feedback": {
                    "rating": rating,
                    "comment": comment,
                    "rated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )
    except Exception as e:
        logger.warning("Feedback write failed (non-fatal): %s", e)
