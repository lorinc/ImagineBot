"""Run full OpenKB eval and print comparison table vs poc1."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import litellm

from eval_harness import DOCUMENTS, RESULTS_DIR, eval_document

POC1_RESULTS_DIR = Path(__file__).parent.parent / "poc1_single_doc/eval"

POC1_FILES = {
    "policy1_hard": "results_en_policy1_hard_framing.json",
    "policy3_hard": "results_en_policy3_hard_framing.json",
    "policy5": "results_en_policy5_code_of_conduct.json",
    "family_manual": "results_en_family_manual_24_25.json",
}


def _load_poc1_summary(doc_name: str) -> dict | None:
    fname = POC1_FILES.get(doc_name)
    if not fname:
        return None
    path = POC1_RESULTS_DIR / fname
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    query_count = d.get("query_count", 1) or 1
    avg_cost = d.get("total_query_cost_usd", 0) / query_count
    return {
        "accuracy": d.get("accuracy", "no_judge"),
        "avg_cost_per_query_usd": avg_cost,
        "avg_chars_read": d.get("avg_chars_to_synthesis", d.get("avg_chars_read", 0)),
        "avg_latency_ms": d.get("avg_latency_ms", 0),
    }


def _print_table(openkb_results: list[dict]) -> None:
    header = f"{'Document':<20} {'System':<10} {'Accuracy':<12} {'Avg Cost':>10} {'Avg Chars':>12} {'Avg Latency':>13}"
    sep = "-" * len(header)
    print("\n" + sep)
    print(header)
    print(sep)

    for res in openkb_results:
        doc_name = res["document"]
        poc1 = _load_poc1_summary(doc_name)
        if poc1:
            print(f"{doc_name:<20} {'poc1':<10} {poc1['accuracy']:<12} "
                  f"${poc1['avg_cost_per_query_usd']:>9.5f} "
                  f"{int(poc1['avg_chars_read']):>12,} "
                  f"{int(poc1['avg_latency_ms']):>11,}ms")

        kb_acc = res.get("accuracy", "?")
        kb_cost = res.get("avg_cost_per_query_usd", 0)
        kb_chars = res.get("avg_chars_read", 0)
        kb_lat = res.get("avg_latency_ms", 0)
        print(f"{doc_name:<20} {'openkb':<10} {str(kb_acc):<12} "
              f"${kb_cost:>9.5f} "
              f"{int(kb_chars):>12,} "
              f"{int(kb_lat):>11,}ms")
        print(sep)


async def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        creds_file = Path(__file__).parent / "credentials"
        if creds_file.exists():
            for line in creds_file.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set (env or poc/openkb_eval/credentials)")
    litellm.api_key = api_key

    openkb_results = []
    for doc_cfg in DOCUMENTS:
        result = await eval_document(doc_cfg)
        out_path = RESULTS_DIR / f"results_openkb_{doc_cfg['name']}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"  Written: {out_path}")
        openkb_results.append(result)

    _print_table(openkb_results)


if __name__ == "__main__":
    asyncio.run(main())
