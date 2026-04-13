#!/usr/bin/env python3
"""
run_eval.py — run a PageIndex eval battery against an existing index.

Queries are loaded from a JSON file so each document can have its own set.
Every intermediate step is printed to stdout and written to the output JSON.

Usage:
  python run/run_eval.py <index.json> <queries.json> <results.json>

Example:
  cd poc/poc1_single_doc
  python run/run_eval.py eval/index_policy5.json eval/queries_policy5.json eval/results_policy5.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).parent.parent / "indexer"))
from pageindex import MODEL_QUALITY, PRICING_PER_1M_USD, get_model, query_index  # noqa: E402

# ── Printing ──────────────────────────────────────────────────────────────────

BAR = "━" * 72
SEC = "─" * 72


# ── Log file writing ──────────────────────────────────────────────────────────

def _write_build_log_section(f: TextIO, index: dict) -> None:
    build_log_path = index.get("build_log")
    if not build_log_path or not Path(build_log_path).exists():
        f.write("(no build log found)\n")
        return
    f.write(Path(build_log_path).read_text(encoding="utf-8"))
    f.write("\n")


def _write_query_log(f: TextIO, idx: int, total: int, result: dict) -> None:
    s1 = result["step1"]
    s2 = result["step2"]
    q_type = result.get("query_type", "")
    q_note = result.get("query_note", "")

    f.write(f"\n{'━' * 72}\n")
    f.write(f"Query {idx}/{total}")
    if q_type:
        f.write(f"  [{q_type}]")
    f.write(f"\n{result['question']}\n")
    if q_note:
        f.write(f"Note: {q_note}\n")

    f.write(f"\n── Step 1: Node Selection ({s1['latency_ms']}ms) {'─' * 30}\n")
    f.write(f"Tokens: in={s1.get('input_tokens', 0):,}  out={s1.get('output_tokens', 0):,}\n")
    f.write(f"Outline: {s1['outline_line_count']} nodes, {s1['outline_char_count']} chars\n\n")
    f.write(s1["outline"])
    f.write(f"\n\nSelected IDs: {s1['selected_ids']}\n")
    f.write(f"Reasoning   : {s1['selection_reasoning']}\n")
    if s1.get("parent_selections"):
        f.write(f"⚠ Parent selections (over-fetch risk): {s1['parent_selections']}\n")
    if s1["unresolved_ids"]:
        f.write(f"⚠ Unresolved IDs: {s1['unresolved_ids']}\n")

    f.write(f"\n── Step 2: Synthesis ({s2['latency_ms']}ms) {'─' * 33}\n")
    f.write(f"Tokens: in={s2.get('input_tokens', 0):,}  out={s2.get('output_tokens', 0):,}\n")
    if s2["selected_nodes"]:
        for n in s2["selected_nodes"]:
            depth = s1["selected_depth"].get(n["id"], "?")
            f.write(f"  [{n['id']}] {n['title']}  ({depth}, "
                    f"direct={n['direct_content_chars']}c, "
                    f"with-children={n['full_text_chars']}c)\n")
        f.write(f"\nTotal chars sent to synthesis LLM: {s2['sections_text_char_count']}\n")
        if s2["sections_text_char_count"] > 40_000:
            f.write("⚠ SYNTHESIS EXPLOSION (>40K chars)\n")
        f.write(f"\nFull text sent:\n{'·' * 40}\n")
        f.write(s2["sections_text"])
        f.write(f"\n{'·' * 40}\n")
    else:
        f.write("⚠ No nodes resolved — fell back to outline.\n")

    f.write(f"\nAnswer:\n{s2['answer']}\n")
    q_cost = result.get("cost_usd", 0.0)
    q_in   = result.get("total_input_tokens", 0)
    q_out  = result.get("total_output_tokens", 0)
    f.write(f"\nTotal latency: {result['total_latency_ms']}ms  |  "
            f"chars→synthesis: {result['chars_to_synthesis']}  |  "
            f"tokens: {q_in:,} in + {q_out:,} out  |  ≈${q_cost:.5f}\n")


def _print_result(idx: int, total: int, result: dict) -> None:
    s1 = result["step1"]
    s2 = result["step2"]

    print(f"\n{BAR}")
    print(f"Query {idx}/{total}")
    print(f"Q: {result['question']}")

    print(f"\n{SEC}")
    print(f"Step 1 — Node Selection  ({s1['latency_ms']}ms)")
    print(f"Outline shown to LLM: {s1['outline_line_count']} nodes · "
          f"{s1['outline_char_count']} chars")
    print()
    print(s1["outline"])
    print()
    print(f"Selected IDs : {s1['selected_ids']}")
    print(f"Reasoning    : {s1['selection_reasoning']}")
    if s1.get("parent_selections"):
        print(f"⚠ Parents    : {s1['parent_selections']}  (over-fetch risk)")
    if s1["unresolved_ids"]:
        print(f"⚠ Unresolved : {s1['unresolved_ids']}")

    print(f"\n{SEC}")
    print(f"Step 2 — Synthesis  ({s2['latency_ms']}ms)")
    if s2["selected_nodes"]:
        print("Nodes fetched:")
        for n in s2["selected_nodes"]:
            depth = s1["selected_depth"].get(n["id"], "?")
            print(f"  [{n['id']}] {n['title']}  ({depth})")
            print(f"      direct={n['direct_content_chars']}c · "
                  f"with-children={n['full_text_chars']}c")
        print()
        print(f"Total text sent to synthesis LLM: {s2['sections_text_char_count']} chars")
        if s2["sections_text_char_count"] > 40_000:
            print("  ⚠ SYNTHESIS EXPLOSION (>40K chars)")
    else:
        print("  ⚠  No nodes resolved — fell back to outline.")

    print()
    print(f"Answer:")
    print(s2["answer"])
    print()
    print(f"Total latency: {result['total_latency_ms']}ms")


def _print_summary(results: list[dict]) -> None:
    print(f"\n{BAR}")
    print("SUMMARY TABLE")
    print(f"{BAR}")
    header = (f"{'#':>2}  {'Q (first 45 chars)':<46}  "
              f"{'#IDs':>4}  {'chars→synth':>11}  {'cost':>8}  {'ms':>7}  {'flags'}")
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, 1):
        q = r["question"][:45]
        n_ids = len(r["step1"]["selected_ids"])
        chars = r["chars_to_synthesis"]
        cost = r.get("cost_usd", 0.0)
        ms = r["total_latency_ms"]
        flags = []
        if r["step1"]["unresolved_ids"]:
            flags.append(f"unres:{len(r['step1']['unresolved_ids'])}")
        if r["step1"].get("parent_selections"):
            flags.append(f"parent:{len(r['step1']['parent_selections'])}")
        if chars > 40_000:
            flags.append("EXPLOSION")
        flag_str = "  " + " ".join(flags) if flags else ""
        print(f"{i:>2}  {q:<46}  {n_ids:>4}  {chars:>11}  ${cost:>7.5f}  {ms:>7}{flag_str}")
    print()
    avg_ms = sum(r["total_latency_ms"] for r in results) // len(results)
    avg_chars = sum(r["chars_to_synthesis"] for r in results) // len(results)
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    parent_count = sum(1 for r in results if r["step1"].get("parent_selections"))
    print(f"Avg latency: {avg_ms}ms  |  Avg chars→synth: {avg_chars}  "
          f"|  Total query cost: ≈${total_cost:.4f}  "
          f"|  Parent selections: {parent_count}/{len(results)}  "
          f"|  Queries: {len(results)}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(index_path: str, queries_path: str, output_path: str) -> None:
    index = json.loads(Path(index_path).read_text())
    queries_doc = json.loads(Path(queries_path).read_text())
    queries: list[dict] = queries_doc["queries"]
    model = get_model(MODEL_QUALITY)
    log_path = Path(output_path).with_suffix(".log")

    print(f"{BAR}")
    print(f"PageIndex Eval")
    print(f"{BAR}")
    print(f"Source  : {index['source']}")
    print(f"Nodes   : {index['node_count']} "
          f"(#={index['level_counts'].get('1', 0)}  "
          f"##={index['level_counts'].get('2', 0)}  "
          f"###={index['level_counts'].get('3', 0)})")
    print(f"Built   : {index['built_at']}  ({index['build_time_s']}s)")
    print(f"Queries : {len(queries)}  [{queries_doc.get('document', '?')}]")
    print()

    # Per-node phrase_count distribution from index
    if index.get("nodes_flat"):
        pcs = [n.get("phrase_count", 0) for n in index["nodes_flat"]]
        if pcs:
            print(f"Index phrase_count: min={min(pcs)} max={max(pcs)} "
                  f"avg={sum(pcs)//len(pcs)}  (nodes={len(pcs)})")
    print()

    all_results: list[dict] = []
    t_eval_start = time.monotonic()

    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(f"PageIndex Eval Log\n")
        log_f.write(f"{'━' * 72}\n")
        log_f.write(f"Document : {queries_doc.get('document', '?')}\n")
        log_f.write(f"Source   : {index['source']}\n")
        log_f.write(f"Nodes    : {index['node_count']}\n")
        log_f.write(f"Built    : {index['built_at']}  ({index['build_time_s']}s)\n")
        log_f.write(f"Queries  : {len(queries)}\n")
        log_f.write(f"Eval run : {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")

        log_f.write(f"\n{'━' * 72}\n")
        log_f.write("BUILD PIPELINE LOG\n")
        log_f.write(f"{'━' * 72}\n")
        _write_build_log_section(log_f, index)

        log_f.write(f"\n{'━' * 72}\n")
        log_f.write("QUERY PIPELINE LOG\n")
        log_f.write(f"{'━' * 72}\n")

        for i, q in enumerate(queries, 1):
            result = await query_index(q["question"], index, model)
            result["query_id"] = q["id"]
            result["query_type"] = q.get("type", "")
            result["query_note"] = q.get("note", "")
            all_results.append(result)
            _print_result(i, len(queries), result)
            _write_query_log(log_f, i, len(queries), result)
            log_f.flush()

    total_eval_s = round(time.monotonic() - t_eval_start, 1)

    # Cost summary section in log
    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"\n{'━' * 72}\n")
        log_f.write("COST SUMMARY\n")
        log_f.write(f"{'━' * 72}\n")

        build_cost = index.get("build_cost_usd", 0.0)
        log_f.write(f"Build pipeline:  ≈${build_cost:.4f}\n")
        for mn, u in sorted(index.get("build_token_usage", {}).items()):
            log_f.write(f"  {mn}: {u['calls']} calls, "
                        f"{u['input_tokens']:,} in + {u['output_tokens']:,} out tokens\n")

        total_q_cost = sum(r.get("cost_usd", 0.0) for r in all_results)
        total_q_in   = sum(r.get("total_input_tokens", 0) for r in all_results)
        total_q_out  = sum(r.get("total_output_tokens", 0) for r in all_results)
        log_f.write(f"\nQuery pipeline ({len(all_results)} queries):  ≈${total_q_cost:.4f}\n")
        log_f.write(f"  {MODEL_QUALITY}: {total_q_in:,} in + {total_q_out:,} out tokens\n")
        for i, r in enumerate(all_results, 1):
            log_f.write(f"  Q{i}: {r.get('total_input_tokens',0):,} in + "
                        f"{r.get('total_output_tokens',0):,} out  ≈${r.get('cost_usd',0):.5f}\n")

        total_cost = build_cost + total_q_cost
        log_f.write(f"\nTotal estimated cost:  ≈${total_cost:.4f}\n")
        p = PRICING_PER_1M_USD
        log_f.write(f"Pricing used: flash-lite in=${p.get('gemini-2.5-flash-lite',{}).get('input','?')}"
                    f"/out=${p.get('gemini-2.5-flash-lite',{}).get('output','?')}  "
                    f"flash in=${p.get('gemini-2.5-flash',{}).get('input','?')}"
                    f"/out=${p.get('gemini-2.5-flash',{}).get('output','?')} per 1M tokens\n")
        log_f.write("Verify against current Vertex AI pricing before using for budgeting.\n")

    _print_summary(all_results)

    output = {
        "eval_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_eval_time_s": total_eval_s,
        "document": queries_doc.get("document", ""),
        "index_source": index["source"],
        "index_built_at": index["built_at"],
        "index_build_time_s": index["build_time_s"],
        "node_count": index["node_count"],
        "level_counts": index["level_counts"],
        "query_count": len(queries),
        "avg_latency_ms": sum(r["total_latency_ms"] for r in all_results) // len(all_results),
        "avg_chars_to_synthesis": sum(r["chars_to_synthesis"] for r in all_results) // len(all_results),
        "total_query_cost_usd": sum(r.get("cost_usd", 0.0) for r in all_results),
        "total_query_input_tokens": sum(r.get("total_input_tokens", 0) for r in all_results),
        "total_query_output_tokens": sum(r.get("total_output_tokens", 0) for r in all_results),
        "build_cost_usd": index.get("build_cost_usd", 0.0),
        "total_cost_usd": index.get("build_cost_usd", 0.0) + sum(r.get("cost_usd", 0.0) for r in all_results),
        "parent_selection_count": sum(1 for r in all_results if r["step1"].get("parent_selections")),
        "nodes_flat": index["nodes_flat"],
        "queries": all_results,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nResults written to: {output_path}")
    print(f"Log written to    : {log_path}")
    print(f"Total eval time: {total_eval_s}s")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <index.json> <queries.json> <results.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
