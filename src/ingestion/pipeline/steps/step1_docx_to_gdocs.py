"""
Step 1 — Convert DOCX files in Drive to native Google Docs via server-side copy.

Input:  list of file metadata dicts from list_accepted_files()
Output: Google Drive folder DRIVE_GDOCS_FOLDER (created if absent)

Native Google Docs pass through unchanged (Step 1 is a no-op for them).
"""

from pathlib import Path

from ..config import DRIVE_GDOCS_FOLDER
from ..drive_utils import find_or_create_folder

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDOC_MIME = "application/vnd.google-apps.document"


def run(drive_service, source_folder_id: str, files: list[dict]) -> list[dict]:
    """
    Convert DOCX files to native Google Docs via server-side copy.
    Native Google Docs pass through unchanged.

    Returns list of {name: stem, gdoc_id: id} for each file.
    """
    print("=== Step 1: DOCX → Google Docs ===")

    gdocs_folder_id = find_or_create_folder(
        drive_service, DRIVE_GDOCS_FOLDER, parent_id=source_folder_id
    )

    results = []
    for f in files:
        stem = Path(f["name"]).stem
        if f["mimeType"] == _GDOC_MIME:
            print(f"  Pass-through (native Google Doc): {f['name']}")
            results.append({"name": stem, "gdoc_id": f["id"]})
            continue

        print(f"  Converting: {f['name']} ...", end=" ", flush=True)
        gdoc = drive_service.files().copy(
            fileId=f["id"],
            body={"name": stem, "mimeType": _GDOC_MIME, "parents": [gdocs_folder_id]},
        ).execute()
        print(f"done ({gdoc['id']})")
        results.append({"name": stem, "gdoc_id": gdoc["id"]})

    print(f"  Step 1 complete: {len(results)} doc(s)\n")
    return results
