#!/usr/bin/env python3
"""
pageindex.py — single-file PageIndex knowledge module for one markdown document.

Architecture:
  Build:  parse markdown headings → tree of nodes → LLM summarises each node → save JSON
  Query:  load index → show LLM outline of summaries → LLM selects node IDs →
          retrieve full text of selected nodes → LLM synthesises answer

  Every intermediate step is captured and returned so eval can drill into it.

Usage:
  python pageindex.py build <source.md> <index.json>
  python pageindex.py query <index.json> "<question>"
"""

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

# ── Config ────────────────────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
REGION = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")

# Per-step model assignments (Decision 3 in system_design_findings.md)
MODEL_STRUCTURAL = "gemini-2.0-flash"   # split boundaries + merge check (mechanical)
MODEL_QUALITY    = "gemini-2.5-flash"   # summarise + node selection + synthesis

# Max concurrent LLM calls during build (avoid rate-limit exhaustion)
_SUMMARISE_CONCURRENCY = 12

# Node size thresholds (characters of direct content / full text)
MAX_NODE_CHARS = 1800   # split if direct content exceeds this
MIN_NODE_CHARS = 500    # merge candidate if full text falls below this


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: str           # e.g. "2.4" or slug "monitoring-review"
    level: int        # 0 = root, 1 = #, 2 = ##, 3 = ###
    title: str        # cleaned heading text (no ** or {#...})
    content: str      # text directly under this heading (before any child heading)
    summary: str = ""
    children: list = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.content)

    def full_text(self, include_heading: bool = True) -> str:
        """Recursively: heading + direct content + all children full_text."""
        parts = []
        if include_heading and self.level > 0:
            parts.append(f"{'#' * self.level} {self.title}")
        if self.content:
            parts.append(self.content)
        for child in self.children:
            parts.append(child.full_text(include_heading=True))
        return "\n\n".join(p for p in parts if p)

    @property
    def full_text_char_count(self) -> int:
        return len(self.full_text())

    def all_nodes(self) -> list:
        """Flat list: self (if non-root) + all descendants, depth-first."""
        result = []
        if self.level > 0:
            result.append(self)
        for child in self.children:
            result.extend(child.all_nodes())
        return result

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        children = [cls.from_dict(c) for c in d.get("children", [])]
        n = cls(
            id=d["id"],
            level=d["level"],
            title=d["title"],
            content=d["content"],
            summary=d.get("summary", ""),
        )
        n.children = children
        return n


# ── Markdown parsing ──────────────────────────────────────────────────────────

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ANCHOR_RE = re.compile(r"\s*\{#[^}]+\}")
_SECTION_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _clean_title(raw: str) -> str:
    t = _BOLD_RE.sub(r"\1", raw)
    t = _ANCHOR_RE.sub("", t)
    return t.strip()


def _make_id(title: str, seen: dict) -> str:
    """Derive a stable, unique ID from the section title."""
    m = _SECTION_NUM_RE.match(title)
    if m:
        base = m.group(1)
    else:
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:24]
    if base not in seen:
        seen[base] = 0
        return base
    seen[base] += 1
    return f"{base}-{seen[base]}"


def parse_tree(text: str) -> Node:
    """Parse a markdown document into a heading tree. Returns root (level 0)."""
    root = Node(id="root", level=0, title="Document Root", content="")
    lines = text.splitlines(keepends=True)

    # Collect all heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, raw_title)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            raw = m.group(2).strip()
            heading_positions.append((i, level, raw))

    seen: dict[str, int] = {}
    node_list: list[tuple[int, Node]] = []

    for idx, (line_no, level, raw) in enumerate(heading_positions):
        title = _clean_title(raw)
        node_id = _make_id(title, seen)

        # Direct content = lines between this heading and the next heading (any level)
        start = line_no + 1
        end = heading_positions[idx + 1][0] if idx + 1 < len(heading_positions) else len(lines)
        content = "".join(lines[start:end]).strip()

        node = Node(id=node_id, level=level, title=title, content=content)
        node_list.append((line_no, node))

    # Build parent-child tree using a level-aware stack
    stack: list[Node] = [root]
    for _, node in node_list:
        while len(stack) > 1 and stack[-1].level >= node.level:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)

    return root


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _init_vertex() -> None:
    vertexai.init(project=GCP_PROJECT, location=REGION)


