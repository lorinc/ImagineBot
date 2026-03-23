#!/usr/bin/env python3
"""
validate.py — Local Graphiti validation against school document corpus.

Usage:
    python validate.py            # ingest + query
    python validate.py --ingest   # ingest only
    python validate.py --query    # query only (requires prior ingest)
    python validate.py --ingest --clear  # wipe graph, then ingest

The 'credentials' file in the repo root is read automatically.
Individual env vars override credentials file values.
"""

import argparse
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

CORPUS_DIR = Path(__file__).parent / "REFERENCE_REPOS/MD2RAG/markdowns"

SOURCES = {
    "run_20260309_204409_EN_Policies_1. CHILD PROTECTION.md": "child-protection",
    "run_20260309_204409_EN_Policies_2. TECHNOLOGY.md": "technology-policy",
    "run_20260309_204409_EN_Policies_3. HEALTH, SAFETY AND REPORTING.md": "health-safety",
    "run_20260309_204409_EN_Policies_4. TRIPS&OUTINGS.md": "trips-outings",
    "run_20260309_204409_EN_Policies_5. CODE OF CONDUCT.md": "code-of-conduct",
    "run_20260309_204409_EN_Manual de familias_24_25 (3).md": "family-manual",
}

# Reference time: school year start — facts in these docs "became true" then
REFERENCE_TIME = datetime(2024, 9, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Test queries
# ---------------------------------------------------------------------------

TEST_QUERIES = [
    {
        "description": "Cross-document: medication rules (trips-outings + health-safety)",
        "query": "What are the rules for administering student medication during school trips?",
        "group_ids": None,  # all sources
    },
    {
        "description": "Single-source: school start and end times",
        "query": "What time does school start and end each day?",
        "group_ids": ["family-manual"],
    },
    {
        "description": "group_id filter check: missing child on outing (trips-outings only)",
        "query": "What should staff do if a child goes missing on a school outing?",
        "group_ids": ["trips-outings"],
    },
    {
        "description": "Cross-document: mobile phone rules",
        "query": "When are students allowed to use mobile phones?",
        "group_ids": None,
    },
]

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _load_creds_file(path: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    last_key: str | None = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            last_key = key.strip()
            creds[last_key] = "".join(value.split())
        elif last_key:
            # Continuation line — value was split across lines
            creds[last_key] += "".join(line.split())
    return creds


def _get(creds: dict, *keys: str) -> str:
    for key in keys:
        v = os.environ.get(key) or creds.get(key)
        if v:
            return "".join(v.split())  # normalise whitespace
    raise ValueError(f"Missing credential — tried: {', '.join(keys)}")


def load_config() -> dict[str, str]:
    creds_path = Path(__file__).parent / "credentials"
    creds = _load_creds_file(creds_path) if creds_path.exists() else {}

    return {
        "neo4j_uri": _get(creds, "NEO4J_URI"),
        "neo4j_user": _get(creds, "NEO4J_USER", "NEO4J_USERNAME"),
        "neo4j_password": _get(creds, "NEO4J_PASSWORD"),
        "openai_api_key": _get(creds, "OPENAI_API_KEY"),
    }

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

async def ingest(graphiti: Graphiti, clear: bool) -> None:
    if clear:
        print("Clearing graph (MATCH (n) DETACH DELETE n)...")
        await graphiti.driver.execute_query("MATCH (n) DETACH DELETE n")
        print("Done.\n")

    print("Building indices and constraints...")
    await graphiti.build_indices_and_constraints()
    print("Done.\n")

    for filename, source_id in SOURCES.items():
        path = CORPUS_DIR / filename
        if not path.exists():
            print(f"SKIP (not found): {filename}")
            continue

        content = path.read_text()
        print(f"Ingesting [{source_id}]  ({len(content):,} chars)...", end=" ", flush=True)

        await graphiti.add_episode(
            name=source_id,
            episode_body=content,
            source_description=f"School document: {filename}",
            reference_time=REFERENCE_TIME,
            source=EpisodeType.text,
            group_id=source_id,
        )

        print("done")

    print("\nIngestion complete.\n")

# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

async def run_queries(graphiti: Graphiti) -> None:
    passed = 0

    for test in TEST_QUERIES:
        q = test["query"]
        group_ids = test["group_ids"]
        scope = ", ".join(group_ids) if group_ids else "all sources"

        print("=" * 70)
        print(f"QUERY : {q}")
        print(f"SCOPE : {scope}")
        print(f"NOTE  : {test['description']}")
        print()

        results = await graphiti.search(
            query=q,
            group_ids=group_ids,
            num_results=5,
        )

        if not results:
            print("  [no results]\n")
            continue

        for i, edge in enumerate(results, 1):
            print(f"  [{i}] {edge.fact}")
            print(f"       source episodes : {edge.episodes}")
            if edge.valid_at:
                print(f"       valid_at         : {edge.valid_at}")
            if edge.invalid_at:
                print(f"       invalid_at       : {edge.invalid_at}")
            print()

        passed += 1

    print("=" * 70)
    print(f"\nResult: {passed}/{len(TEST_QUERIES)} queries returned results.")
    if passed == len(TEST_QUERIES):
        print("PASS — Graphiti is working. Proceed to GCP provisioning.")
    else:
        print("PARTIAL — review missing results above before proceeding.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest", action="store_true", help="Run ingestion")
    parser.add_argument("--query", action="store_true", help="Run queries")
    parser.add_argument("--clear", action="store_true", help="Wipe graph before ingest")
    args = parser.parse_args()

    run_ingest = args.ingest or (not args.ingest and not args.query)
    run_query = args.query or (not args.ingest and not args.query)

    config = load_config()
    os.environ["OPENAI_API_KEY"] = config["openai_api_key"]

    graphiti = Graphiti(
        uri=config["neo4j_uri"],
        user=config["neo4j_user"],
        password=config["neo4j_password"],
    )

    try:
        if run_ingest:
            await ingest(graphiti, clear=args.clear)
        if run_query:
            await run_queries(graphiti)
    finally:
        await graphiti.close()


if __name__ == "__main__":
    asyncio.run(main())
