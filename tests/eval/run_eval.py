"""
Eval harness against the live gateway.

Usage:
    python tests/eval/run_eval.py [--gateway URL] [--filter ID_PREFIX]

Options:
    --gateway   Gateway base URL (default: $GATEWAY_URL or http://localhost:8080)
    --filter    Only run items whose id starts with PREFIX (e.g. fd, poly, ce)
    --verbose   Print full answer text for each item
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import requests

GOLDEN = Path(__file__).parent / "golden.jsonl"
DEFAULT_GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8080")


def load_items(filter_prefix: str | None) -> list[dict]:
    items = []
    with GOLDEN.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("skip"):
                continue
            if filter_prefix and not item["id"].startswith(filter_prefix):
                continue
            items.append(item)
    return items


def send_turn(gateway: str, session_id: str, message: str) -> str:
    """POST one turn to /chat (SSE), return the answer text."""
    url = f"{gateway}/chat"
    payload = {"message": message, "session_id": session_id}
    answer = None
    with requests.post(url, json=payload, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode()
            if line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
            elif line.startswith("event:"):
                event_type = line[6:].strip()
                if event_type == "answer":
                    pass  # handled via data parsing below
            else:
                continue
            if "answer" in data:
                answer = data["answer"]
    if answer is None:
        raise RuntimeError("No answer event received from gateway")
    return answer


def evaluate_item(gateway: str, item: dict, verbose: bool) -> dict:
    item_id = item["id"]
    session_id = str(uuid.uuid4())

    prior_turns = item.get("prior_turns", [])
    for turn in prior_turns:
        send_turn(gateway, session_id, turn["content"])

    answer = send_turn(gateway, session_id, item["query"])

    answer_lower = answer.lower()
    missing_facts = [
        f for f in item.get("expected_facts", [])
        if f.lower() not in answer_lower
    ]
    forbidden_hits = [
        f for f in item.get("must_not_contain", [])
        if f.lower() in answer_lower
    ]

    passed = not missing_facts and not forbidden_hits
    result = {
        "id": item_id,
        "passed": passed,
        "missing_facts": missing_facts,
        "forbidden_hits": forbidden_hits,
    }
    if verbose:
        result["answer"] = answer
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--filter", default=None, dest="filter_prefix")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    items = load_items(args.filter_prefix)
    if not items:
        print("No items to run (all skipped or filtered out).")
        sys.exit(0)

    print(f"Running {len(items)} eval items against {args.gateway}")
    results = []
    for item in items:
        print(f"  {item['id']} ...", end=" ", flush=True)
        try:
            r = evaluate_item(args.gateway, item, args.verbose)
        except Exception as exc:
            r = {"id": item["id"], "passed": False, "error": str(exc)}
        status = "PASS" if r.get("passed") else "FAIL"
        print(status)
        if not r.get("passed") or args.verbose:
            if r.get("missing_facts"):
                print(f"    missing_facts: {r['missing_facts']}")
            if r.get("forbidden_hits"):
                print(f"    forbidden_hits: {r['forbidden_hits']}")
            if r.get("error"):
                print(f"    error: {r['error']}")
            if args.verbose and r.get("answer"):
                print(f"    answer: {r['answer'][:300]}")
        results.append(r)

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"\n{passed}/{total} passed")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