def get_model(model_name: str = MODEL_QUALITY) -> GenerativeModel:
    _init_vertex()
    return GenerativeModel(model_name)


async def _llm_call(model: GenerativeModel, prompt: str,
                    response_schema: dict | None = None) -> tuple[str, int]:
    """Single LLM call. Returns (response_text, latency_ms)."""
    t0 = time.monotonic()
    config = GenerationConfig(
        response_mime_type="application/json" if response_schema else "text/plain",
        response_schema=response_schema,
        temperature=0.0,
    )
    response = await model.generate_content_async(prompt, generation_config=config)
    ms = int((time.monotonic() - t0) * 1000)
    return response.text, ms


# ── Build: LLM schemas ────────────────────────────────────────────────────────

_SPLIT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                },
                "required": ["title", "start"],
            },
        }
    },
    "required": ["sections"],
}

_MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "should_merge": {"type": "boolean"},
        "merged_title": {"type": "string"},
    },
    "required": ["should_merge", "merged_title"],
}

# ── Build: semaphore ──────────────────────────────────────────────────────────

_SEM: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(_SUMMARISE_CONCURRENCY)
    return _SEM


# ── Build: split large nodes ──────────────────────────────────────────────────

def _split_text_by_starts(text: str, starts: list[str]) -> list[str]:
    """
    Locate each start phrase within text and return the slices between them.
    The first entry in `starts` anchors to position 0 (the LLM always places
    the first sub-section at the very beginning).  Returns [] on any failure
    so callers can leave the node untouched.
    """
    positions = [0]
    for start in starts[1:]:
        matched = False
        for prefix_len in (50, 30, 15):
            prefix = start[:prefix_len].strip()
            if not prefix:
                continue
            idx = text.find(prefix, positions[-1] + 1)
            if idx != -1:
                positions.append(idx)
                matched = True
                break
        if not matched:
            return []   # can't locate boundary — abort
    positions.append(len(text))
    slices = [text[positions[i]:positions[i + 1]].strip()
              for i in range(len(positions) - 1)]
    return [s for s in slices if s]


async def _split_large_node(model: GenerativeModel, node: Node) -> None:
    """
    If node's direct content exceeds MAX_NODE_CHARS, ask the LLM to identify
    semantic sub-section boundaries and prepend them as synthetic children.
    Mutates node in place; sets node.content = "" on success.
    """
    if node.char_count <= MAX_NODE_CHARS or not node.content.strip():
        return

    prompt = (
        f"Section: '{node.title}'\n\n"
        f"Text:\n{node.content}\n\n"
        "This section is too long to index as a single unit. "
        "Identify 2–6 meaningful semantic sub-sections. For each provide:\n"
        "  title: a short descriptive name\n"
        "  start: the first 50 characters of that sub-section, copied verbatim from the text\n"
        "The first sub-section MUST start at the very beginning of the text. "
        "Sub-sections must be exhaustive and contiguous."
    )

    async with _get_sem():
        raw, _ = await _llm_call(model, prompt, response_schema=_SPLIT_SCHEMA)

    try:
        sections = json.loads(raw).get("sections", [])
    except json.JSONDecodeError:
        return

    if len(sections) < 2:
        return

    slices = _split_text_by_starts(node.content, [s["start"] for s in sections])
    if len(slices) != len(sections):
        return

    synthetic: list[Node] = []
    for i, (sec, content) in enumerate(zip(sections, slices), 1):
        child = Node(
            id=f"{node.id}.s{i}",
            level=node.level + 1,
            title=sec["title"],
            content=content,
        )
        synthetic.append(child)

    # Synthetic children precede any heading-based children
    node.children = synthetic + node.children
    node.content = ""


