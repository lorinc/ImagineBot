#!/usr/bin/env python3
"""
run_eval.py — run the PageIndex eval battery against an existing index.

Each query is executed, all intermediate steps printed to stdout, and the
full result (including outline, prompts, raw LLM responses, selected nodes,
full text sent to synthesis) is written to the output JSON.

Usage:
  python run/run_eval.py <index.json> <results.json>

Example:
  cd poc/poc1_single_doc
  python run/run_eval.py eval/index.json eval/results.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Allow importing pageindex from the sibling build/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "indexer"))
from pageindex import get_model, query_index  # noqa: E402

# ── Test battery ──────────────────────────────────────────────────────────────
# Queries designed to exercise different sections of the Code of Conduct
# and to probe the open questions from docs/design/RAG -- System Design.md:
#   - Node density signal (how many nodes selected per query?)
#   - Vocabulary mismatch (does step 1 select the right section even when vocab differs?)
#   - Multi-section answers (does step 2 synthesise correctly across sections?)

QUERIES = [
    # Numeric fact — single section (§3.4 Definitions)
    "What attendance percentage is required for secondary students?",

    # Multi-step process — single section but long (§6 Anti-Bullying)
    "What happens step-by-step when a bullying incident is reported to the school?",

    # Policy nuance with conditions — §4 Behaviour Policy (physical restraint sub-section)
    "Can teachers physically restrain students, and under what conditions is this allowed?",

    # Enumeration — §8 Weapons
    "What items are classified as weapons under school policy?",

    # Specific sub-rule — §2.4 General Guidance (PE day dress code)
    "What are the specific dress code rules for PE days?",

    # Complex process — §7 Drug and Alcohol
    "How does the school handle a situation where a student is found with drugs on school premises?",

    # Cross-section inference — §4 Behaviour + §5 Anti-Racism
    # Vocabulary mismatch probe: 'racist language' doesn't appear verbatim in §4
    "Is racist language treated differently from other forms of misconduct?",
]

# ── Printing ──────────────────────────────────────────────────────────────────

BAR = "━" * 72
SEC = "─" * 72


def _print_result(idx: int, total: int, result: dict) -> None:
    """Print every intermediate step for human inspection."""
    s1 = result["step1"]
    s2 = result["step2"]

    print(f"\n{BAR}")
    print(f"Query {idx}/{total}")
    print(f"Q: {result['question']}")

    # ── Step 1 ───────────────────────────────────────────────────────────────
    print(f"\n{SEC}")
    print(f"Step 1 — Node Selection  ({s1['latency_ms']}ms)")
    print(f"Outline shown to LLM: {s1['outline_line_count']} nodes · "
          f"{s1['outline_char_count']} chars")
    print()
    print(s1["outline"])
    print()
    print(f"Raw LLM response:")
    print(f"  {s1['raw_response']}")
    print()
    print(f"Selected IDs : {s1['selected_ids']}")
    print(f"Reasoning    : {s1['selection_reasoning']}")
    if s1["unresolved_ids"]:
        print(f"⚠ Unresolved : {s1['unresolved_ids']}")

    # ── Step 2 ───────────────────────────────────────────────────────────────
    print(f"\n{SEC}")
    print(f"Step 2 — Synthesis  ({s2['latency_ms']}ms)")
    if s2["selected_nodes"]:
        print("Nodes fetched:")
        for n in s2["selected_nodes"]:
            print(f"  [{n['id']}] {n['title']}")
            print(f"      direct={n['direct_content_chars']}c · "
                  f"with-children={n['full_text_chars']}c")
            print(f"      content preview: {n['content_preview'][:200]}")
        print()
        print(f"Total text sent to synthesis LLM: "
              f"{s2['sections_text_char_count']} chars")
        print()
        print("Full text sent to synthesis LLM:")
        print(s2["sections_text"])
    else:
        print("  ⚠  No nodes resolved — fell back to outline.")

    print()
    print(f"Answer:")
    print(s2["answer"])
    print()
    print(f"Total latency: {result['total_latency_ms']}ms")


# ── Summary table ─────────────────────────────────────────────────────────────

def _print_summary(results: list[dict]) -> None:
    print(f"\n{BAR}")
    print("SUMMARY TABLE")
    print(f"{BAR}")
    header = f"{'#':>2}  {'Q (first 55 chars)':<56}  {'IDs selected':<28}  {'ms':>6}"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, 1):
        q = r["question"][:55]
        ids = ", ".join(r["step1"]["selected_ids"]) or "(none)"
        if len(ids) > 28:
            ids = ids[:25] + "..."
        ms = r["total_latency_ms"]
        unres = f"  ⚠{len(r['step1']['unresolved_ids'])}" if r["step1"]["unresolved_ids"] else ""
        print(f"{i:>2}  {q:<56}  {ids:<28}  {ms:>6}{unres}")
    print()
    avg = sum(r["total_latency_ms"] for r in results) // len(results)
    print(f"Avg latency: {avg}ms   |   Queries: {len(results)}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(index_path: str, output_path: str) -> None:
    index = json.loads(Path(index_path).read_text())
    model = get_model()

    print(f"{BAR}")
    print(f"PageIndex Eval — POC 1 (single document)")
    print(f"{BAR}")
    print(f"Source : {index['source']}")
    print(f"Nodes  : {index['node_count']} "
          f"(#={index['level_counts'].get('1', 0)}  "
          f"##={index['level_counts'].get('2', 0)}  "
          f"###={index['level_counts'].get('3', 0)})")
    print(f"Built  : {index['built_at']}  ({index['build_time_s']}s)")
    print(f"Queries: {len(QUERIES)}")
    print()

    all_results: list[dict] = []
    t_eval_start = time.monotonic()

    for i, question in enumerate(QUERIES, 1):
        result = await query_index(question, index, model)
        all_results.append(result)
        _print_result(i, len(QUERIES), result)

    total_eval_s = round(time.monotonic() - t_eval_start, 1)
    _print_summary(all_results)

    output = {
        "eval_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_eval_time_s": total_eval_s,
        "index_source": index["source"],
        "index_built_at": index["built_at"],
        "index_build_time_s": index["build_time_s"],
        "node_count": index["node_count"],
        "level_counts": index["level_counts"],
        "query_count": len(QUERIES),
        "avg_latency_ms": sum(r["total_latency_ms"] for r in all_results) // len(all_results),
        # Full node details (content + summaries) for drill-down in results.json
        "nodes_flat": index["nodes_flat"],
        # Each query: question + full step1 + full step2 (including text sent to LLM)
        "queries": all_results,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nResults written to: {output_path}")
    print(f"Total eval time: {total_eval_s}s")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <index.json> <results.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
