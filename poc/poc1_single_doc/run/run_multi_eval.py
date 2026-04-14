#!/usr/bin/env python3
"""
run_multi_eval.py — run a multi-document PageIndex eval battery.

Usage:
  python run/run_multi_eval.py <multi_index.json> <queries.json> <results.json>

Example:
  cd poc/poc1_single_doc
  python run/run_multi_eval.py \
    eval/multi_index.json \
    eval/queries_multi.json \
    eval/results_multi_v1.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).parent.parent))
from indexer import MODEL_QUALITY, MODEL_STRUCTURAL, PRICING_PER_1M_USD, get_model  # noqa: E402
from indexer.multi import query_multi_index  # noqa: E402

BAR = "━" * 72
SEC = "─" * 72


# ── Log writing ───────────────────────────────────────────────────────────────

def _write_query_log(f: TextIO, idx: int, total: int, result: dict) -> None:
    r = result["routing"]
    s = result["synthesis"]
    q_type = result.get("query_type", "")
    q_note = result.get("query_note", "")

    f.write(f"\n{'━' * 72}\n")
    f.write(f"Query {idx}/{total}")
    if q_type:
        f.write(f"  [{q_type}]")
    f.write(f"\n{result['question']}\n")
    if q_note:
        f.write(f"Note: {q_note}\n")

    f.write(f"\n── Stage 1: Routing ({r['latency_ms']}ms) {'─' * 30}\n")
    f.write(f"Tokens: in={r.get('input_tokens', 0):,}  out={r.get('output_tokens', 0):,}  "
            f"≈${r.get('cost_usd', 0):.5f}\n")
    f.write(f"Routing outline: {r['routing_outline_char_count']} chars\n\n")
    f.write(r["routing_outline"])
    f.write(f"\n\nSelected docs : {r['selected_doc_ids']}\n")
    if r.get("unresolved_doc_ids"):
        f.write(f"⚠ Unresolved  : {r['unresolved_doc_ids']}\n")
    f.write(f"Reasoning     : {r['reasoning']}\n")

    f.write(f"\n── Stage 2: Per-doc node selection {'─' * 30}\n")
    for doc_id, sel in result["per_doc_selection"].items():
        f.write(f"\n  {doc_id}  ({sel['latency_ms']}ms)\n")
        f.write(f"  Tokens: in={sel.get('input_tokens', 0):,}  out={sel.get('output_tokens', 0):,}\n")
        f.write(f"  Outline: {sel['outline_char_count']} chars\n")
        f.write(f"  Selected IDs: {sel['selected_node_ids']}\n")
        if sel.get("parent_selections"):
            f.write(f"  ⚠ Parents expanded: {sel['parent_selections']} → {sel['expanded_ids']}\n")
        if sel.get("unresolved_ids"):
            f.write(f"  ⚠ Unresolved IDs: {sel['unresolved_ids']}\n")
        f.write(f"  Reasoning: {sel['reasoning']}\n")

    f.write(f"\n── Stage 3: Synthesis ({s['latency_ms']}ms) {'─' * 33}\n")
    f.write(f"Tokens: in={s.get('input_tokens', 0):,}  out={s.get('output_tokens', 0):,}  "
            f"≈${s.get('cost_usd', 0):.5f}\n")
    if s["selected_nodes"]:
        for n in s["selected_nodes"]:
            f.write(f"  [{n['scoped_id']}] {n['title']}  "
                    f"(direct={n['direct_content_chars']}c, full={n['full_text_chars']}c)\n")
        f.write(f"\nTotal chars sent to synthesis: {s['sections_text_char_count']}\n")
        if s["sections_text_char_count"] > 40_000:
            f.write("⚠ SYNTHESIS EXPLOSION (>40K chars)\n")
        f.write(f"\nFull text sent:\n{'·' * 40}\n")
        f.write(s["sections_text"])
        f.write(f"\n{'·' * 40}\n")
    else:
        f.write("⚠ No nodes selected — fell back to routing outline.\n")

    f.write(f"\nAnswer:\n{s['answer']}\n")
    f.write(f"\nTotal: {result['total_latency_ms']}ms  |  "
            f"chars→synthesis: {result['chars_to_synthesis']}  |  "
            f"tokens: {result.get('total_input_tokens', 0):,} in + "
            f"{result.get('total_output_tokens', 0):,} out  |  ≈${result['cost_usd']:.5f}\n")


def _print_result(idx: int, total: int, result: dict) -> None:
    r = result["routing"]
    s = result["synthesis"]

    print(f"\n{BAR}")
    print(f"Query {idx}/{total}  [{result.get('query_type', '')}]")
    print(f"Q: {result['question']}")

    print(f"\n{SEC}")
    print(f"Stage 1 — Routing  ({r['latency_ms']}ms)")
    print(f"Selected docs : {r['selected_doc_ids']}")
    print(f"Reasoning     : {r['reasoning']}")

    print(f"\n{SEC}")
    print(f"Stage 2 — Per-doc selection")
    for doc_id, sel in result["per_doc_selection"].items():
        print(f"  {doc_id}: {sel['selected_node_ids']}  ({sel['latency_ms']}ms)")

    print(f"\n{SEC}")
    print(f"Stage 3 — Synthesis  ({s['latency_ms']}ms)")
    if s["selected_nodes"]:
        for n in s["selected_nodes"]:
            print(f"  [{n['scoped_id']}] {n['title']}  full={n['full_text_chars']}c")
        print(f"Total chars: {s['sections_text_char_count']}")
    else:
        print("  ⚠  No nodes — fallback to routing outline.")
    print()
    print("Answer:")
    print(s["answer"])
    print()
    print(f"Total: {result['total_latency_ms']}ms  ≈${result['cost_usd']:.5f}")


def _print_summary(results: list[dict]) -> None:
    print(f"\n{BAR}")
    print("SUMMARY TABLE")
    print(f"{BAR}")
    header = (f"{'#':>2}  {'Q (first 45 chars)':<46}  "
              f"{'docs':>5}  {'#IDs':>4}  {'chars→synth':>11}  {'cost':>8}  {'ms':>7}  {'flags'}")
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, 1):
        q = r["question"][:45]
        n_docs = len(r["routing"]["selected_doc_ids"])
        n_ids = sum(len(s["selected_node_ids"]) for s in r["per_doc_selection"].values())
        chars = r["chars_to_synthesis"]
        cost = r["cost_usd"]
        ms = r["total_latency_ms"]
        flags = []
        if r["routing"].get("unresolved_doc_ids"):
            flags.append(f"unres_doc:{len(r['routing']['unresolved_doc_ids'])}")
        for doc_id, sel in r["per_doc_selection"].items():
            if sel.get("unresolved_ids"):
                flags.append(f"unres_node:{len(sel['unresolved_ids'])}")
            if sel.get("parent_selections"):
                flags.append(f"parent:{len(sel['parent_selections'])}")
        if chars > 40_000:
            flags.append("EXPLOSION")
        flag_str = "  " + " ".join(flags) if flags else ""
        print(f"{i:>2}  {q:<46}  {n_docs:>5}  {n_ids:>4}  {chars:>11,}  "
              f"${cost:>7.5f}  {ms:>7}{flag_str}")

    print()
    avg_ms = sum(r["total_latency_ms"] for r in results) // len(results)
    avg_chars = sum(r["chars_to_synthesis"] for r in results) // len(results)
    total_cost = sum(r["cost_usd"] for r in results)
    route_cost = sum(r["routing"]["cost_usd"] for r in results)
    synth_cost = sum(r["synthesis"]["cost_usd"] for r in results)
    print(f"Avg latency: {avg_ms}ms  |  Avg chars→synth: {avg_chars:,}  "
          f"|  Total cost: ≈${total_cost:.4f}  "
          f"(routing: ≈${route_cost:.4f}  synthesis: ≈${synth_cost:.4f})")
    print(f"Queries: {len(results)}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(multi_index_path: str, queries_path: str, output_path: str) -> None:
    multi_index = json.loads(Path(multi_index_path).read_text(encoding="utf-8"))
    queries_doc = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    queries: list[dict] = queries_doc["queries"]
    structural = get_model(MODEL_STRUCTURAL)
    quality = get_model(MODEL_QUALITY)
    log_path = Path(output_path).with_suffix(".log")

    print(f"{BAR}")
    print(f"MultiDoc PageIndex Eval")
    print(f"{BAR}")
    print(f"Multi-index built: {multi_index['built_at']}")
    print(f"Documents ({multi_index['doc_count']}):")
    for d in multi_index["documents"]:
        print(f"  {d['doc_id']}: {d['node_count']} nodes, {len(d['l1_nodes'])} L1 sections")
    print(f"Queries : {len(queries)}  [{queries_doc.get('document', '?')}]")
    print()

    all_results: list[dict] = []
    t_eval_start = time.monotonic()

    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write("MultiDoc PageIndex Eval Log\n")
        log_f.write(f"{'━' * 72}\n")
        log_f.write(f"Multi-index: {multi_index_path}\n")
        log_f.write(f"Built      : {multi_index['built_at']}\n")
        log_f.write(f"Docs       : {[d['doc_id'] for d in multi_index['documents']]}\n")
        log_f.write(f"Queries    : {len(queries)}\n")
        log_f.write(f"Eval run   : {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        log_f.write(f"\n{'━' * 72}\n")
        log_f.write("QUERY PIPELINE LOG\n")
        log_f.write(f"{'━' * 72}\n")

        for i, q in enumerate(queries, 1):
            result = await query_multi_index(q["question"], multi_index, structural, quality)
            result["query_id"] = q["id"]
            result["query_type"] = q.get("type", "")
            result["query_note"] = q.get("note", "")
            all_results.append(result)
            _print_result(i, len(queries), result)
            _write_query_log(log_f, i, len(queries), result)
            log_f.flush()

    total_eval_s = round(time.monotonic() - t_eval_start, 1)

    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"\n{'━' * 72}\n")
        log_f.write("COST SUMMARY\n")
        log_f.write(f"{'━' * 72}\n")
        total_q_cost = sum(r["cost_usd"] for r in all_results)
        total_q_in   = sum(r.get("total_input_tokens", 0) for r in all_results)
        total_q_out  = sum(r.get("total_output_tokens", 0) for r in all_results)
        log_f.write(f"Query pipeline ({len(all_results)} queries):  ≈${total_q_cost:.4f}\n")
        log_f.write(f"  Total tokens: {total_q_in:,} in + {total_q_out:,} out\n")
        for i, r in enumerate(all_results, 1):
            log_f.write(f"  Q{i}: {r.get('total_input_tokens',0):,} in + "
                        f"{r.get('total_output_tokens',0):,} out  ≈${r['cost_usd']:.5f}\n")
        p = PRICING_PER_1M_USD
        log_f.write(f"\nPricing used:\n")
        for mn, prices in p.items():
            log_f.write(f"  {mn}: in=${prices['input']}/out=${prices['output']} per 1M tokens\n")
        log_f.write("Verify against current Vertex AI pricing before using for budgeting.\n")

    _print_summary(all_results)

    output = {
        "eval_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_eval_time_s": total_eval_s,
        "document": queries_doc.get("document", ""),
        "multi_index_path": multi_index_path,
        "multi_index_built_at": multi_index["built_at"],
        "doc_count": multi_index["doc_count"],
        "documents": [{"doc_id": d["doc_id"], "node_count": d["node_count"]}
                      for d in multi_index["documents"]],
        "query_count": len(queries),
        "avg_latency_ms": sum(r["total_latency_ms"] for r in all_results) // len(all_results),
        "avg_chars_to_synthesis": sum(r["chars_to_synthesis"] for r in all_results) // len(all_results),
        "total_query_cost_usd": sum(r["cost_usd"] for r in all_results),
        "total_routing_cost_usd": sum(r["routing"]["cost_usd"] for r in all_results),
        "total_synthesis_cost_usd": sum(r["synthesis"]["cost_usd"] for r in all_results),
        "total_query_input_tokens": sum(r.get("total_input_tokens", 0) for r in all_results),
        "total_query_output_tokens": sum(r.get("total_output_tokens", 0) for r in all_results),
        "queries": all_results,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults written to: {output_path}")
    print(f"Log written to    : {log_path}")
    print(f"Total eval time: {total_eval_s}s")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <multi_index.json> <queries.json> <results.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