async def _split_all(model: GenerativeModel, node: Node) -> None:
    """
    Recursively split all oversized nodes, depth-first.
    New synthetic children are recursed into immediately so a split that
    produces a still-oversized child is handled in the same pass.
    """
    await _split_large_node(model, node)
    await asyncio.gather(*[_split_all(model, c) for c in node.children])


# ── Build: thin small nodes ───────────────────────────────────────────────────

def _merge_nodes(a: Node, b: Node, title: str) -> Node:
    combined = "\n\n".join(p for p in [a.content, b.content] if p)
    merged = Node(id=a.id, level=a.level, title=title, content=combined)
    merged.children = a.children + b.children
    return merged


async def _check_merge(model: GenerativeModel, a: Node, b: Node) -> tuple[bool, str]:
    prompt = (
        f"Section A — '{a.title}':\n{a.full_text()[:600]}\n\n"
        f"Section B — '{b.title}':\n{b.full_text()[:600]}\n\n"
        "Should these two consecutive sections be merged into one index entry? "
        "Merge ONLY if they cover the same specific topic and a reader looking for "
        "either topic would naturally expect to find them together. "
        "If yes, provide a concise title for the merged section."
    )
    async with _get_sem():
        raw, _ = await _llm_call(model, prompt, response_schema=_MERGE_SCHEMA)
    parsed = json.loads(raw)
    fallback_title = f"{a.title} / {b.title}"
    return parsed["should_merge"], parsed.get("merged_title") or fallback_title


async def _thin_level(model: GenerativeModel, children: list[Node]) -> list[Node]:
    """
    Single left-to-right pass over a sibling list.  Merges consecutive pairs
    where ALL three conditions hold: both small, consecutive, semantically similar.
    Loops until a full pass produces no merges.
    """
    result = list(children)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            a, b = result[i], result[i + 1]
            if (a.full_text_char_count < MIN_NODE_CHARS
                    and b.full_text_char_count < MIN_NODE_CHARS):
                should, title = await _check_merge(model, a, b)
                if should:
                    result[i:i + 2] = [_merge_nodes(a, b, title)]
                    changed = True
                    continue  # re-check new node against its right neighbour
            i += 1
    return result


async def _thin_all(model: GenerativeModel, node: Node) -> None:
    """Post-order: thin every level from leaves upward."""
    await asyncio.gather(*[_thin_all(model, c) for c in node.children])
    if node.children:
        node.children = await _thin_level(model, node.children)


# ── Build: summarise ──────────────────────────────────────────────────────────

async def _summarise_node(model: GenerativeModel, node: Node) -> None:
    """
    Recursively summarise a node (leaves first via gather).
    Mutates node.summary in-place.
    """
    # Summarise all children first (in parallel, semaphore-limited)
    await asyncio.gather(*[_summarise_node(model, c) for c in node.children])

    if node.level == 0:
        return  # root — skip

    child_block = ""
    if node.children:
        child_lines = "\n".join(f"  - {c.title}: {c.summary}" for c in node.children)
        child_block = f"\n\nSub-sections covered:\n{child_lines}"

    content_block = node.content if node.content else "(no direct content)"

    prompt = (
        f"Section: {node.title}\n\n"
        f"Content:\n{content_block}"
        f"{child_block}\n\n"
        "Write 1–2 sentences describing what specific information this section contains. "
        "Be concrete — mention key rules, numbers, processes, or definitions present. "
        "Do NOT start with 'This section' or 'The section'."
    )

    async with _get_sem():
        text, _ = await _llm_call(model, prompt)
    node.summary = text.strip()


