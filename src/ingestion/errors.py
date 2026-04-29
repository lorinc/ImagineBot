"""Typed exception hierarchy for the ingestion pipeline."""
import time
from typing import Callable, TypeVar

_T = TypeVar("_T")


class IngestionError(Exception):
    pass


class ValidationError(IngestionError):
    error_type: str = ""
    error_detail: str = ""
    actionable: str = ""

    def __init__(self, name: str, drive_url: str, *, error_detail: str | None = None):
        self.name = name
        self.drive_url = drive_url
        if error_detail is not None:
            self.error_detail = error_detail
        super().__init__(f"[{self.error_type}] {name}: {self.error_detail}")


class UnsupportedFormat(ValidationError):
    error_type = "UNSUPPORTED_FORMAT"
    error_detail = "This file type cannot be processed."
    actionable = "Convert to a Word document (.docx) or Google Doc and re-upload."


class PermissionDenied(ValidationError):
    error_type = "PERMISSION_DENIED"
    error_detail = "ImagineBot cannot access this document."
    actionable = "Share the document with the service account (Viewer)."


class ExportEmpty(ValidationError):
    error_type = "EXPORT_EMPTY"
    error_detail = "This document appears to be locked, encrypted, or empty."
    actionable = "Open the document in Google Docs and verify it contains readable text."


class NoHeadings(ValidationError):
    error_type = "NO_HEADINGS"
    error_detail = "This document has no section headings."
    actionable = (
        "Add at least one heading (bold title or Heading 1/2 style) so the "
        "document can be divided into topics."
    )


class ExportServerError(ValidationError):
    error_type = "EXPORT_SERVER_ERROR"
    error_detail = "Google could not export this document (server error)."
    actionable = (
        "Wait 10 minutes and trigger a manual refresh. If the problem persists, "
        "re-save the document in Google Docs."
    )


class PipelineFailure(ValidationError):
    error_type = "PIPELINE_FAILURE"
    error_detail = "Processing failed after 3 attempts."
    actionable = "Check run_report.json for the step and error detail."

    def __init__(self, name: str, drive_url: str, *, step: int, cause: Exception):
        self.step = step
        self.cause = cause
        super().__init__(
            name, drive_url,
            error_detail=f"Step {step} failed after 3 attempts: {cause}",
        )


def retry(
    fn: Callable[[], _T],
    *,
    name: str,
    drive_url: str,
    step: int,
    max_attempts: int = 3,
    backoff: float = 2.0,
) -> _T:
    """Call fn() up to max_attempts times with exponential backoff.

    Raises PipelineFailure on exhaustion.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(backoff ** attempt)
    raise PipelineFailure(name, drive_url, step=step, cause=last_exc)
