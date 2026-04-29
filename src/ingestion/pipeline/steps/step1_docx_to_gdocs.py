"""
Step 1 — Convert DOCX files in Drive to native Google Docs via server-side copy.

Input:  list of file metadata dicts from list_accepted_files()
Output: Google Drive folder DRIVE_GDOCS_FOLDER (created if absent)

Native Google Docs pass through unchanged (Step 1 is a no-op for them).
"""

from pathlib import Path

from googleapiclient.errors import HttpError

from ..config import DRIVE_GDOCS_FOLDER
from ..drive_utils import find_or_create_folder
from ...errors import ExportServerError, PermissionDenied, ValidationError
from ...log import error, info

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDOC_MIME = "application/vnd.google-apps.document"

_VIEWER_URL = "https://drive.google.com/file/d/{id}/view"
_EDITOR_URL = "https://docs.google.com/document/d/{id}/edit"


def run(
    drive_service, source_folder_id: str, files: list[dict]
) -> tuple[list[dict], list[ValidationError]]:
    """Convert DOCX files to native Google Docs via server-side copy.

    Native Google Docs pass through unchanged.

    Returns (gdocs, errors) where gdocs is a list of {name, gdoc_id} dicts
    for each file that succeeded, and errors is a list of ValidationErrors
    for files that failed.
    """
    info("Step 1 started", step=1, file_count=len(files))

    gdocs_folder_id = find_or_create_folder(
        drive_service, DRIVE_GDOCS_FOLDER, parent_id=source_folder_id
    )

    results: list[dict] = []
    errors: list[ValidationError] = []

    for f in files:
        stem = Path(f["name"]).stem
        drive_url = _VIEWER_URL.format(id=f["id"])

        if f["mimeType"] == _GDOC_MIME:
            info("Pass-through: native Google Doc", step=1, stem=stem)
            results.append({"name": stem, "gdoc_id": f["id"]})
            continue

        info("Converting DOCX to Google Doc", step=1, stem=stem)
        try:
            gdoc = drive_service.files().copy(
                fileId=f["id"],
                body={"name": stem, "mimeType": _GDOC_MIME, "parents": [gdocs_folder_id]},
            ).execute()
        except HttpError as e:
            if e.resp.status == 403:
                err = PermissionDenied(stem, drive_url)
            else:
                err = ExportServerError(stem, drive_url)
            error("Step 1 failed", step=1, stem=stem, error_type=err.error_type, detail=str(e))
            errors.append(err)
            continue

        info("Conversion done", step=1, stem=stem, gdoc_id=gdoc["id"])
        results.append({"name": stem, "gdoc_id": gdoc["id"]})

    info("Step 1 complete", step=1, doc_count=len(results), error_count=len(errors))
    return results, errors
