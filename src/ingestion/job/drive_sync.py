"""
Drive sync helpers for the ingestion job.
"""
import shutil
from pathlib import Path

from googleapiclient.http import MediaInMemoryUpload

from ..pipeline.drive_utils import find_or_create_folder


def list_docx_files(drive_service, folder_id: str) -> list[dict]:
    """Return [{id, name, modified_time}] for all DOCX files in folder_id."""
    q = (
        f"'{folder_id}' in parents"
        " AND mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
        " AND trashed=false"
    )
    results = drive_service.files().list(q=q, fields="files(id, name, modifiedTime)").execute()
    return [
        {"id": f["id"], "name": f["name"], "modified_time": f["modifiedTime"]}
        for f in results.get("files", [])
    ]


def download_docx_to_local(drive_service, files: list[dict], dest_dir: Path) -> None:
    """Download all DOCX files to dest_dir, clearing it first."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)

    for f in files:
        request = drive_service.files().get_media(fileId=f["id"])
        content = request.execute()
        dest = dest_dir / f["name"]
        dest.write_bytes(content)
        print(f"  Downloaded: {f['name']}")


def upload_intermediaries(drive_service, run_dir: Path, parent_folder_id: str) -> None:
    """
    Upload pipeline intermediary dirs and the built index to Drive.

    Subdirs uploaded: 01_baseline_md, 02_ai_cleaned, 03_chunked.
    Index uploaded: data/index/multi_index.json → index/ subfolder.
    """
    for subdir_name in ("01_baseline_md", "02_ai_cleaned", "03_chunked"):
        subdir = run_dir / subdir_name
        if not subdir.exists():
            continue
        folder_id = find_or_create_folder(drive_service, subdir_name, parent_id=parent_folder_id)
        for file_path in sorted(subdir.iterdir()):
            if not file_path.is_file():
                continue
            _upload_or_update(drive_service, file_path, folder_id)

    index_dir = Path("data/index")
    multi_index = index_dir / "multi_index.json"
    if multi_index.exists():
        index_folder_id = find_or_create_folder(drive_service, "index", parent_id=parent_folder_id)
        _upload_or_update(drive_service, multi_index, index_folder_id)


def _upload_or_update(drive_service, file_path: Path, parent_folder_id: str) -> None:
    content = file_path.read_bytes()
    mime = "text/plain"
    media = MediaInMemoryUpload(content, mimetype=mime, resumable=False)

    q = (
        f"name='{file_path.name}' and '{parent_folder_id}' in parents and trashed=false"
    )
    existing = drive_service.files().list(q=q, fields="files(id)").execute().get("files", [])

    if existing:
        drive_service.files().update(
            fileId=existing[0]["id"],
            media_body=media,
        ).execute()
    else:
        drive_service.files().create(
            body={"name": file_path.name, "parents": [parent_folder_id]},
            media_body=media,
            fields="id",
        ).execute()
    print(f"  Uploaded: {file_path.name}")
