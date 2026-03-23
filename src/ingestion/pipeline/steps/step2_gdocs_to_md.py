"""
Step 2 — Export Google Docs to baseline Markdown, saved locally.

Input:  Google Drive folder DRIVE_GDOCS_FOLDER (list from Step 1)
Output: data/pipeline/<run_id>/01_baseline_md/<stem>.md

Also saves a <stem>_styles.json alongside each .md with font-size metadata,
which Step 3 uses to fix header hierarchy.
"""

import json
from pathlib import Path
from ..config import DRIVE_GDOCS_FOLDER
from ..drive_utils import find_or_create_folder, list_google_docs_in_folder


def _export_markdown(drive_service, gdoc_id: str) -> str:
    content = drive_service.files().export(
        fileId=gdoc_id, mimeType="text/markdown"
    ).execute()
    return content.decode("utf-8")


def _extract_styles(docs_service, gdoc_id: str) -> list[dict]:
    doc = docs_service.documents().get(documentId=gdoc_id).execute()
    styles = []
    for item in doc.get("body", {}).get("content", []):
        if "paragraph" not in item:
            continue
        text = "".join(
            e.get("textRun", {}).get("content", "")
            for e in item["paragraph"].get("elements", [])
        )
        size = 11
        elements = item["paragraph"].get("elements", [])
        if elements:
            size_data = (
                elements[0]
                .get("textRun", {})
                .get("textStyle", {})
                .get("fontSize", {})
            )
            size = size_data.get("magnitude", 11)
        if text.strip():
            styles.append({"text": text.strip(), "size": size})
    return styles


def run(drive_service, docs_service, run_dir: Path, gdocs: list[dict]) -> list[str]:
    """
    Export each Google Doc to Markdown.

    *gdocs* is the list returned by step1 (each item has 'name' and 'gdoc_id').
    Returns list of source stems successfully exported.
    """
    print("=== Step 2: Google Docs → Baseline Markdown ===")

    out_dir = run_dir / "01_baseline_md"
    out_dir.mkdir(parents=True, exist_ok=True)

    # If gdocs list is empty (step1 skipped), discover from Drive —
    # but filter to only stems that match our local DOCX files.
    if not gdocs:
        from ..config import DOCX_DIR
        from ..drive_utils import find_or_create_folder
        local_stems = {p.stem for p in DOCX_DIR.glob("*.docx")}
        folder_id = find_or_create_folder(drive_service, DRIVE_GDOCS_FOLDER)
        gdocs_raw = list_google_docs_in_folder(drive_service, folder_id)
        gdocs = [
            {"name": d["name"], "gdoc_id": d["id"]}
            for d in gdocs_raw
            if d["name"] in local_stems
        ]

    exported = []
    for doc in gdocs:
        stem = doc["name"]
        md_path = out_dir / f"{stem}.md"
        styles_path = out_dir / f"{stem}_styles.json"

        if md_path.exists():
            print(f"  Skipping (already exported): {stem}")
            exported.append(stem)
            continue

        print(f"  Exporting: {stem} ...", end=" ", flush=True)
        try:
            md = _export_markdown(drive_service, doc["gdoc_id"])
            styles = _extract_styles(docs_service, doc["gdoc_id"])
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        md_path.write_text(md, encoding="utf-8")
        styles_path.write_text(json.dumps(styles, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"done ({len(md):,} chars)")
        exported.append(stem)

    print(f"  Step 2 complete: {len(exported)} file(s) in {out_dir}\n")
    return exported
