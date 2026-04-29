"""
Drive sync helpers for the ingestion job.
"""

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDOC_MIME = "application/vnd.google-apps.document"


def list_accepted_files(drive_service, folder_id: str) -> list[dict]:
    """Return file metadata dicts for DOCX and native Google Doc files in folder_id.

    Each dict has: id, name, mimeType, md5Checksum (DOCX only), version (Google Docs only).
    md5Checksum and version are the content-change fingerprints used by has_changes().
    """
    q = (
        f"'{folder_id}' in parents"
        f" AND (mimeType='{_DOCX_MIME}' OR mimeType='{_GDOC_MIME}')"
        " AND trashed=false"
    )
    results = drive_service.files().list(
        q=q, fields="files(id, name, mimeType, md5Checksum, version)"
    ).execute()
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "md5Checksum": f.get("md5Checksum"),   # present for DOCX, absent for Google Docs
            "version": f.get("version"),            # present for Google Docs, absent for DOCX
        }
        for f in results.get("files", [])
    ]
