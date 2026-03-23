"""
Minimal Drive utilities needed by the pipeline.
"""


def find_or_create_folder(drive_service, name, parent_id=None):
    """Return folder ID for *name*, creating it if absent."""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = drive_service.files().list(q=q, fields="files(id, name)").execute()
    folders = results.get("files", [])
    if folders:
        return folders[0]["id"]

    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    print(f"  Created Drive folder: {name}")
    return folder["id"]


def list_google_docs_in_folder(drive_service, folder_id):
    """Return list of {id, name} dicts for Google Docs in *folder_id*."""
    q = (
        f"'{folder_id}' in parents"
        " and mimeType='application/vnd.google-apps.document'"
        " and trashed=false"
    )
    results = drive_service.files().list(q=q, fields="files(id, name)").execute()
    return results.get("files", [])
