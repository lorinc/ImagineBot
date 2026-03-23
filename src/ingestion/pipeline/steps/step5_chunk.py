"""
Step 5 — Split prose markdown into per-section chunks.

Input:  data/pipeline/<run_id>/03_chunked/<stem>_prose.md
Output: data/pipeline/<run_id>/03_chunked/<stem>_chunk_NN.md

Splitting rule: each ## heading starts a new chunk.
Chunk filenames: <stem>_chunk_01.md, <stem>_chunk_02.md, …

The _prose.md intermediates are kept for debugging but are not the final output.
"""

import re
from pathlib import Path

_H2 = re.compile(r"^## ", re.MULTILINE)


def _split_on_h2(text: str) -> list[str]:
    """Split *text* into sections at every ## heading."""
    positions = [m.start() for m in _H2.finditer(text)]

    if not positions:
        # No ## headings — whole document is one chunk
        return [text.strip()] if text.strip() else []

    sections = []
    # Content before first ## (preamble) — include if non-empty
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
    print("=== Step 5: Semantic Chunking ===")

    chunk_dir = run_dir / "03_chunked"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: dict[str, list[Path]] = {}

    for stem in stems:
        prose_path = chunk_dir / f"{stem}_prose.md"
        if not prose_path.exists():
            print(f"  MISSING prose file: {prose_path.name} — skipping")
            continue

        # Check if chunks already exist
        existing = sorted(chunk_dir.glob(f"{stem}_chunk_*.md"))
        if existing:
            print(f"  Skipping (already chunked): {stem} ({len(existing)} chunks)")
            all_chunks[stem] = existing
            continue

        text = prose_path.read_text(encoding="utf-8")
        sections = _split_on_h2(text)

        if not sections:
            print(f"  {stem}: empty after split — skipping")
            continue

        chunk_paths = []
        for n, section in enumerate(sections, start=1):
            chunk_path = chunk_dir / f"{stem}_chunk_{n:02d}.md"
            chunk_path.write_text(section, encoding="utf-8")
            chunk_paths.append(chunk_path)

        all_chunks[stem] = chunk_paths
        print(f"  Chunked: {stem} → {len(chunk_paths)} chunk(s)")

    total = sum(len(v) for v in all_chunks.values())
    print(f"  Step 5 complete: {total} chunk file(s) across {len(all_chunks)} doc(s)\n")
    return all_chunks
