#!/usr/bin/env python3
"""
Build the PageIndex from cleaned corpus files.

This is the final step of the ingestion pipeline. Run after the corpus has been
cleaned (data/pipeline/latest/02_ai_cleaned/en_*.md).

Produces:
  <output-dir>/index_<docname>.json   — per-document PageIndex
  <output-dir>/multi_index.json       — multi-document routing index

Paths in multi_index.json are stored relative to the output directory so the
index can be moved or mounted at any path (e.g. /data/index/ in Cloud Run).

Usage:
    python3 tools/build_index.py [--output-dir data/index/] [--corpus-dir data/pipeline/latest/02_ai_cleaned/]

Run this:
  - Before the first deploy of the knowledge service
  - After corpus files are updated (ingestion pipeline output changes)

Requires: gcloud auth application-default login (or ADC already configured)
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add src/knowledge/ to path so `indexer` package resolves (matches container layout)
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "knowledge"))

import vertexai

from indexer.config import GCP_PROJECT, REGION
from indexer.pageindex import build_index
from indexer.multi import build_multi_index

DEFAULT_CORPUS_DIR = Path("data/pipeline/latest/02_ai_cleaned")
DEFAULT_OUTPUT_DIR = Path("data/index")


async def build_all(corpus_dir: Path, output_dir: Path) -> None:
    vertexai.init(project=GCP_PROJECT, location=REGION)

    md_files = sorted(f for f in corpus_dir.iterdir() if f.name.startswith("en_") and f.suffix == ".md")
    if not md_files:
        print(f"ERROR: No en_*.md files found in {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building indexes for {len(md_files)} file(s) → {output_dir}")

    per_doc_paths: list[Path] = []
    for md_path in md_files:
        out_path = output_dir / f"index_{md_path.stem}.json"
        print(f"\n[{md_path.name}] → {out_path.name}")
        await build_index(md_path, out_path)
        per_doc_paths.append(out_path)

    print(f"\nBuilding multi-index from {len(per_doc_paths)} document(s)...")
    multi_path = output_dir / "multi_index.json"
    multi_index = build_multi_index(per_doc_paths, multi_path)

    # Rewrite index_path to be relative to the output directory.
    # build_multi_index writes absolute paths; the service needs portable relative paths.
    for doc in multi_index["documents"]:
        doc["index_path"] = Path(doc["index_path"]).name
    multi_path.write_text(json.dumps(multi_index, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone. Set KNOWLEDGE_INDEX_PATH={multi_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    args = parser.parse_args()

    asyncio.run(build_all(args.corpus_dir, args.output_dir))


if __name__ == "__main__":
    main()
