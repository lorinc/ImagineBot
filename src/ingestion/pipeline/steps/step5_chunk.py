"""
Step 5 — Split prose markdown into per-section chunks.

Input:  /tmp/pipeline/03_chunked/<stem>_prose.md
Output: /tmp/pipeline/03_chunked/<stem>_chunk_NN.md

Splitting rule: each ## heading starts a new chunk.
"""

import re
from pathlib import Path
from ...log import info, warning

_H2 = re.compile(r"^## ", re.MULTILINE)


def _split_on_h2(text: str) -> list[str]:
    """Split *text* into sections at every ## heading."""
    positions = [m.start() for m in _H2.finditer(text)]

    if not positions:
        return [text.strip()] if text.strip() else []

    sections = []
    preamble = text[: positions[0]].strip()
    if preamble:
        sections.append(preamble)

    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)

    return sections


def run(run_dir: Path, stems: list[str]) -> dict[str, list[Path]]:
    """
    Chunk each prose file into per-section files.

    Returns a dict mapping stem → list of chunk Paths produced.
    """
    info("Step 5 started", step=5, stem_count=len(stems))

    chunk_dir = run_dir / "03_chunked"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: dict[str, list[Path]] = {}

    for stem in stems:
        prose_path = chunk_dir / f"{stem}_prose.md"
        if not prose_path.exists():
            warning("Missing prose file", step=5, stem=stem)
            continue

        existing = sorted(chunk_dir.glob(f"{stem}_chunk_*.md"))
        if existing:
            info("Skipping: already chunked", step=5, stem=stem, chunks=len(existing))
            all_chunks[stem] = existing
            continue

        text = prose_path.read_text(encoding="utf-8")
        sections = _split_on_h2(text)

        if not sections:
            warning("Empty after split", step=5, stem=stem)
            continue

        chunk_paths = []
        for n, section in enumerate(sections, start=1):
            chunk_path = chunk_dir / f"{stem}_chunk_{n:02d}.md"
            chunk_path.write_text(section, encoding="utf-8")
            chunk_paths.append(chunk_path)

        all_chunks[stem] = chunk_paths
        info("Chunked", step=5, stem=stem, chunks=len(chunk_paths))

    total = sum(len(v) for v in all_chunks.values())
    info("Step 5 complete", step=5, total_chunks=total, docs=len(all_chunks))
    return all_chunks
