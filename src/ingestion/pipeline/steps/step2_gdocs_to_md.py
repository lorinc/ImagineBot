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

_TOC_LINE = re.compile(r"^\s*[-*]?\s*\[.+\]\(#.+\)\s*$")
_TOC_HEADING = re.compile(r"^#+\s*(table of contents|contents)\s*$", re.IGNORECASE)


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
        # Skip a TOC heading line
        if _TOC_HEADING.match(line.rstrip()):
            i += 1
            continue
        # Skip a run of anchor-link lines (TOC entries)
        if _TOC_LINE.match(line):
            while i < len(lines) and (_TOC_LINE.match(lines[i]) or lines[i].strip() == ""):
                i += 1
            # Drop trailing blank lines absorbed into the block
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


def run(drive_service, docs_service, run_dir: Path, gdocs: list[dict]) -> list[str]:
    """
    Export each Google Doc to Markdown.

    *gdocs* is the list returned by step1 (each item has 'name' and 'gdoc_id').
    Returns list of source stems successfully exported.
    """
    print("=== Step 2: Google Docs → Baseline Markdown ===")

    out_dir = run_dir / "01_baseline_md"
    out_dir.mkdir(parents=True, exist_ok=True)

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

        md_path.write_text(_strip_toc(md), encoding="utf-8")
        styles_path.write_text(json.dumps(styles, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"done ({len(md):,} chars)")
        exported.append(stem)

    print(f"  Step 2 complete: {len(exported)} file(s) in {out_dir}\n")
    return exported
