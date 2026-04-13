#!/usr/bin/env python3
"""
Create (or refresh) the Vertex AI context cache from canonical corpus files.

Reads all en_*.md files from data/pipeline/latest/02_ai_cleaned/, uploads them
to Vertex AI as a cached context, then writes the cache name to Firestore so all
knowledge service instances can discover it.

Usage:
    python3 tools/create_cache.py [--ttl-hours 48] [--dry-run]

Run this:
  - Before the first deploy of the knowledge service (creates the initial cache)
  - After corpus files are updated (weekly refresh — old cache is deleted)

Requires: gcloud auth application-default login (or ADC already configured)
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vertexai
from google.cloud import firestore
from vertexai.generative_models import Content, Part
from vertexai.preview.caching import CachedContent
from vertexai.preview.generative_models import GenerativeModel  # noqa: F401 — confirms preview import works

GCP_PROJECT = "img-dev-490919"
REGION = "europe-west1"
MODEL = "gemini-2.5-flash"
CORPUS_DIR = Path(__file__).parent.parent / "data" / "pipeline" / "latest" / "02_ai_cleaned"
FIRESTORE_COLLECTION = "config"
FIRESTORE_DOCUMENT = "context_cache"


def load_corpus() -> tuple[str, list[str]]:
    """Returns (combined corpus text, list of source_ids loaded)."""
    files = sorted(f for f in CORPUS_DIR.iterdir() if f.name.startswith("en_") and f.suffix == ".md")
    if not files:
        print(f"ERROR: No en_*.md files found in {CORPUS_DIR}", file=sys.stderr)
        sys.exit(1)

    source_ids = [f.stem for f in files]
    parts = []
    for f in files:
        parts.append(f"# Document: {f.stem}\n\n{f.read_text().strip()}")

    corpus = "\n\n---\n\n".join(parts)
    return corpus, source_ids


def delete_existing_cache(db: firestore.Client) -> None:
    doc = db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOCUMENT).get()
    if not doc.exists:
        return
    old_cache_name = doc.to_dict().get("cache_name")
    if not old_cache_name:
        return
    try:
        old = CachedContent.get(old_cache_name)
        old.delete()
        print(f"Deleted old cache: {old_cache_name}", file=sys.stderr)
    except Exception as e:
        print(f"Could not delete old cache {old_cache_name}: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ttl-hours", type=int, default=48, help="Cache TTL in hours (default: 48)")
    parser.add_argument("--dry-run", action="store_true", help="Load corpus and print token estimate without creating cache")
    args = parser.parse_args()

    corpus, source_ids = load_corpus()
    print(f"Loaded {len(source_ids)} files: {source_ids}", file=sys.stderr)
    print(f"Corpus size: ~{len(corpus) // 4} tokens (estimated)", file=sys.stderr)

    if args.dry_run:
        print(corpus[:500] + "\n...", file=sys.stderr)
        print("DRY RUN — no cache created.", file=sys.stderr)
        return

    vertexai.init(project=GCP_PROJECT, location=REGION)
    db = firestore.Client(project=GCP_PROJECT)

    print("Deleting existing cache (if any)...", file=sys.stderr)
    delete_existing_cache(db)

    system_instruction = (
        "You are a school information assistant. "
        "Answer questions using ONLY the information in the provided documents. "
        "- Cite the exact document source_id for every claim you make. "
        "- If the documents do not contain enough information to answer, set answer to exactly: "
        '"I don\'t have that information in the school documents." and citations to []. '
        "- Never invent, extrapolate, or guess. "
        "- Answer in the same language the question was written in."
    )

    print(f"Creating context cache (TTL: {args.ttl_hours}h)...", file=sys.stderr)
    cached = CachedContent.create(
        model_name=MODEL,
        system_instruction=system_instruction,
        contents=[Content(role="user", parts=[Part.from_text(corpus)])],
        ttl=timedelta(hours=args.ttl_hours),
    )
    print(f"Cache created: {cached.name}", file=sys.stderr)

    now = datetime.now(timezone.utc)
    db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOCUMENT).set({
        "cache_name": cached.name,
        "created_at": now,
        "expires_at": now + timedelta(hours=args.ttl_hours),
        "source_ids": source_ids,
    })
    print("Firestore updated.", file=sys.stderr)

    # Print cache name to stdout for scripting
    print(cached.name)


if __name__ == "__main__":
    main()