async def build_index(source_path: Path, output_path: Path) -> dict:
    """
    Full build pipeline:
      parse → split large nodes → thin small nodes → summarise → save JSON index.

    Returns the index dict (also written to output_path).
    """
    print(f"[build] Reading {source_path.name} ({source_path.stat().st_size // 1024}KB)...")
    text = source_path.read_text()

    print("[build] Parsing heading tree...")
    root = parse_tree(text)

    def _node_stats(label: str) -> None:
        nodes = root.all_nodes()
        cc = [n.char_count for n in nodes]
        lc: dict[int, int] = {}
        for n in nodes:
            lc[n.level] = lc.get(n.level, 0) + 1
        print(f"[build] {label}: {len(nodes)} nodes  "
              f"(#={lc.get(1,0)}  ##={lc.get(2,0)}  ###={lc.get(3,0)}  "
              f"synthetic={lc.get(4,0)+lc.get(5,0)+lc.get(6,0)})  "
              f"direct chars min={min(cc)} max={max(cc)} avg={sum(cc)//len(cc)}")

    _node_stats("After parse")

    structural_model = get_model(MODEL_STRUCTURAL)
    quality_model = get_model(MODEL_QUALITY)
    t0 = time.monotonic()

    print(f"[build] Splitting large nodes (threshold={MAX_NODE_CHARS} chars, model={MODEL_STRUCTURAL})...")
    await _split_all(structural_model, root)
    _node_stats("After split")

    print(f"[build] Thinning small nodes (threshold={MIN_NODE_CHARS} chars, model={MODEL_STRUCTURAL})...")
    await _thin_all(structural_model, root)
    _node_stats("After thin")

    all_nodes = root.all_nodes()
    print(f"[build] Summarising {len(all_nodes)} nodes "
          f"(concurrency={_SUMMARISE_CONCURRENCY}, model={MODEL_QUALITY})...")
    await _summarise_node(quality_model, root)
    build_time = round(time.monotonic() - t0, 1)
    print(f"[build] Build done in {build_time}s")

    # Recompute final stats after all phases
    all_nodes = root.all_nodes()
    level_counts: dict[int, int] = {}
    for n in all_nodes:
        level_counts[n.level] = level_counts.get(n.level, 0) + 1

    # Flat list for easy lookup in eval
    nodes_flat = [
        {
            "id": n.id,
            "level": n.level,
            "title": n.title,
            "char_count": n.char_count,
            "full_text_char_count": n.full_text_char_count,
            "summary": n.summary,
            "content": n.content,
        }
        for n in all_nodes
    ]

    index = {
        "source": str(source_path.resolve()),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "node_count": len(all_nodes),
        "build_time_s": build_time,
        "level_counts": level_counts,
        "nodes_flat": nodes_flat,
        "tree": root.to_dict(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"[build] Index saved → {output_path}")
    return index


# ── Query ─────────────────────────────────────────────────────────────────────

_NODE_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning": {"type": "string"},
    },
    "required": ["selected_ids", "reasoning"],
}


def _render_outline(root: Node) -> str:
    """Indented outline of all node IDs + summaries, as shown to the step-1 LLM."""
    lines = []
    for n in root.all_nodes():
        indent = "  " * (n.level - 1)
        lines.append(f"{indent}[{n.id}] {n.title}: {n.summary}")
    return "\n".join(lines)


