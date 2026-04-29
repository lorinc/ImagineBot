"""
Step 4 — Convert markdown tables to prose sentences.

Input:  /tmp/pipeline/02_ai_cleaned/<stem>.md
Output: /tmp/pipeline/02_ai_cleaned/<stem>.md     (overwritten in-place)
        /tmp/pipeline/03_chunked/<stem>_prose.md  (copy for step5_chunk)

Overwrites 02_ai_cleaned/ in-place so build_all() picks up the prose version.
"""

from pathlib import Path
from ...table_to_prose import table_to_prose
from ...log import info, warning


def run(run_dir: Path, stems: list[str]) -> list[str]:
    """
    Apply table_to_prose to each stem in 02_ai_cleaned/.
    Overwrites the source file in 02_ai_cleaned/ and writes a copy to 03_chunked/.
    Returns list of stems successfully converted.
    """
    info("Step 4 started", step=4, stem_count=len(stems))

    in_dir = run_dir / "02_ai_cleaned"
    out_dir = run_dir / "03_chunked"
    out_dir.mkdir(parents=True, exist_ok=True)

    converted = []
    for stem in stems:
        out_path = out_dir / f"{stem}_prose.md"
        in_path = in_dir / f"{stem}.md"

        if out_path.exists():
            info("Skipping: already converted", step=4, stem=stem)
            converted.append(stem)
            continue

        if not in_path.exists():
            warning("Missing cleaned file", step=4, stem=stem)
            continue

        text = in_path.read_text(encoding="utf-8")
        prose = table_to_prose(text)
        in_path.write_text(prose, encoding="utf-8")
        out_path.write_text(prose, encoding="utf-8")
        info("Table-to-prose done", step=4, stem=stem)
        converted.append(stem)

    info("Step 4 complete", step=4, converted=len(converted))
    return converted
