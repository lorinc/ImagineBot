"""
Drive sync helpers for the ingestion job.
"""

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDOC_MIME = "application/vnd.google-apps.document"


def list_accepted_files(drive_service, folder_id: str) -> list[dict]:
    """Return [{id, name, modified_time, mimeType}] for DOCX and native Google Doc files."""
    q = (
        f"'{folder_id}' in parents"
        f" AND (mimeType='{_DOCX_MIME}' OR mimeType='{_GDOC_MIME}')"
        " AND trashed=false"
    )
    results = drive_service.files().list(
        q=q, fields="files(id, name, modifiedTime, mimeType)"
    ).execute()
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "modified_time": f["modifiedTime"],
            "mimeType": f["mimeType"],
        }
        for f in results.get("files", [])
    ]
