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


async def write_trace(trace: dict) -> None:
    try:
        db = _get_db()
        await db.collection("traces").document(trace["trace_id"]).set(trace)
    except Exception as e:
        logger.warning("Trace write failed (non-fatal): %s", e)


async def update_feedback(trace_id: str, rating: int, comment: str | None) -> None:
    from datetime import datetime, timezone

    try:
        db = _get_db()
        await db.collection("traces").document(trace_id).update(
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
