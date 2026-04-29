"""
Step 2 — Export Google Docs to baseline Markdown, saved locally.

Input:  list of {name, gdoc_id} dicts from step1
Output: /tmp/pipeline/01_baseline_md/<stem>.md

Also saves a <stem>_styles.json alongside each .md with font-size metadata,
which Step 3 uses to fix header hierarchy.
"""

import json
import re
from pathlib import Path

from googleapiclient.errors import HttpError

from ...errors import ExportEmpty, ExportServerError, NoHeadings, PermissionDenied, ValidationError
from ...log import error, info

_TOC_LINE = re.compile(r"^\s*[-*]?\s*\[.+\]\(#.+\)\s*$")
_TOC_HEADING = re.compile(r"^#+\s*(table of contents|contents)\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)

_EDITOR_URL = "https://docs.google.com/document/d/{id}/edit"
_EXPORT_EMPTY_THRESHOLD = 200


def _strip_toc(md: str) -> str:
    """Remove Table of Contents blocks produced by Google's Markdown export.

    A TOC block is a contiguous run of anchor-link lines (optionally preceded by
    a 'Table of Contents' heading) appearing before the first non-TOC heading.
    """
    lines = md.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _TOC_HEADING.match(line.rstrip()):
            i += 1
            continue
        if _TOC_LINE.match(line):
            while i < len(lines) and (_TOC_LINE.match(lines[i]) or lines[i].strip() == ""):
                i += 1
            while result and result[-1].strip() == "":
                result.pop()
            continue
        result.append(line)
        i += 1
    return "".join(result)


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


def run(
    drive_service, docs_service, run_dir: Path, gdocs: list[dict]
) -> tuple[list[str], list[ValidationError]]:
    """Export each Google Doc to Markdown and validate the result.

    Returns (stems, errors) where stems is the list of source stems that
    passed validation, and errors is a list of ValidationErrors for files
    that failed.
    """
    info("Step 2 started", step=2, doc_count=len(gdocs))

    out_dir = run_dir / "01_baseline_md"
    out_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    errors: list[ValidationError] = []

    for doc in gdocs:
        stem = doc["name"]
        drive_url = _EDITOR_URL.format(id=doc["gdoc_id"])
        md_path = out_dir / f"{stem}.md"
        styles_path = out_dir / f"{stem}_styles.json"

        if md_path.exists():
            info("Skipping: already exported", step=2, stem=stem)
            exported.append(stem)
            continue

        info("Exporting", step=2, stem=stem)
        try:
            md = _export_markdown(drive_service, doc["gdoc_id"])
            styles = _extract_styles(docs_service, doc["gdoc_id"])
        except HttpError as e:
            if e.resp.status == 403:
                err = PermissionDenied(stem, drive_url)
            else:
                err = ExportServerError(stem, drive_url)
            error("Step 2 export failed", step=2, stem=stem, error_type=err.error_type, detail=str(e))
            errors.append(err)
            continue

        stripped = _strip_toc(md)

        if len(stripped.strip()) < _EXPORT_EMPTY_THRESHOLD:
            err = ExportEmpty(stem, drive_url)
            error("Step 2 validation failed", step=2, stem=stem, error_type=err.error_type)
            errors.append(err)
            continue

        if not _HEADING.search(stripped):
            err = NoHeadings(stem, drive_url)
            error("Step 2 validation failed", step=2, stem=stem, error_type=err.error_type)
            errors.append(err)
            continue

        md_path.write_text(stripped, encoding="utf-8")
        styles_path.write_text(json.dumps(styles, indent=2, ensure_ascii=False), encoding="utf-8")
        info("Export done", step=2, stem=stem, chars=len(md))
        exported.append(stem)

    info("Step 2 complete", step=2, exported=len(exported), error_count=len(errors))
    return exported, errors
