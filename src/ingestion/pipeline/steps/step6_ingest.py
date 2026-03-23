"""
Step 6 — Ingest chunks into Graphiti (Neo4j knowledge graph).

Input:  data/pipeline/<run_id>/03_chunked/<stem>_chunk_<NN>.md
Output: Neo4j graph + data/pipeline/<run_id>/04_ingested/<stem>.done  (idempotency marker)

group_id = source stem (e.g. "en_policy1_child_protection")
episode name = chunk filename stem (e.g. "en_policy1_child_protection_chunk_03")

Idempotent: presence of 04_ingested/<stem>.done skips that source entirely.
To re-ingest a source: delete its .done marker and re-run.
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

# School year start — facts in these docs "became true" at this point
REFERENCE_TIME = datetime(2024, 9, 1, tzinfo=timezone.utc)

CUSTOM_EXTRACTION_INSTRUCTIONS = """
Extract ALL operational facts, not just named-entity relationships.
Include facts where one side is implicit:
  - times and schedules ("school starts at 9:00 AM" → school STARTS_AT 9:00 AM)
  - procedures ("parents must sign the consent form" → parents MUST consent_form)
  - contact details, locations, platform names
Do not skip a fact because it lacks two named entities.
"""


def _source_stem(chunk_path: Path) -> str:
    """Extract source stem from chunk filename: en_policy1_child_protection_chunk_01 → en_policy1_child_protection"""
    name = chunk_path.stem  # e.g. en_policy1_child_protection_chunk_01
    idx = name.rfind("_chunk_")
    return name[:idx] if idx != -1 else name


async def _clear_graph(graphiti: Graphiti) -> None:
    print("Clearing graph (MATCH (n) DETACH DELETE n)...")
    await graphiti.driver.execute_query("MATCH (n) DETACH DELETE n")
    print("Rebuilding indices and constraints...")
    await graphiti.build_indices_and_constraints()
    print("Done.\n")


async def _ingest_chunks(graphiti: Graphiti, run_dir: Path, chunk_paths: list[Path]) -> None:
    done_dir = run_dir / "04_ingested"
    done_dir.mkdir(parents=True, exist_ok=True)

    # Group chunks by source stem
    by_source: dict[str, list[Path]] = {}
    for p in sorted(chunk_paths):
        stem = _source_stem(p)
        by_source.setdefault(stem, []).append(p)

    total_sources = len(by_source)
    for i, (source_stem, chunks) in enumerate(sorted(by_source.items()), 1):
        done_marker = done_dir / f"{source_stem}.done"
        if done_marker.exists():
            print(f"[{i}/{total_sources}] Skipping (already ingested): {source_stem}")
            continue

        print(f"[{i}/{total_sources}] Ingesting {source_stem} ({len(chunks)} chunks)...")
        for chunk_path in sorted(chunks):
            content = chunk_path.read_text(encoding="utf-8")
            episode_name = chunk_path.stem
            print(f"  {episode_name} ({len(content):,} chars)...", end=" ", flush=True)
            await graphiti.add_episode(
                name=episode_name,
                episode_body=content,
                source_description=f"School document chunk: {chunk_path.name}",
                reference_time=REFERENCE_TIME,
                source=EpisodeType.text,
                group_id=source_stem,
                custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
            )
            print("done")

        done_marker.write_text(datetime.now(timezone.utc).isoformat())
        print(f"  Marked done: {done_marker.name}\n")

    print(f"Ingestion complete.")


async def run(run_dir: Path, chunk_paths: list[Path], clear: bool = False) -> None:
    from ..config import PROJECT_ROOT

    creds_path = PROJECT_ROOT / "credentials"

    def _load_creds(path: Path) -> dict[str, str]:
        creds: dict[str, str] = {}
        last_key = None
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                last_key = key.strip()
                creds[last_key] = "".join(value.split())
            elif last_key:
                creds[last_key] += "".join(line.split())
        return creds

    creds = _load_creds(creds_path)

    def _get(*keys):
        for k in keys:
            v = os.environ.get(k) or creds.get(k)
            if v:
                return "".join(v.split())
        raise ValueError(f"Missing credential — tried: {', '.join(keys)}")

    os.environ["OPENAI_API_KEY"] = _get("OPENAI_API_KEY")

    graphiti = Graphiti(
        uri=_get("NEO4J_URI"),
        user=_get("NEO4J_USER", "NEO4J_USERNAME"),
        password=_get("NEO4J_PASSWORD"),
    )

    try:
        if clear:
            await _clear_graph(graphiti)
        await _ingest_chunks(graphiti, run_dir, chunk_paths)
    finally:
        await graphiti.close()
