"""
Step 4 — Convert markdown tables to prose sentences.

Input:  data/pipeline/<run_id>/02_ai_cleaned/<stem>.md
Output: data/pipeline/<run_id>/03_chunked/<stem>_prose.md  (intermediate)

Thin wrapper around src.ingestion.table_to_prose.
"""

from pathlib import Path
from ...table_to_prose import table_to_prose


def run(run_dir: Path, stems: list[str]) -> list[str]:
    """
    Apply table_to_prose to each stem in 02_ai_cleaned/.
    Writes intermediate prose files to 03_chunked/ before chunking.
    Returns list of stems successfully converted.
    """
    print("=== Step 4: Table → Prose ===")

    in_dir = run_dir / "02_ai_cleaned"
    out_dir = run_dir / "03_chunked"
    out_dir.mkdir(parents=True, exist_ok=True)

    converted = []
    for stem in stems:
        out_path = out_dir / f"{stem}_prose.md"
        if out_path.exists():
            print(f"  Skipping (already converted): {stem}")
            converted.append(stem)
            continue

        in_path = in_dir / f"{stem}.md"
        if not in_path.exists():
            print(f"  MISSING cleaned: {stem}.md — skipping")
            continue

        text = in_path.read_text(encoding="utf-8")
        prose = table_to_prose(text)
        out_path.write_text(prose, encoding="utf-8")
        print(f"  Converted: {stem}")
        converted.append(stem)

    print(f"  Step 4 complete: {len(converted)} file(s)\n")
    return converted
