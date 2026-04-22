#!/usr/bin/env python3
"""
pageindex.py — PageIndex pipeline orchestrator.

Architecture:
  Build:  parse markdown headings → tree of nodes → LLM generates topics per node → save JSON
  Query:  load index → show LLM outline of topics → LLM selects node IDs →
          retrieve full text of selected nodes → LLM synthesises answer

  Every intermediate step is captured and returned so eval can drill into it.

Usage:
  python pageindex.py build <source.md> <index.json>
  python pageindex.py query <index.json> "<question>"
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from vertexai.generative_models import GenerativeModel

from .config import MAX_NODE_CHARS, MIN_NODE_CHARS, MODEL_QUALITY, MODEL_STRUCTURAL
from .llm import (
    MERGE_CHECK_SCHEMA,
    NODE_SELECTION_SCHEMA,
    SPLIT_SCHEMA,
    TOPICS_SCHEMA,
    get_model,
    get_sem,
    llm_call,
)
from .node import Node
from .observability import (
    blog,
    blog_section,
    cost_usd,
    get_build_usage,
    init_build_context,
    log_cost_summary,
    render_children_outline,
    render_outline,
    reset_build_context,
    track_usage,
    validate,
    write_build_log,
)
from .parser import make_breadcrumb, parse_tree, split_text_by_starts
from .prompts import (
    make_discriminate_prompt,
    make_intermediate_topics_prompt,
    make_merge_prompt,
    make_route_section_prompt,
    make_select_prompt,
    make_split_prompt,
    make_synthesize_prompt,
    make_topics_prompt,
)

# Max total children shown in a single discrimination call before splitting per-parent
_COMBINE_THRESHOLD = 20

# ── Topic generation helpers ──────────────────────────────────────────────────

async def _generate_topics(
    model: GenerativeModel, full_text: str, breadcrumb: str
) -> tuple[str, str]:
    """Generate (title, topics) for a leaf node from its full text."""
    prompt = make_topics_prompt(full_text, breadcrumb)
    async with get_sem():
        raw, _, usage = await llm_call(model, prompt, response_schema=TOPICS_SCHEMA)
    track_usage(getattr(model, "_name", MODEL_QUALITY),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    parsed = json.loads(raw)
    return parsed["title"].strip(), parsed["topics"].strip()


async def _generate_intermediate_topics(
    model: GenerativeModel,
    node_title: str,
    children: list[Node],
    breadcrumb: str,
) -> tuple[str, str]:
    """Generate (title, topics) for a non-leaf from children's titles+topics only."""
    prompt = make_intermediate_topics_prompt(node_title, children, breadcrumb)
    async with get_sem():
        raw, _, usage = await llm_call(model, prompt, response_schema=TOPICS_SCHEMA)
    track_usage(getattr(model, "_name", MODEL_QUALITY),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    parsed = json.loads(raw)
    return parsed["title"].strip(), parsed["topics"].strip()


# ── Step 2: Preamble hoisting ─────────────────────────────────────────────────

def _hoist_preamble(node: Node) -> None:
    """
    Recursively hoist preamble content (text before first child) into a
    synthetic leaf child. After hoisting all content lives in leaf nodes.
    """
    for child in node.children:
        _hoist_preamble(child)

    if node.children and node.content.strip():
        synth = Node(
            id=f"{node.id}.p",
            level=node.level + 1,
            title=node.title,
            content=node.content,
            is_preamble=True,
        )
        node.children.insert(0, synth)
        node.content = ""
        blog(f"  Hoisted preamble [{node.id}] '{node.title}' "
             f"({len(synth.content)}c) → [{synth.id}]")


# ── Steps 3–5: Split oversized leaves ────────────────────────────────────────

async def _split_large_node(
    model: GenerativeModel, node: Node, doc_name: str, ancestors: list[Node]
) -> None:
    """
    If a leaf node's full text exceeds MAX_NODE_CHARS, ask the LLM to identify
    semantic sub-section boundaries. Mutates node in place.
    Children receive title + topics from the split step. Parent topics are
    cleared and will be regenerated in step 8.
    """
    if not node.is_leaf():
        return
    if node.full_text_char_count <= MAX_NODE_CHARS:
        return

    blog(f"  [{node.id}] '{node.title}' "
         f"full_text={node.full_text_char_count}c > MAX={MAX_NODE_CHARS}c → splitting")

    breadcrumb = make_breadcrumb(doc_name, ancestors)
    prompt = make_split_prompt(node.title, node.content, breadcrumb)

    async with get_sem():
        raw, _, usage = await llm_call(model, prompt, response_schema=SPLIT_SCHEMA)
    track_usage(getattr(model, "_name", MODEL_STRUCTURAL),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    try:
        sections = json.loads(raw).get("sections", [])
    except json.JSONDecodeError:
        blog(f"  [{node.id}] split FAILED (JSON decode error)")
        return

    if len(sections) < 2:
        blog(f"  [{node.id}] split FAILED (LLM returned {len(sections)} section(s), need ≥2)")
        return

    slices, slice_positions = split_text_by_starts(node.content, [s["start"] for s in sections])
    if len(slices) != len(sections):
        import re
        for i, s in enumerate(sections[1:], 2):  # section 1 is implicit at pos 0
            start50 = s["start"][:50]
            norm_needle = re.sub(r"\s+", " ", start50).strip()
            in_source = norm_needle[:20] in re.sub(r"\s+", " ", node.content)
            blog(f"    section {i} start={repr(start50[:40])} "
                 f"norm20={'found' if in_source else 'NOT FOUND'}")
        blog(f"  [{node.id}] split FAILED (boundary detection: "
             f"got {len(slices)} slices for {len(sections)} sections)")
        return

    synthetic: list[Node] = []
    for sec, content, pos in zip(sections, slices, slice_positions):
        line_no = node.content[:pos].count("\n")
        child = Node(
            id=f"{node.id}.L{line_no}",
            level=node.level + 1,
            title=sec["title"],
            content=content,
            topics=sec.get("topics", ""),
        )
        synthetic.append(child)

    child_summary = ", ".join(f"'{c.title}' ({len(c.content)}c)" for c in synthetic)
    blog(f"  [{node.id}] → {len(synthetic)} children: {child_summary}")

    node.children = synthetic + node.children
    node.content = ""
    node.topics = ""  # will be regenerated bottom-up in step 8


async def _split_all(
    model: GenerativeModel, node: Node, doc_name: str, ancestors: list[Node]
) -> None:
    """
    Recursively split all oversized leaf nodes.
    New synthetic children are immediately recursed into so that still-oversized
    children are handled in the same pass.
    """
    await _split_large_node(model, node, doc_name, ancestors)
    new_ancestors = ancestors + [node]
    await asyncio.gather(*[_split_all(model, c, doc_name, new_ancestors) for c in node.children])


# ── Step 7: Thin small nodes ──────────────────────────────────────────────────

async def _check_merge(model: GenerativeModel, a: Node, b: Node) -> bool:
    """Ask the structural model whether two adjacent leaf nodes should be merged."""
    a_repr = a.topics if a.topics else a.full_text()[:400]
    b_repr = b.topics if b.topics else b.full_text()[:400]
    prompt = make_merge_prompt(a.title, a_repr, b.title, b_repr)
    async with get_sem():
        raw, _, usage = await llm_call(model, prompt, response_schema=MERGE_CHECK_SCHEMA)
    track_usage(getattr(model, "_name", MODEL_STRUCTURAL),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    return json.loads(raw)["should_merge"]


def _merge_nodes(a: Node, b: Node) -> Node:
    """Create a merged node with combined content. Title/topics set by caller."""
    combined = "\n\n".join(p for p in [a.content, b.content] if p)
    merged = Node(id=a.id, level=a.level, title=a.title, content=combined)
    merged.children = a.children + b.children
    return merged


async def _thin_level(
    structural_model: GenerativeModel,
    quality_model: GenerativeModel,
    children: list[Node],
    doc_name: str,
    ancestors: list[Node],
) -> list[Node]:
    """
    Single left-to-right pass over a sibling list. Merges consecutive leaf pairs
    where at least one is small (or one is a preamble node) and combined ≤ MAX.
    Loops until a full pass produces no merges.
    """
    result = list(children)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            a, b = result[i], result[i + 1]

            if not a.is_leaf() or not b.is_leaf():
                i += 1
                continue

            combined_size = a.full_text_char_count + b.full_text_char_count
            if combined_size > MAX_NODE_CHARS:
                i += 1
                continue

            do_merge = False
            if a.is_preamble or b.is_preamble:
                do_merge = True  # always absorb preamble singletons
                blog(f"  Force-merge (preamble): [{a.id}] ({a.full_text_char_count}c) "
                     f"+ [{b.id}] ({b.full_text_char_count}c)")
            elif (a.full_text_char_count < MIN_NODE_CHARS
                  or b.full_text_char_count < MIN_NODE_CHARS):
                do_merge = await _check_merge(structural_model, a, b)
                verdict = "MERGE" if do_merge else "skip"
                blog(f"  Check [{a.id}] ({a.full_text_char_count}c) "
                     f"+ [{b.id}] ({b.full_text_char_count}c) → {verdict}")

            if do_merge:
                merged = _merge_nodes(a, b)
                breadcrumb = make_breadcrumb(doc_name, ancestors)
                title, topics = await _generate_topics(
                    quality_model, merged.full_text(), breadcrumb
                )
                merged.title = title
                merged.topics = topics
                pc = len([p for p in topics.split(";") if p.strip()])
                blog(f"    → [{merged.id}] '{title}' ({merged.full_text_char_count}c, {pc} phrases)")
                result[i:i + 2] = [merged]
                changed = True
                continue
            i += 1
    return result


async def _thin_all(
    structural_model: GenerativeModel,
    quality_model: GenerativeModel,
    node: Node,
    doc_name: str,
    ancestors: list[Node],
) -> None:
    """Post-order: thin every level from leaves upward."""
    new_ancestors = ancestors + [node]
    await asyncio.gather(*[
        _thin_all(structural_model, quality_model, c, doc_name, new_ancestors)
        for c in node.children
    ])
    if node.children:
        node.children = await _thin_level(
            structural_model, quality_model, node.children, doc_name, ancestors
        )


# ── Step 6: Summarise unprocessed leaves ──────────────────────────────────────

async def _summarise_leaves(
    model: GenerativeModel, node: Node, doc_name: str, ancestors: list[Node]
) -> None:
    """Generate title + topics for every leaf that has no topics yet."""
    if node.is_leaf():
        if not node.topics and node.level > 0:
            breadcrumb = make_breadcrumb(doc_name, ancestors)
            title, topics = await _generate_topics(model, node.full_text(), breadcrumb)
            node.title = title
            node.topics = topics
            pc = len([p for p in topics.split(";") if p.strip()])
            blog(f"  [{node.id}] '{title}' ({node.full_text_char_count}c) → {pc} phrases")
    else:
        new_ancestors = ancestors + [node]
        await asyncio.gather(*[
            _summarise_leaves(model, c, doc_name, new_ancestors)
            for c in node.children
        ])


# ── Step 8: Bottom-up intermediary rewriting ──────────────────────────────────

async def _rewrite_intermediates(
    model: GenerativeModel, node: Node, doc_name: str, ancestors: list[Node]
) -> None:
    """
    Bottom-up: for every non-leaf node, generate title + topics from children's
    titles + topics only (not the corpus).
    """
    new_ancestors = ancestors + [node]
    await asyncio.gather(*[
        _rewrite_intermediates(model, c, doc_name, new_ancestors)
        for c in node.children
    ])

    if node.level == 0 or node.is_leaf():
        return

    breadcrumb = make_breadcrumb(doc_name, ancestors)
    title, topics = await _generate_intermediate_topics(
        model, node.title, node.children, breadcrumb
    )
    node.title = title
    node.topics = topics
    pc = len([p for p in topics.split(";") if p.strip()])
    blog(f"  [{node.id}] '{title}' ← {len(node.children)} children → {pc} phrases")


# ── Build pipeline ────────────────────────────────────────────────────────────

async def build_index(source_path: Path, output_path: Path) -> dict:
    """
    Full build pipeline:
      parse → hoist preamble → split large leaves → thin small leaves →
      summarise remaining leaves → rewrite intermediates → validate → save JSON.
    """
    token = init_build_context(request_id=source_path.name)
    log_path = output_path.with_suffix("").with_suffix(".build.log")
    try:
        blog(f"Build: {source_path.name}  ({source_path.stat().st_size // 1024}KB)")
        blog(f"Started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        blog(f"MAX_NODE_CHARS={MAX_NODE_CHARS}  MIN_NODE_CHARS={MIN_NODE_CHARS}")
        blog(f"MODEL_STRUCTURAL={MODEL_STRUCTURAL}  MODEL_QUALITY={MODEL_QUALITY}")

        print(f"[build] Reading {source_path.name} ({source_path.stat().st_size // 1024}KB)...")
        text = source_path.read_text()
        doc_name = source_path.stem

        def _node_stats_str(r: Node) -> str:
            nodes = r.all_nodes()
            cc = [n.full_text_char_count for n in nodes]
            lc: dict[int, int] = {}
            for n in nodes:
                lc[n.level] = lc.get(n.level, 0) + 1
            leaf_count = sum(1 for n in nodes if n.is_leaf())
            synth = sum(lc.get(l, 0) for l in range(4, 10))
            return (f"{len(nodes)} nodes (leaves={leaf_count})  "
                    f"#={lc.get(1,0)}  ##={lc.get(2,0)}  ###={lc.get(3,0)}  "
                    f"synthetic={synth}  "
                    f"chars min={min(cc)} max={max(cc)} avg={sum(cc)//len(cc)}")

        def _node_stats(label: str) -> None:
            print(f"[build] {label}: {_node_stats_str(root)}")

        blog_section("Step 1 — Parse")
        print("[build] Parsing heading tree...")
        root = parse_tree(text)
        _node_stats("After parse")
        blog(f"  {_node_stats_str(root)}")

        blog_section("Step 2 — Preamble hoisting")
        print("[build] Hoisting preamble content...")
        _hoist_preamble(root)
        _node_stats("After hoist")
        blog(f"  {_node_stats_str(root)}")

        structural_model = get_model(MODEL_STRUCTURAL)
        quality_model = get_model(MODEL_QUALITY)
        t0 = time.monotonic()

        blog_section("Steps 3–5 — Split oversized leaves")
        print(f"[build] Splitting oversized leaves "
              f"(threshold={MAX_NODE_CHARS}c, model={MODEL_STRUCTURAL})...")
        await _split_all(structural_model, root, doc_name, [])
        _node_stats("After split")
        blog(f"  {_node_stats_str(root)}")

        blog_section("Step 7 — Thin small nodes")
        print(f"[build] Thinning small nodes "
              f"(threshold={MIN_NODE_CHARS}c, model={MODEL_STRUCTURAL})...")
        await _thin_all(structural_model, quality_model, root, doc_name, [])
        _node_stats("After thin")
        blog(f"  {_node_stats_str(root)}")

        blog_section("Step 6 — Summarise unprocessed leaves")
        print(f"[build] Summarising unprocessed leaves (model={MODEL_QUALITY})...")
        await _summarise_leaves(quality_model, root, doc_name, [])

        blog_section("Step 8 — Rewrite intermediates (bottom-up)")
        print(f"[build] Rewriting intermediates bottom-up (model={MODEL_QUALITY})...")
        await _rewrite_intermediates(quality_model, root, doc_name, [])

        build_time = round(time.monotonic() - t0, 1)
        print(f"[build] Build done in {build_time}s")

        blog_section("Step 9 — Validate")
        print("[build] Validating...")
        validate(root)

        blog_section("Cost Estimate")
        total_build_cost = log_cost_summary()
        blog("")
        blog(f"Build time: {build_time}s")

        write_build_log(log_path)
        print(f"[build] Pipeline log → {log_path}")

        all_nodes = root.all_nodes()
        level_counts: dict[int, int] = {}
        for n in all_nodes:
            level_counts[n.level] = level_counts.get(n.level, 0) + 1

        nodes_flat = [
            {
                "id": n.id,
                "level": n.level,
                "title": n.title,
                "char_count": n.char_count,
                "full_text_char_count": n.full_text_char_count,
                "topics": n.topics,
                "phrase_count": len([p for p in n.topics.split(";") if p.strip()]),
                "is_preamble": n.is_preamble,
                "content": n.content,
            }
            for n in all_nodes
        ]

        index = {
            "source": str(source_path.resolve()),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "node_count": len(all_nodes),
            "build_time_s": build_time,
            "build_cost_usd": total_build_cost,
            "build_token_usage": get_build_usage(),
            "build_log": str(log_path.resolve()),
            "level_counts": level_counts,
            "nodes_flat": nodes_flat,
            "tree": root.to_dict(),
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
        print(f"[build] Index saved → {output_path}")
        return index
    finally:
        reset_build_context(token)


# ── Query ─────────────────────────────────────────────────────────────────────

async def _hierarchical_select(
    question: str,
    root: Node,
    model: GenerativeModel,
    nodes_by_id: dict,
) -> tuple:
    """
    Top-down tree walk: route at level-1, then discriminate within selected
    non-leaf nodes, repeating until all selected nodes are leaves.

    Returns (leaf_nodes, stages) where stages is a list of per-call dicts
    suitable for drill-down observability. Each stage records its outline,
    selected IDs, reasoning, token counts, and latency.
    """
    stages: list[dict] = []

    # ── Stage 1: routing — level-1 nodes only ────────────────────────────────
    level1_nodes = root.children
    level1_outline = render_children_outline(level1_nodes)
    stage1_prompt = make_route_section_prompt(level1_outline, question)
    raw, ms, usage = await llm_call(model, stage1_prompt, response_schema=NODE_SELECTION_SCHEMA)

    try:
        parsed = json.loads(raw)
        selected_ids: list[str] = parsed.get("selected_ids", [])
        reasoning: str = parsed.get("reasoning", "")
    except json.JSONDecodeError as e:
        selected_ids = []
        reasoning = f"[JSON parse error: {e}]"

    unresolved = [sid for sid in selected_ids if sid not in nodes_by_id]
    selected_nodes: list[Node] = [nodes_by_id[sid] for sid in selected_ids if sid in nodes_by_id]

    stages.append({
        "stage": 1,
        "type": "routing",
        "parent_ids": [],
        "outline": level1_outline,
        "outline_node_count": len(level1_nodes),
        "prompt_char_count": len(stage1_prompt),
        "selected_ids": selected_ids,
        "reasoning": reasoning,
        "unresolved_ids": unresolved,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "latency_ms": ms,
    })

    # ── Stage 2+: discrimination loop — walk until all selected are leaves ───
    stage_num = 2
    prior_reasoning = reasoning

    while True:
        leaves = [n for n in selected_nodes if n.is_leaf()]
        non_leaves = [n for n in selected_nodes if not n.is_leaf()]
        if not non_leaves:
            break

        parent_groups: list[tuple] = [(p, p.children) for p in non_leaves]
        all_children = [c for _, children in parent_groups for c in children]

        if len(all_children) <= _COMBINE_THRESHOLD:
            # One combined discrimination call for all children
            parent_summaries = [(p.id, p.title, p.topics) for p, _ in parent_groups]
            children_outline = render_children_outline(all_children)
            prompt = make_discriminate_prompt(question, parent_summaries, children_outline, prior_reasoning)
            raw, ms, usage = await llm_call(model, prompt, response_schema=NODE_SELECTION_SCHEMA)

            try:
                parsed = json.loads(raw)
                new_ids: list[str] = parsed.get("selected_ids", [])
                new_reasoning: str = parsed.get("reasoning", "")
            except json.JSONDecodeError as e:
                new_ids = []
                new_reasoning = f"[JSON parse error: {e}]"

            new_unresolved = [sid for sid in new_ids if sid not in nodes_by_id]
            new_selected = [nodes_by_id[sid] for sid in new_ids if sid in nodes_by_id]

            stages.append({
                "stage": stage_num,
                "type": "discrimination_combined",
                "parent_ids": [p.id for p, _ in parent_groups],
                "outline": children_outline,
                "outline_node_count": len(all_children),
                "prompt_char_count": len(prompt),
                "selected_ids": new_ids,
                "reasoning": new_reasoning,
                "unresolved_ids": new_unresolved,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "latency_ms": ms,
            })

            selected_nodes = leaves + new_selected
            prior_reasoning = new_reasoning

        else:
            # Per-parent parallel discrimination calls
            async def _one(parent: Node, children: list, prior: str, snum: int) -> tuple:
                ps = [(parent.id, parent.title, parent.topics)]
                co = render_children_outline(children)
                p = make_discriminate_prompt(question, ps, co, prior)
                r, ms, u = await llm_call(model, p, response_schema=NODE_SELECTION_SCHEMA)
                try:
                    parsed = json.loads(r)
                    nids: list[str] = parsed.get("selected_ids", [])
                    nr: str = parsed.get("reasoning", "")
                except json.JSONDecodeError as e:
                    nids = []
                    nr = f"[JSON parse error: {e}]"
                nsel = [nodes_by_id[sid] for sid in nids if sid in nodes_by_id]
                return nsel, {
                    "stage": snum,
                    "type": "discrimination_per_parent",
                    "parent_ids": [parent.id],
                    "outline": co,
                    "outline_node_count": len(children),
                    "prompt_char_count": len(p),
                    "selected_ids": nids,
                    "reasoning": nr,
                    "unresolved_ids": [sid for sid in nids if sid not in nodes_by_id],
                    "input_tokens": u.get("input_tokens", 0),
                    "output_tokens": u.get("output_tokens", 0),
                    "latency_ms": ms,
                }

            results = await asyncio.gather(*[
                _one(parent, children, prior_reasoning, stage_num)
                for parent, children in parent_groups
            ])

            new_selected = leaves[:]
            reasonings: list[str] = []
            for sel, stage_dict in results:
                new_selected.extend(sel)
                stages.append(stage_dict)
                reasonings.append(stage_dict["reasoning"])

            selected_nodes = new_selected
            prior_reasoning = "; ".join(reasonings)

        stage_num += 1

    return selected_nodes, stages


async def query_index(question: str, index: dict, model: GenerativeModel) -> dict:
    """
    Hierarchical PageIndex query.

    Selection — top-down tree walk:
      Stage 1 (routing): show level-1 nodes only, select relevant sections.
      Stage 2+ (discrimination): show children of selected non-leaf nodes,
        select specific subsections. Repeat until all selected nodes are leaves.
      Combined call when total children ≤ _COMBINE_THRESHOLD; per-parent parallel
        calls otherwise.

    Synthesis — full text of leaf nodes sent to quality LLM for free-text answer.

    Returns a dict with every intermediate artefact for eval drill-down.
    The top-level 'step1' key is an aggregated backward-compatible view of all
    selection stages; 'selection_stages' has the full per-call detail.
    """
    root = Node.from_dict(index["tree"])
    all_nodes = root.all_nodes()
    nodes_by_id = {n.id: n for n in all_nodes}

    # ── Hierarchical selection ───────────────────────────────────────────────
    selected_nodes, stages = await _hierarchical_select(question, root, model, nodes_by_id)

    # Aggregate across stages for backward-compatible step1 view
    stage1 = stages[0]
    last_stage = stages[-1]
    final_selected_ids = [n.id for n in selected_nodes]
    all_unresolved = [uid for s in stages for uid in s["unresolved_ids"]]
    total_sel_input  = sum(s["input_tokens"] for s in stages)
    total_sel_output = sum(s["output_tokens"] for s in stages)
    # Wall-clock latency: stage 1 is sequential; per-parent stages within a stage
    # run in parallel — use max latency per stage group, then sum across stages.
    stage_nums = sorted({s["stage"] for s in stages})
    total_sel_ms = sum(
        max(s["latency_ms"] for s in stages if s["stage"] == sn)
        for sn in stage_nums
    )
    selected_depth = {n.id: "leaf" for n in selected_nodes}  # all are leaves by construction

    # ── Synthesis ────────────────────────────────────────────────────────────
    outline = render_outline(root)  # kept for fallback only
    if selected_nodes:
        sections_text = "\n\n---\n\n".join(
            f"[Section {n.id}: {n.title}]\n{n.full_text(include_heading=False)}"
            for n in selected_nodes
        )
    else:
        sections_text = f"(no sections selected — outline follows)\n\n{outline}"

    step2_prompt = make_synthesize_prompt(question, sections_text)
    step2_raw, step2_ms, step2_usage = await llm_call(model, step2_prompt)
    answer = step2_raw.strip()

    chars_to_synthesis = len(sections_text)
    model_name = getattr(model, "_name", MODEL_QUALITY)
    total_input  = total_sel_input  + step2_usage.get("input_tokens", 0)
    total_output = total_sel_output + step2_usage.get("output_tokens", 0)
    query_cost   = cost_usd(model_name, total_input, total_output)

    return {
        "question": question,
        "node_ids_selected": final_selected_ids,
        "chars_to_synthesis": chars_to_synthesis,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "cost_usd": query_cost,
        # Backward-compatible aggregated view (run_eval.py reads this)
        "step1": {
            "outline_line_count": stage1["outline_node_count"],
            "outline_char_count": len(stage1["outline"]),
            "outline": stage1["outline"],
            "prompt_char_count": stage1["prompt_char_count"],
            "raw_response": "",  # not meaningful across stages
            "selected_ids": final_selected_ids,
            "selection_reasoning": last_stage["reasoning"],
            "unresolved_ids": all_unresolved,
            "selected_depth": selected_depth,
            "parent_selections": [],   # hierarchical walk never leaks parents to synthesis
            "expanded_ids": [],
            "input_tokens": total_sel_input,
            "output_tokens": total_sel_output,
            "latency_ms": total_sel_ms,
        },
        # Full per-stage detail for drill-down
        "selection_stages": stages,
        "step2": {
            "selected_nodes": [
                {
                    "id": n.id,
                    "level": n.level,
                    "title": n.title,
                    "direct_content_chars": n.char_count,
                    "full_text_chars": n.full_text_char_count,
                    "content_preview": n.content[:400] + ("…" if n.char_count > 400 else ""),
                }
                for n in selected_nodes
            ],
            "sections_text_char_count": chars_to_synthesis,
            "sections_text": sections_text,
            "prompt_char_count": len(step2_prompt),
            "raw_response": step2_raw,
            "answer": answer,
            "input_tokens": step2_usage.get("input_tokens", 0),
            "output_tokens": step2_usage.get("output_tokens", 0),
            "latency_ms": step2_ms,
        },
        "total_latency_ms": total_sel_ms + step2_ms,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_query_result(result: dict) -> None:
    """Human-readable drill-down printout of a single query result."""
    bar = "━" * 72
    s2 = result["step2"]

    print(f"\n{bar}")
    print(f"Question: {result['question']}")

    for stage in result.get("selection_stages", []):
        stype = stage["type"]
        label = {
            "routing": "Stage 1 — Routing",
            "discrimination_combined": f"Stage {stage['stage']} — Discrimination (combined)",
            "discrimination_per_parent": f"Stage {stage['stage']} — Discrimination [{stage['parent_ids']}]",
        }.get(stype, f"Stage {stage['stage']}")
        print(f"\n── {label} ({stage['latency_ms']}ms) ─────────────────────────────────")
        print(f"Shown: {stage['outline_node_count']} nodes")
        print(stage["outline"])
        print(f"\nSelected: {stage['selected_ids']}")
        print(f"Reasoning: {stage['reasoning']}")
        if stage["unresolved_ids"]:
            print(f"⚠  Unresolved: {stage['unresolved_ids']}")

    s1 = result["step1"]
    print(f"\n── Final selection ({s1['latency_ms']}ms total selection) ──────────────")
    print(f"Leaf IDs: {s1['selected_ids']}")

    print(f"\n── Synthesis ({s2['latency_ms']}ms) ────────────────────────────────────")
    if s2["selected_nodes"]:
        print("Nodes fetched:")
        for n in s2["selected_nodes"]:
            print(f"  [{n['id']}] {n['title']}")
            print(f"         direct={n['direct_content_chars']}c  "
                  f"full={n['full_text_chars']}c")
            print(f"         preview: {n['content_preview'][:180]}")
        print(f"Total text sent: {s2['sections_text_char_count']} chars")
    else:
        print("  (no nodes selected — fallback to outline)")

    print(f"\nAnswer ({s2['latency_ms']}ms):")
    print(f"  {s2['answer']}")
    print(f"\nTotal latency: {result['total_latency_ms']}ms")


async def _cmd_build(source: str, output: str) -> None:
    await build_index(Path(source), Path(output))


async def _cmd_query(index_path: str, question: str) -> None:
    index = json.loads(Path(index_path).read_text())
    model = get_model(MODEL_QUALITY)
    result = await query_index(question, index, model)
    _print_query_result(result)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "build":
        if len(sys.argv) != 4:
            print("Usage: pageindex.py build <source.md> <index.json>")
            sys.exit(1)
        asyncio.run(_cmd_build(sys.argv[2], sys.argv[3]))

    elif cmd == "query":
        if len(sys.argv) != 4:
            print('Usage: pageindex.py query <index.json> "<question>"')
            sys.exit(1)
        asyncio.run(_cmd_query(sys.argv[2], sys.argv[3]))

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
