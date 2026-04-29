"""Post Drive comments for validation errors; deduplicates by error_type."""
import re

from googleapiclient.errors import HttpError

from ..errors import ValidationError
from ..log import error, info

_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")
_MARKER_PREFIX = "ImagineBot:"


def _file_id_from_url(drive_url: str) -> str | None:
    m = _ID_RE.search(drive_url)
    return m.group(1) if m else None


def _comment_body(err: ValidationError) -> str:
    return (
        f"[{_MARKER_PREFIX}{err.error_type}] ImagineBot could not process this document.\n\n"
        f"Reason: {err.error_detail}\n"
        f"Action: {err.actionable}"
    )


def post_validation_comment(drive_svc, err: ValidationError) -> None:
    """Post a Drive comment for a validation error. No-op if an identical error_type comment exists."""
    file_id = _file_id_from_url(err.drive_url)
    if not file_id:
        error("Cannot post Drive comment: no file_id in drive_url", stem=err.name, drive_url=err.drive_url)
        return

    marker = f"[{_MARKER_PREFIX}{err.error_type}]"
    try:
        existing = drive_svc.comments().list(
            fileId=file_id, fields="comments(content,resolved)"
        ).execute()
        for c in existing.get("comments", []):
            if marker in (c.get("content") or ""):
                info("Drive comment already exists — skipping", stem=err.name, error_type=err.error_type)
                return
    except HttpError as e:
        error("Failed to list Drive comments", stem=err.name, detail=str(e))
        return

    try:
        drive_svc.comments().create(
            fileId=file_id,
            body={"content": _comment_body(err)},
            fields="id",
        ).execute()
        info("Drive comment posted", stem=err.name, error_type=err.error_type)
    except HttpError as e:
        error("Failed to post Drive comment", stem=err.name, detail=str(e))
