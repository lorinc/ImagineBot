#!/usr/bin/env python3
"""
Print a summary of the latest ingestion run_report.json from GCS.

Usage:
  python3 tools/status.py [--source SOURCE_ID] [--bucket BUCKET] [--debug]

Flags:
  --source   GCS source_id prefix (default: tech_poc)
  --bucket   GCS bucket name      (default: img-dev-index)
  --debug    Show per-file detail
"""
import argparse
import json
import sys

from google.cloud import storage as gcs


def _status_badge(status: str) -> str:
    return {"ok": "OK", "partial_failure": "PARTIAL", "aborted": "ABORTED", "failed": "FAILED"}.get(
        status, status.upper()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Show latest ingestion run status")
    parser.add_argument("--source", default="tech_poc")
    parser.add_argument("--bucket", default="img-dev-index")
    parser.add_argument("--debug", action="store_true", help="Show per-file detail")
    args = parser.parse_args()

    client = gcs.Client()
    blob = client.bucket(args.bucket).blob(f"{args.source}/run_report.json")

    if not blob.exists():
        print(f"No run_report.json found at gs://{args.bucket}/{args.source}/run_report.json")
        sys.exit(1)

    report = json.loads(blob.download_as_text())

    status = report.get("status", "unknown")
    badge = _status_badge(status)
    run_id = report.get("run_id", "—")
    trigger = report.get("trigger", "—")
    started_at = report.get("started_at", "—")
    finished_at = report.get("finished_at", "—")
    index_updated = report.get("index_updated", False)
    index_version_live = report.get("index_version_live") or "—"
    index_age_hours = report.get("index_age_hours")
    cost_total = report.get("cost_total_usd", 0.0)
    files = report.get("files", [])

    ok_count = sum(1 for f in files if f.get("status") == "ok")
    failed_count = sum(1 for f in files if f.get("status") == "failed")

    age_str = f"{index_age_hours}h ago" if index_age_hours is not None else "—"

    print(f"Status:        {badge}")
    print(f"Run ID:        {run_id}")
    print(f"Trigger:       {trigger}")
    print(f"Started:       {started_at}")
    print(f"Finished:      {finished_at}")
    print(f"Index updated: {'yes' if index_updated else 'no'}  (live: {index_version_live}, age: {age_str})")
    print(f"Files:         {ok_count} ok, {failed_count} failed  (total: {len(files)})")
    print(f"Cost:          ${cost_total:.4f}")

    if failed_count:
        print("\nFailed files:")
        for f in files:
            if f.get("status") == "failed":
                url = f.get("drive_url", "")
                url_str = f"  {url}" if url else ""
                print(f"  {f['name']}  [{f.get('error_type', '?')}]  {f.get('error_detail', '')} {url_str}".rstrip())

    if args.debug and files:
        print("\nAll files:")
        for f in files:
            if f.get("status") == "ok":
                steps = ",".join(str(s) for s in f.get("steps_completed", []))
                chunks = f.get("chunks", 0)
                print(f"  OK   {f['name']}  steps=[{steps}]  chunks={chunks}")
            else:
                step = f.get("failed_at_step", "?")
                print(f"  FAIL {f['name']}  step={step}  [{f.get('error_type', '?')}]  {f.get('error_detail', '')}")


if __name__ == "__main__":
    main()
