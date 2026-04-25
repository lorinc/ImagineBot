"""multi.py — Multi-document index build and query pipeline.

Architecture:
  Build:  read per-doc index JSONs → extract L1 nodes → write multi_index.json  (no LLM calls)
  Query:  routing (structural model, L1 outline) → per-doc node selection (quality model,
          concurrent) → synthesis (quality model, cross-doc sections)

Usage:
  python3 -m indexer.multi build <index1.json> [<index2.json> ...] <multi_index.json>
  python3 -m indexer.multi query <multi_index.json> "<question>"
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from vertexai.generative_models import GenerativeModel

from .config import MODEL_QUALITY, MODEL_STRUCTURAL
from .llm import DOC_ROUTING_SCHEMA, NODE_SELECTION_SCHEMA, get_model, llm_call
from .node import Node
from .observability import cost_usd, emit_span, render_outline
from .prompts import make_route_prompt, make_overview_synthesize_prompt, make_select_prompt, make_synthesize_prompt

_MAX_ROUTING_TOPICS = 6  # phrases per L1 node shown to the routing LLM


# ── Multi-index build ─────────────────────────────────────────────────────────

def build_multi_index(index_paths: list[Path], output_path: Path) -> dict:
    """Build a multi-document index from a list of per-doc index JSON files. No LLM calls."""
    documents = []
    for p in index_paths:
        idx = json.loads(p.read_text(encoding="utf-8"))
        doc_id = Path(idx["source"]).stem
        root = Node.from_dict(idx["tree"])
        l1_nodes = [
            {
                "id": n.id,
                "title": n.title,
                "topics": n.topics,
                "children_count": len(n.children),
            }
            for n in root.children  # direct children of root are L1 nodes
        ]
        documents.append({
            "doc_id": doc_id,
            "source": idx["source"],
            "index_path": str(p.resolve()),
            "node_count": idx["node_count"],
            "l1_nodes": l1_nodes,
        })
        print(f"[multi build] {doc_id}: {idx['node_count']} nodes, {len(l1_nodes)} L1 sections")

    multi_index = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "doc_count": len(documents),
        "documents": documents,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(multi_index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[multi build] Multi-index saved → {output_path}  ({len(documents)} docs)")
    return multi_index


# ── Routing outline ───────────────────────────────────────────────────────────

def render_routing_outline(multi_index: dict, max_topics: int = _MAX_ROUTING_TOPICS) -> str:
    """Compact L1-only outline for the routing LLM, with truncated topics per node."""
    blocks = []
    for doc in multi_index["documents"]:
        lines = [f"=== {doc['doc_id']} ({doc['node_count']} nodes) ==="]
        for n in doc["l1_nodes"]:
            phrases = [p.strip() for p in n["topics"].split(";") if p.strip()]
            truncated = "; ".join(phrases[:max_topics])
            if len(phrases) > max_topics:
                truncated += f"; ... ({len(phrases) - max_topics} more)"
            lines.append(f"[{n['id']}] {n['title']}: {truncated}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ── Query ─────────────────────────────────────────────────────────────────────

async def query_multi_index(
    question: str,
    multi_index: dict,
    structural_model: GenerativeModel,
    quality_model: GenerativeModel,
    *,
    topics_only: bool = False,
    overview: bool = False,
) -> dict:
    """
    Three-stage multi-document query.

    Stage 1 — Routing (structural model):
      Compact routing outline (L1 nodes only, truncated topics) → 1–2 doc IDs.

    Stage 2 — Per-doc node selection (quality model, concurrent):
      Full outline of each selected doc → leaf node IDs (same as single-doc step 1).

    Stage 3 — Synthesis (quality model):
      Full text of all selected nodes, prefixed with doc-scoped IDs → answer.
    """
    docs_by_id = {d["doc_id"]: d for d in multi_index["documents"]}

    # ── Stage 1: Routing ──────────────────────────────────────────────────────

    routing_outline = render_routing_outline(multi_index)
    route_prompt = make_route_prompt(routing_outline, question)
    route_raw, route_ms, route_usage = await llm_call(
        structural_model, route_prompt, response_schema=DOC_ROUTING_SCHEMA
    )
    try:
        route_parsed = json.loads(route_raw)
        selected_doc_ids: list[str] = route_parsed.get("selected_doc_ids", [])
        route_reasoning: str = route_parsed.get("reasoning", "")
    except json.JSONDecodeError as e:
        selected_doc_ids = []
        route_reasoning = f"[JSON parse error: {e}] raw: {route_raw[:300]}"

    resolved_docs = [d for d in selected_doc_ids if d in docs_by_id]
    unresolved_docs = [d for d in selected_doc_ids if d not in docs_by_id]

    emit_span("knowledge.routing", {
        "selected_doc_ids": resolved_docs,
        "doc_titles": ", ".join(d.replace("_", " ").replace("-", " ").title() for d in resolved_docs),
        "unresolved": unresolved_docs,
        "reasoning_preview": route_reasoning[:120],
    }, duration_ms=route_ms)

    print(f"[multi query] Routing → {resolved_docs}")
    print(f"[multi query]   Reasoning: {route_reasoning[:120]}")
    if unresolved_docs:
        print(f"[multi query] ⚠  Unresolved doc IDs: {unresolved_docs}")

    # ── Stage 2: Per-doc node selection (concurrent) ──────────────────────────

    async def _select_from_doc(doc_id: str) -> tuple[str, dict]:
        doc = docs_by_id[doc_id]
        idx = json.loads(Path(doc["index_path"]).read_text(encoding="utf-8"))
        root = Node.from_dict(idx["tree"])
        outline = render_outline(root)
        select_prompt = make_select_prompt(outline, question)
        raw, ms, usage = await llm_call(
            quality_model, select_prompt, response_schema=NODE_SELECTION_SCHEMA
        )
        try:
            parsed = json.loads(raw)
            ids: list[str] = parsed.get("selected_ids", [])
            reasoning: str = parsed.get("reasoning", "")
        except json.JSONDecodeError as e:
            ids = []
            reasoning = f"[JSON parse error: {e}]"

        all_nodes = root.all_nodes()
        nodes_by_id = {n.id: n for n in all_nodes}

        selected_nodes: list[Node] = []
        unresolved: list[str] = []
        for sid in ids:
            if sid in nodes_by_id:
                selected_nodes.append(nodes_by_id[sid])
            else:
                unresolved.append(sid)

        # Lever 2: expand parent selections to direct children
        parent_selections = [n.id for n in selected_nodes if not n.is_leaf()]
        expanded_ids: list[str] = []
        if parent_selections:
            expanded: list[Node] = []
            seen: set[str] = set()
            for n in selected_nodes:
                if n.is_leaf():
                    if n.id not in seen:
                        expanded.append(n)
                        seen.add(n.id)
                else:
                    for child in n.children:
                        if child.id not in seen:
                            expanded.append(child)
                            seen.add(child.id)
                            expanded_ids.append(child.id)
            selected_nodes = expanded

        print(f"[multi query]   {doc_id}: {[n.id for n in selected_nodes]}  ({ms}ms)")

        # Compute L1 ancestors for topics_only mode
        l1_ancestors: list[dict] = []
        if topics_only:
            node_to_l1: dict[str, Node] = {}
            for l1 in root.children:
                for n in l1.all_nodes():
                    node_to_l1[n.id] = l1
            seen_l1: set[str] = set()
            for n in selected_nodes:
                l1 = node_to_l1.get(n.id)
                if l1 and l1.id not in seen_l1:
                    seen_l1.add(l1.id)
                    l1_ancestors.append({"doc_id": doc_id, "id": l1.id, "title": l1.title})

        return doc_id, {
            "selected_ids": ids,
            "reasoning": reasoning,
            "unresolved_ids": unresolved,
            "parent_selections": parent_selections,
            "expanded_ids": expanded_ids,
            "outline_char_count": len(outline),
            "selected_node_ids": [n.id for n in selected_nodes],
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "latency_ms": ms,
            "_nodes": selected_nodes,  # Node objects; stripped before serialisation
            "_l1_ancestors": l1_ancestors,
        }

    select_results = await asyncio.gather(*[_select_from_doc(d) for d in resolved_docs])
    per_doc_raw: dict[str, dict] = dict(select_results)

    sel_chunks = [{"title": n.title, "chars": n.full_text_char_count}
                  for sel in per_doc_raw.values() for n in sel["_nodes"]]
    sel_summary = ", ".join(f"{c['title']} ({c['chars']}c)" for c in sel_chunks[:6])
    if len(sel_chunks) > 6:
        sel_summary += f" +{len(sel_chunks) - 6} more"
    emit_span("knowledge.selection", {
        "chunk_count": len(sel_chunks),
        "chunk_summary": sel_summary,
        "chunks": sel_chunks,
        "total_chars": sum(c["chars"] for c in sel_chunks),
    }, duration_ms=max((v["latency_ms"] for v in per_doc_raw.values()), default=0))

    # ── topics_only: return L1 ancestors without synthesis ────────────────────
    if topics_only:
        l1_topics: list[dict] = []
        for sel in per_doc_raw.values():
            l1_topics.extend(sel.get("_l1_ancestors", []))
        return {"l1_topics": l1_topics}

    # ── Stage 3: Synthesis ────────────────────────────────────────────────────

    section_parts: list[str] = []
    all_selected_node_info: list[dict] = []
    for doc_id, sel in per_doc_raw.items():
        for n in sel["_nodes"]:
            scoped_id = f"{doc_id}:{n.id}"
            section_parts.append(
                f"[Section {scoped_id}: {n.title}]\n{n.full_text(include_heading=False)}"
            )
            all_selected_node_info.append({
                "doc_id": doc_id,
                "id": n.id,
                "scoped_id": scoped_id,
                "level": n.level,
                "title": n.title,
                "direct_content_chars": n.char_count,
                "full_text_chars": n.full_text_char_count,
                "content_preview": n.content[:400] + ("…" if n.char_count > 400 else ""),
            })

    sections_text = (
        "\n\n---\n\n".join(section_parts)
        if section_parts
        else f"(no sections selected)\n\n{routing_outline}"
    )

    synth_prompt = (
        make_overview_synthesize_prompt(question, sections_text)
        if overview
        else make_synthesize_prompt(question, sections_text)
    )
    emit_span("knowledge.synthesis_started", {
        "chunk_count": len(all_selected_node_info),
        "total_chars": len(sections_text),
    }, duration_ms=None)
    synth_raw, synth_ms, synth_usage = await llm_call(quality_model, synth_prompt)
    answer = synth_raw.strip()
    emit_span("knowledge.synthesis_done", {
        "answer_chars": len(answer),
    }, duration_ms=synth_ms)

    print(f"[multi query] Synthesis done ({synth_ms}ms)")

    # ── Totals ────────────────────────────────────────────────────────────────

    sel_input  = sum(s["input_tokens"]  for s in per_doc_raw.values())
    sel_output = sum(s["output_tokens"] for s in per_doc_raw.values())
    sel_ms_max = max((s["latency_ms"] for s in per_doc_raw.values()), default=0)

    struct_name = getattr(structural_model, "_name", MODEL_STRUCTURAL)
    qual_name   = getattr(quality_model,    "_name", MODEL_QUALITY)
    route_cost  = cost_usd(struct_name,
                           route_usage.get("input_tokens", 0),
                           route_usage.get("output_tokens", 0))
    sel_cost    = cost_usd(qual_name, sel_input, sel_output)
    synth_cost  = cost_usd(qual_name,
                           synth_usage.get("input_tokens", 0),
                           synth_usage.get("output_tokens", 0))

    total_input  = (route_usage.get("input_tokens", 0) + sel_input
                    + synth_usage.get("input_tokens", 0))
    total_output = (route_usage.get("output_tokens", 0) + sel_output
                    + synth_usage.get("output_tokens", 0))

    # Strip non-serialisable Node objects from per_doc results
    per_doc_selection = {
        doc_id: {k: v for k, v in sel.items() if k != "_nodes"}
        for doc_id, sel in per_doc_raw.items()
    }

    return {
        "question": question,
        "routing": {
            "routing_outline_char_count": len(routing_outline),
            "routing_outline": routing_outline,
            "selected_doc_ids": resolved_docs,
            "unresolved_doc_ids": unresolved_docs,
            "reasoning": route_reasoning,
            "input_tokens": route_usage.get("input_tokens", 0),
            "output_tokens": route_usage.get("output_tokens", 0),
            "latency_ms": route_ms,
            "cost_usd": route_cost,
        },
        "per_doc_selection": per_doc_selection,
        "synthesis": {
            "selected_nodes": all_selected_node_info,
            "sections_text_char_count": len(sections_text),
            "sections_text": sections_text,
            "prompt_char_count": len(synth_prompt),
            "raw_response": synth_raw,
            "answer": answer,
            "input_tokens": synth_usage.get("input_tokens", 0),
            "output_tokens": synth_usage.get("output_tokens", 0),
            "latency_ms": synth_ms,
            "cost_usd": synth_cost,
        },
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "cost_usd": route_cost + sel_cost + synth_cost,
        "chars_to_synthesis": len(sections_text),
        "total_latency_ms": route_ms + sel_ms_max + synth_ms,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_query_result(result: dict) -> None:
    """Human-readable drill-down for a single multi-doc query result."""
    bar = "━" * 72
    r = result["routing"]
    s = result["synthesis"]

    print(f"\n{bar}")
    print(f"Question: {result['question']}")

    print(f"\n── Stage 1: Routing ({r['latency_ms']}ms) ───────────────────────────────────")
    print(f"Routing outline: {r['routing_outline_char_count']} chars")
    print()
    print(r["routing_outline"])
    print()
    print(f"Selected docs : {r['selected_doc_ids']}")
    if r["unresolved_doc_ids"]:
        print(f"⚠  Unresolved : {r['unresolved_doc_ids']}")
    print(f"Reasoning     : {r['reasoning']}")

    print(f"\n── Stage 2: Per-doc node selection ──────────────────────────────────────────")
    for doc_id, sel in result["per_doc_selection"].items():
        print(f"  {doc_id}  ({sel['latency_ms']}ms)")
        print(f"    Outline: {sel['outline_char_count']} chars")
        print(f"    Selected: {sel['selected_node_ids']}")
        if sel.get("parent_selections"):
            print(f"    ⚠ Parents expanded: {sel['parent_selections']} → {sel['expanded_ids']}")
        if sel.get("unresolved_ids"):
            print(f"    ⚠ Unresolved IDs: {sel['unresolved_ids']}")
        print(f"    Reasoning: {sel['reasoning'][:120]}")

    print(f"\n── Stage 3: Synthesis ({s['latency_ms']}ms) ──────────────────────────────────")
    if s["selected_nodes"]:
        print("Nodes sent to synthesis:")
        for n in s["selected_nodes"]:
            print(f"  [{n['scoped_id']}] {n['title']}")
            print(f"      direct={n['direct_content_chars']}c  full={n['full_text_chars']}c")
        print(f"Total text: {s['sections_text_char_count']} chars")
        if s["sections_text_char_count"] > 40_000:
            print("  ⚠ SYNTHESIS EXPLOSION (>40K chars)")
    else:
        print("  ⚠  No nodes selected — used routing outline as fallback.")

    print(f"\nAnswer:")
    print(f"  {s['answer']}")
    print(f"\nTotal: {result['total_latency_ms']}ms  ≈${result['cost_usd']:.5f}")
    print(bar)


async def _cmd_build(index_paths: list[str], output: str) -> None:
    build_multi_index([Path(p) for p in index_paths], Path(output))


async def _cmd_query(multi_index_path: str, question: str) -> None:
    multi_index = json.loads(Path(multi_index_path).read_text(encoding="utf-8"))
    structural = get_model(MODEL_STRUCTURAL)
    quality = get_model(MODEL_QUALITY)
    result = await query_multi_index(question, multi_index, structural, quality)
    _print_query_result(result)


def main() -> None:
    """
    Usage:
      python3 -m indexer.multi build <index1.json> [<index2.json> ...] <multi_index.json>
      python3 -m indexer.multi query <multi_index.json> "<question>"
    """
    if len(sys.argv) < 2:
        print(main.__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "build":
        if len(sys.argv) < 4:
            print("Usage: indexer.multi build <index1.json> [<index2.json> ...] <output.json>")
            sys.exit(1)
        # All args after "build" except the last are input indexes; last is output
        asyncio.run(_cmd_build(sys.argv[2:-1], sys.argv[-1]))

    elif cmd == "query":
        if len(sys.argv) != 4:
            print('Usage: indexer.multi query <multi_index.json> "<question>"')
            sys.exit(1)
        asyncio.run(_cmd_query(sys.argv[2], sys.argv[3]))

    else:
        print(f"Unknown command: {cmd}")
        print(main.__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
