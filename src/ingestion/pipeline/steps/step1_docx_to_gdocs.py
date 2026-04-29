"""
Step 1 — Convert DOCX files in Drive to native Google Docs via server-side copy.

Input:  list of file metadata dicts from list_accepted_files()
Output: Google Drive folder DRIVE_GDOCS_FOLDER (created if absent)

Native Google Docs pass through unchanged (Step 1 is a no-op for them).
"""

from pathlib import Path

from ..config import DRIVE_GDOCS_FOLDER
from ..drive_utils import find_or_create_folder
from ...log import info

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDOC_MIME = "application/vnd.google-apps.document"


def run(drive_service, source_folder_id: str, files: list[dict]) -> list[dict]:
    """
    Convert DOCX files to native Google Docs via server-side copy.
    Native Google Docs pass through unchanged.

    Returns list of {name: stem, gdoc_id: id} for each file.
    """
    info("Step 1 started", step=1, file_count=len(files))

    gdocs_folder_id = find_or_create_folder(
        drive_service, DRIVE_GDOCS_FOLDER, parent_id=source_folder_id
    )

    results = []
    for f in files:
        stem = Path(f["name"]).stem
        if f["mimeType"] == _GDOC_MIME:
            info("Pass-through: native Google Doc", step=1, stem=stem)
            results.append({"name": stem, "gdoc_id": f["id"]})
            continue

        info("Converting DOCX to Google Doc", step=1, stem=stem)
        gdoc = drive_service.files().copy(
            fileId=f["id"],
            body={"name": stem, "mimeType": _GDOC_MIME, "parents": [gdocs_folder_id]},
        ).execute()
        info("Conversion done", step=1, stem=stem, gdoc_id=gdoc["id"])
        results.append({"name": stem, "gdoc_id": gdoc["id"]})

    info("Step 1 complete", step=1, doc_count=len(results))
    return results
