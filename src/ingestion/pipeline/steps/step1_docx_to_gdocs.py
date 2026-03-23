"""
Step 1 — Upload local DOCX files to Google Drive as native Google Docs.

Input:  data/docx/*.docx
Output: Google Drive folder DRIVE_GDOCS_FOLDER (created if absent)

Idempotent: skips files whose stem already exists in the Drive folder.
"""

from pathlib import Path
from ..config import DOCX_DIR, DRIVE_GDOCS_FOLDER
from ..drive_utils import find_or_create_folder, list_google_docs_in_folder


def run(drive_service, run_dir: Path) -> list[dict]:
    """
    Upload all DOCX files from DOCX_DIR to Drive as Google Docs.

    Returns list of {name, gdoc_id} for every doc in the Drive folder
    (including pre-existing ones).
    """
    print("=== Step 1: DOCX → Google Docs ===")

    folder_id = find_or_create_folder(drive_service, DRIVE_GDOCS_FOLDER)
    print(f"  Drive folder '{DRIVE_GDOCS_FOLDER}': {folder_id}")

    # Index existing docs by stem name to enable idempotency
    existing = {d["name"]: d["id"] for d in list_google_docs_in_folder(drive_service, folder_id)}

    docx_files = sorted(DOCX_DIR.glob("*.docx"))
    if not docx_files:
        print(f"  No DOCX files found in {DOCX_DIR}")
        return []

    results = []
    for docx_path in docx_files:
        stem = docx_path.stem
        if stem in existing:
            print(f"  Skipping (already in Drive): {stem}")
            results.append({"name": stem, "gdoc_id": existing[stem]})
            continue

        print(f"  Uploading: {docx_path.name} ...", end=" ", flush=True)
        with open(docx_path, "rb") as f:
            content = f.read()

        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(
            content,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            resumable=False,
        )
        metadata = {
            "name": stem,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id],
        }
        gdoc = drive_service.files().create(
            body=metadata,
            media_body=media,
            fields="id, name",
        ).execute()
        print(f"done ({gdoc['id']})")
        results.append({"name": stem, "gdoc_id": gdoc["id"]})

    print(f"  Step 1 complete: {len(results)} doc(s) in Drive\n")
    return results
