"""
Ingestion pipeline orchestrator.

Usage:
    python3 -m src.ingestion.pipeline.run --all
    python3 -m src.ingestion.pipeline.run --step1
    python3 -m src.ingestion.pipeline.run --step2
    python3 -m src.ingestion.pipeline.run --step3
    python3 -m src.ingestion.pipeline.run --step4
    python3 -m src.ingestion.pipeline.run --step5
    python3 -m src.ingestion.pipeline.run --step6 [--clear]
    python3 -m src.ingestion.pipeline.run --from-step2   # skip upload, re-use Drive docs

Run ID format: YYYY-MM-DD_NNN (auto-incremented).
Output: data/pipeline/<run_id>/ with staged step directories.
data/pipeline/latest  symlink updated after each run.
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from .config import PIPELINE_DIR
from .auth_oauth import get_drive_service, get_docs_service


# ── Run ID ────────────────────────────────────────────────────────────────────

def _next_run_id() -> str:
    today = date.today().strftime("%Y-%m-%d")
    existing = sorted(PIPELINE_DIR.glob(f"{today}_*")) if PIPELINE_DIR.exists() else []
    n = len(existing) + 1
    return f"{today}_{n:03d}"


def _setup_run_dir(run_id: str) -> Path:
    run_dir = PIPELINE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({"run_id": run_id, "files": {}}, indent=2))
    return run_dir


def _update_symlink(run_dir: Path):
    latest = PIPELINE_DIR / "latest"
    if latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir.name)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ImagineBot ingestion pipeline")
    parser.add_argument("--all", action="store_true", help="Run all steps (1–6)")
    parser.add_argument("--from-step2", action="store_true", help="Skip upload; run steps 2–5")
    parser.add_argument("--step1", action="store_true")
    parser.add_argument("--step2", action="store_true")
    parser.add_argument("--step3", action="store_true")
    parser.add_argument("--step4", action="store_true")
    parser.add_argument("--step5", action="store_true")
    parser.add_argument("--step6", action="store_true", help="Ingest chunks into Graphiti")
    parser.add_argument("--clear", action="store_true", help="Wipe Graphiti graph before step 6")
    parser.add_argument("--en-only", action="store_true", help="Step 6: ingest only en_* chunks")
    parser.add_argument("--run-id", help="Reuse an existing run ID instead of creating a new one")
    args = parser.parse_args()

    if not any([args.all, args.from_step2, args.step1, args.step2, args.step3,
                args.step4, args.step5, args.step6]):
        parser.error("Specify at least one of: --all --from-step2 --step1..6")

    run_id = args.run_id or _next_run_id()
    run_dir = _setup_run_dir(run_id)
    print(f"\nRun ID: {run_id}")
    print(f"Output: {run_dir}\n")

    do_step1 = args.all or args.step1
    do_step2 = args.all or args.from_step2 or args.step2
    do_step3 = args.all or args.from_step2 or args.step3
    do_step4 = args.all or args.from_step2 or args.step4
    do_step5 = args.all or args.from_step2 or args.step5
    do_step6 = args.all or args.step6

    drive_service = docs_service = None
    gdocs = []
    stems = []

    # ── Step 1 ────────────────────────────────────────────────────────────────
    if do_step1:
        if drive_service is None:
            drive_service = get_drive_service()
        from .steps.step1_docx_to_gdocs import run as step1
        gdocs = step1(drive_service, run_dir)
        stems = [d["name"] for d in gdocs]

    # ── Step 2 ────────────────────────────────────────────────────────────────
    if do_step2:
        if drive_service is None:
            drive_service = get_drive_service()
        if docs_service is None:
            docs_service = get_docs_service()
        from .steps.step2_gdocs_to_md import run as step2
        stems = step2(drive_service, docs_service, run_dir, gdocs)

    # ── Steps 3–5: derive stems from local DOCX files (authoritative list) ─────
    if (do_step3 or do_step4 or do_step5) and not stems:
        from .config import DOCX_DIR
        stems = sorted(p.stem for p in DOCX_DIR.glob("*.docx"))
        if not stems:
            print("ERROR: No DOCX files found in data/docx/ — cannot derive stem list")
            sys.exit(1)

    # ── Step 3 ────────────────────────────────────────────────────────────────
    if do_step3:
        from .steps.step3_ai_cleanup import run as step3
        stems = step3(run_dir, stems)

    # ── Step 4 ────────────────────────────────────────────────────────────────
    if do_step4:
        if not stems:
            cleaned_dir = run_dir / "02_ai_cleaned"
            stems = [p.stem for p in sorted(cleaned_dir.glob("*.md"))] if cleaned_dir.exists() else []
        from .steps.step4_table_to_prose import run as step4
        stems = step4(run_dir, stems)

    # ── Step 5 ────────────────────────────────────────────────────────────────
    if do_step5:
        from .steps.step5_chunk import run as step5
        chunks = step5(run_dir, stems)
        total = sum(len(v) for v in chunks.values())
        print(f"Step 5 complete. {total} chunk file(s) in {run_dir / '03_chunked'}\n")

    # ── Step 6 ────────────────────────────────────────────────────────────────
    if do_step6:
        chunk_dir = run_dir / "03_chunked"
        if not chunk_dir.exists():
            print("ERROR: 03_chunked/ not found — run steps 1–5 first")
            sys.exit(1)

        all_chunks = sorted(chunk_dir.glob("*_chunk_*.md"))
        if args.en_only:
            all_chunks = [p for p in all_chunks if p.name.startswith("en_")]
            print(f"--en-only: {len(all_chunks)} English chunk(s) selected\n")

        from .steps.step6_ingest import run as step6
        asyncio.run(step6(run_dir, all_chunks, clear=args.clear))

    _update_symlink(run_dir)
    print(f"\nSymlink updated: data/pipeline/latest → {run_id}\n")


if __name__ == "__main__":
    main()