async def query_index(question: str, index: dict, model: GenerativeModel) -> dict:
    """
    Two-step PageIndex query.

    Step 1 — Node selection:
      LLM sees full outline (all summaries). Returns JSON with selected_ids + reasoning.

    Step 2 — Synthesis:
      Full text of selected nodes sent to LLM. Free-text answer with inline section citations.

    Returns a dict with every intermediate artefact for both drill-down inspection
    (write to JSON) and human-readable printing (see run_eval.py).
    """
    root = Node.from_dict(index["tree"])
    all_nodes = root.all_nodes()
    nodes_by_id = {n.id: n for n in all_nodes}

    # ── Step 1: Node selection ───────────────────────────────────────────────

    outline = _render_outline(root)

    step1_prompt = (
        "You are helping answer a question about a school policy document. "
        "Below is an outline of the document: each line is [section_id] Title: summary.\n\n"
        f"OUTLINE:\n{outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select the section IDs whose full text must be read to answer the question. "
        "Be selective — only include sections directly relevant. "
        "Return JSON with:\n"
        "  selected_ids: array of section IDs (exactly as shown in the outline)\n"
        "  reasoning: one sentence explaining why these sections were chosen"
    )

    step1_raw, step1_ms = await _llm_call(model, step1_prompt,
                                           response_schema=_NODE_SELECTION_SCHEMA)

    try:
        step1_parsed = json.loads(step1_raw)
        selected_ids: list[str] = step1_parsed.get("selected_ids", [])
        selection_reasoning: str = step1_parsed.get("reasoning", "")
    except json.JSONDecodeError as e:
        selected_ids = []
        selection_reasoning = f"[JSON parse error: {e}] raw: {step1_raw[:300]}"

    # Resolve IDs → nodes (track unresolved for eval visibility)
    selected_nodes: list[Node] = []
    unresolved_ids: list[str] = []
    for sid in selected_ids:
        if sid in nodes_by_id:
            selected_nodes.append(nodes_by_id[sid])
        else:
            unresolved_ids.append(sid)

    # ── Step 2: Synthesis ────────────────────────────────────────────────────

    if selected_nodes:
        sections_text = "\n\n---\n\n".join(
            f"[Section {n.id}: {n.title}]\n{n.full_text(include_heading=False)}"
            for n in selected_nodes
        )
    else:
        # Fallback: no nodes selected — send outline so LLM can at least respond
        sections_text = f"(no sections selected — outline follows)\n\n{outline}"

    step2_prompt = (
        "Answer the following question using ONLY the document sections provided. "
        "For each claim, cite the section ID in square brackets, e.g. [3.4]. "
        "If the sections do not contain a clear answer, respond: "
        "'The provided sections do not answer this question.'\n\n"
        f"QUESTION: {question}\n\n"
        f"SECTIONS:\n{sections_text}"
    )

    step2_raw, step2_ms = await _llm_call(model, step2_prompt)
    answer = step2_raw.strip()

    return {
        "question": question,
        "step1": {
            "outline_line_count": len(outline.splitlines()),
            "outline_char_count": len(outline),
            "outline": outline,                          # full outline shown to LLM
            "prompt_char_count": len(step1_prompt),
            "raw_response": step1_raw,
            "selected_ids": selected_ids,
            "selection_reasoning": selection_reasoning,
            "unresolved_ids": unresolved_ids,
            "latency_ms": step1_ms,
        },
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
            "sections_text_char_count": len(sections_text),
            "sections_text": sections_text,             # full text sent to synthesis LLM
            "prompt_char_count": len(step2_prompt),
            "raw_response": step2_raw,
            "answer": answer,
            "latency_ms": step2_ms,
        },
        "total_latency_ms": step1_ms + step2_ms,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_query_result(result: dict) -> None:
    """Human-readable drill-down printout of a single query result."""
    bar = "━" * 72
    s1 = result["step1"]
    s2 = result["step2"]

    print(f"\n{bar}")
    print(f"Question: {result['question']}")

    print(f"\n── Step 1: Node Selection ──────────────────────────────────────────")
    print(f"Outline shown to LLM: {s1['outline_line_count']} nodes, "
          f"{s1['outline_char_count']} chars")
    print()
    print(s1["outline"])
    print()
    print(f"Reasoning: {s1['selection_reasoning']}")
    print(f"Selected IDs: {s1['selected_ids']}")
    if s1["unresolved_ids"]:
        print(f"⚠  Unresolved IDs (not in index): {s1['unresolved_ids']}")
    print(f"Latency: {s1['latency_ms']}ms")

    print(f"\n── Step 2: Synthesis ───────────────────────────────────────────────")
    if s2["selected_nodes"]:
        print("Nodes selected for full-text read:")
        for n in s2["selected_nodes"]:
            print(f"  [{n['id']}] {n['title']}")
            print(f"         direct={n['direct_content_chars']}c  "
                  f"with-children={n['full_text_chars']}c")
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
