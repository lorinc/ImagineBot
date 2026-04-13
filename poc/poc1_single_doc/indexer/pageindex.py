#!/usr/bin/env python3
"""
pageindex.py — single-file PageIndex knowledge module for one markdown document.

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
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import vertexai
from google.api_core.exceptions import ResourceExhausted
from vertexai.generative_models import GenerationConfig, GenerativeModel

# ── Config ────────────────────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
REGION = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")

# Per-step model assignments
MODEL_STRUCTURAL = "gemini-2.5-flash-lite"  # split boundaries + merge check (mechanical)
MODEL_QUALITY    = "gemini-2.5-flash"       # topics generation + synthesis

# Max concurrent LLM calls during build
_SUMMARISE_CONCURRENCY = 12

# Node size thresholds (characters of full text, all content in leaf nodes)
MAX_NODE_CHARS = 5000
MIN_NODE_CHARS = 1500

# Estimated Vertex AI pricing (USD per 1M tokens).
# Verify against https://cloud.google.com/vertex-ai/generative-ai/pricing before use.
PRICING_PER_1M_USD: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash":      {"input": 0.15,  "output": 0.60},
}


# ── Build log ─────────────────────────────────────────────────────────────────

_BUILD_LOG: list[str] = []
_BUILD_USAGE: dict[str, dict] = {}  # model_name → {calls, input_tokens, output_tokens}


def _blog(msg: str) -> None:
    """Append a line to the in-memory build log (thread-safe under asyncio)."""
    _BUILD_LOG.append(msg)


def _blog_section(title: str) -> None:
    _BUILD_LOG.append("")
    _BUILD_LOG.append(f"── {title} {'─' * max(0, 66 - len(title))}")


def _reset_build_log() -> None:
    global _BUILD_LOG, _BUILD_USAGE
    _BUILD_LOG = []
    _BUILD_USAGE = {}


def _track_usage(model_name: str, input_tokens: int, output_tokens: int) -> None:
    if model_name not in _BUILD_USAGE:
        _BUILD_USAGE[model_name] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    _BUILD_USAGE[model_name]["calls"] += 1
    _BUILD_USAGE[model_name]["input_tokens"] += input_tokens
    _BUILD_USAGE[model_name]["output_tokens"] += output_tokens


def _cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING_PER_1M_USD.get(model_name, {"input": 0.0, "output": 0.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: str
    level: int
    title: str
    content: str
    topics: str = ""
    is_preamble: bool = False
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

    def is_leaf(self) -> bool:
        return not self.children

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
            "topics": self.topics,
            "is_preamble": self.is_preamble,
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
            topics=d.get("topics", ""),
            is_preamble=d.get("is_preamble", False),
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

    heading_positions: list[tuple[int, int, str]] = []
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
    m = GenerativeModel(model_name)
    m._name = model_name  # remembered for cost tracking
    return m


async def _llm_call(
    model: GenerativeModel,
    prompt: str,
    response_schema: dict | None = None,
) -> tuple[str, int, dict]:
    """Single LLM call. Returns (response_text, latency_ms, usage).
    usage = {input_tokens: int, output_tokens: int} — may be empty if unavailable.
    Retries on 429 ResourceExhausted with exponential backoff (5s, 10s, 20s, 40s).
    """
    t0 = time.monotonic()
    config = GenerationConfig(
        response_mime_type="application/json" if response_schema else "text/plain",
        response_schema=response_schema,
        temperature=0.0,
    )
    delay = 5
    for attempt in range(5):
        try:
            response = await model.generate_content_async(prompt, generation_config=config)
            break
        except ResourceExhausted:
            if attempt == 4:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    ms = int((time.monotonic() - t0) * 1000)

    usage: dict = {}
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        usage = {
            "input_tokens":  getattr(um, "prompt_token_count",     0) or 0,
            "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
        }

    return response.text, ms, usage


# ── LLM schemas ───────────────────────────────────────────────────────────────

_TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "topics": {"type": "string"},
    },
    "required": ["title", "topics"],
}

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
                    "topics": {"type": "string"},
                },
                "required": ["title", "start", "topics"],
            },
        }
    },
    "required": ["sections"],
}

_MERGE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "should_merge": {"type": "boolean"},
    },
    "required": ["should_merge"],
}

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


# ── Build: semaphore ──────────────────────────────────────────────────────────

_SEM: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(_SUMMARISE_CONCURRENCY)
    return _SEM


# ── Build: breadcrumb ─────────────────────────────────────────────────────────

def _make_breadcrumb(doc_name: str, ancestors: list[Node]) -> str:
    parts = [doc_name] + [a.title for a in ancestors if a.level > 0]
    return " > ".join(parts)


# ── Build: topic generation helpers ──────────────────────────────────────────

_PHRASE_PROMPT = (
    "For each distinct concept, rule, or procedure in this section, "
    "write a 1–5 word topic phrase. Separate phrases with semicolons. "
    "No sentences, no elaboration."
)


async def _generate_topics(
    model: GenerativeModel, full_text: str, breadcrumb: str
) -> tuple[str, str]:
    """Generate (title, topics) for a leaf node from its full text."""
    prompt = (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Text:\n{full_text}\n\n"
        "1. Rewrite the section title as a 4–8 word information-dense index anchor "
        "(do not repeat the breadcrumb path).\n"
        f"2. {_PHRASE_PROMPT}"
    )
    async with _get_sem():
        raw, _, usage = await _llm_call(model, prompt, response_schema=_TOPICS_SCHEMA)
    _track_usage(getattr(model, "_name", MODEL_QUALITY),
                 usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    parsed = json.loads(raw)
    return parsed["title"].strip(), parsed["topics"].strip()


async def _generate_intermediate_topics(
    model: GenerativeModel,
    node_title: str,
    children: list[Node],
    breadcrumb: str,
) -> tuple[str, str]:
    """Step 8: generate (title, topics) for a non-leaf from children's titles+topics only."""
    child_block = "\n".join(f"- {c.title}: {c.topics}" for c in children)
    prompt = (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Section: {node_title}\n\n"
        "Sub-sections covered:\n"
        f"{child_block}\n\n"
        "Synthesise the index entry for this section.\n"
        "1. Rewrite the section title as a 4–8 word information-dense index anchor "
        "(do not repeat the breadcrumb path).\n"
        f"2. {_PHRASE_PROMPT}"
    )
    async with _get_sem():
        raw, _, usage = await _llm_call(model, prompt, response_schema=_TOPICS_SCHEMA)
    _track_usage(getattr(model, "_name", MODEL_QUALITY),
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
        _blog(f"  Hoisted preamble [{node.id}] '{node.title}' "
              f"({len(synth.content)}c) → [{synth.id}]")


# ── Steps 3–5: Split oversized leaves ────────────────────────────────────────

_MARKDOWN_INLINE = frozenset("*_`#")


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Strip inline markdown markers and collapse whitespace runs to a single space.
    Returns (norm_text, pos_map) where pos_map[i] is the original index of
    norm_text[i].  Handles both whitespace normalisation ('1.  ' → '1. ') and
    markdown stripping ('**bold**' → 'bold') so LLM start-string matching is
    robust to both classes of LLM copy-paste variation."""
    norm: list[str] = []
    pos_map: list[int] = []
    in_ws = False
    for i, c in enumerate(text):
        if c in _MARKDOWN_INLINE:
            in_ws = False   # inline marker resets whitespace run; char is dropped
        elif c in " \t\n\r\f\v":
            if not in_ws:
                norm.append(" ")
                pos_map.append(i)
                in_ws = True
        else:
            norm.append(c)
            pos_map.append(i)
            in_ws = False
    return "".join(norm), pos_map


def _split_text_by_starts(text: str, starts: list[str]) -> tuple[list[str], list[int]]:
    """
    Locate each start phrase within text using whitespace-normalised matching
    and return (slices, start_positions).  start_positions[i] is the offset of
    slice i in the original text.
    Returns ([], []) on any failure so callers can leave the node untouched.
    """
    norm_text, pos_map = _norm_map(text)

    def _find_norm(needle: str, after: int) -> int:
        """Find normalised needle in norm_text starting after `after`; return
        the corresponding position in the original text, or -1."""
        norm_needle = re.sub(r"\s+", " ",
                             re.sub(f"[{''.join(_MARKDOWN_INLINE)}]", "", needle)).strip()
        if not norm_needle:
            return -1
        # translate `after` (original pos) to normalised pos
        norm_after = next((j for j, p in enumerate(pos_map) if p >= after), len(pos_map))
        idx = norm_text.find(norm_needle, norm_after)
        return pos_map[idx] if idx != -1 else -1

    positions = [0]
    for start in starts[1:]:
        matched = False
        for prefix_len in (50, 30, 15):
            idx = _find_norm(start[:prefix_len], positions[-1] + 1)
            if idx != -1:
                positions.append(idx)
                matched = True
                break
        if not matched:
            return [], []
    positions.append(len(text))
    slices = [text[positions[i]:positions[i + 1]].strip()
              for i in range(len(positions) - 1)]
    # filter empty slices but keep positions in sync
    result = [(s, positions[i]) for i, s in enumerate(slices) if s]
    if not result:
        return [], []
    texts, pos_out = zip(*result)
    return list(texts), list(pos_out)


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

    _blog(f"  [{node.id}] '{node.title}' "
          f"full_text={node.full_text_char_count}c > MAX={MAX_NODE_CHARS}c → splitting")

    breadcrumb = _make_breadcrumb(doc_name, ancestors)
    prompt = (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Section: '{node.title}'\n\n"
        f"Text:\n{node.content}\n\n"
        "This section is too long to index as a single unit. "
        "Identify 2–6 meaningful semantic sub-sections. For each provide:\n"
        "  title: a 1–8 word index title\n"
        "  start: the first 50 characters of that sub-section, copied verbatim from the text\n"
        f"  topics: {_PHRASE_PROMPT}\n"
        "The first sub-section MUST start at the very beginning of the text. "
        "Sub-sections must be exhaustive and contiguous."
    )

    async with _get_sem():
        raw, _, usage = await _llm_call(model, prompt, response_schema=_SPLIT_SCHEMA)
    _track_usage(getattr(model, "_name", MODEL_STRUCTURAL),
                 usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    try:
        sections = json.loads(raw).get("sections", [])
    except json.JSONDecodeError:
        _blog(f"  [{node.id}] split FAILED (JSON decode error)")
        return

    if len(sections) < 2:
        _blog(f"  [{node.id}] split FAILED (LLM returned {len(sections)} section(s), need ≥2)")
        return

    slices, slice_positions = _split_text_by_starts(node.content, [s["start"] for s in sections])
    if len(slices) != len(sections):
        for i, s in enumerate(sections[1:], 2):  # section 1 is implicit at pos 0
            start50 = s["start"][:50]
            norm_needle = re.sub(r"\s+", " ", start50).strip()
            in_source = norm_needle[:20] in re.sub(r"\s+", " ", node.content)
            _blog(f"    section {i} start={repr(start50[:40])} "
                  f"norm20={'found' if in_source else 'NOT FOUND'}")
        _blog(f"  [{node.id}] split FAILED (boundary detection: "
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
    _blog(f"  [{node.id}] → {len(synthetic)} children: {child_summary}")

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
    prompt = (
        f"Section A — '{a.title}':\n{a_repr}\n\n"
        f"Section B — '{b.title}':\n{b_repr}\n\n"
        "Should these two consecutive sections be merged into one index entry? "
        "Merge ONLY if they cover the same specific topic and a reader looking for "
        "either topic would naturally expect to find them together."
    )
    async with _get_sem():
        raw, _, usage = await _llm_call(model, prompt, response_schema=_MERGE_CHECK_SCHEMA)
    _track_usage(getattr(model, "_name", MODEL_STRUCTURAL),
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
                _blog(f"  Force-merge (preamble): [{a.id}] ({a.full_text_char_count}c) "
                      f"+ [{b.id}] ({b.full_text_char_count}c)")
            elif (a.full_text_char_count < MIN_NODE_CHARS
                  or b.full_text_char_count < MIN_NODE_CHARS):
                do_merge = await _check_merge(structural_model, a, b)
                verdict = "MERGE" if do_merge else "skip"
                _blog(f"  Check [{a.id}] ({a.full_text_char_count}c) "
                      f"+ [{b.id}] ({b.full_text_char_count}c) → {verdict}")

            if do_merge:
                merged = _merge_nodes(a, b)
                breadcrumb = _make_breadcrumb(doc_name, ancestors)
                title, topics = await _generate_topics(
                    quality_model, merged.full_text(), breadcrumb
                )
                merged.title = title
                merged.topics = topics
                pc = len([p for p in topics.split(";") if p.strip()])
                _blog(f"    → [{merged.id}] '{title}' ({merged.full_text_char_count}c, {pc} phrases)")
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
            breadcrumb = _make_breadcrumb(doc_name, ancestors)
            title, topics = await _generate_topics(model, node.full_text(), breadcrumb)
            node.title = title
            node.topics = topics
            pc = len([p for p in topics.split(";") if p.strip()])
            _blog(f"  [{node.id}] '{title}' ({node.full_text_char_count}c) → {pc} phrases")
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

    breadcrumb = _make_breadcrumb(doc_name, ancestors)
    title, topics = await _generate_intermediate_topics(
        model, node.title, node.children, breadcrumb
    )
    node.title = title
    node.topics = topics
    pc = len([p for p in topics.split(";") if p.strip()])
    _blog(f"  [{node.id}] '{title}' ← {len(node.children)} children → {pc} phrases")


# ── Step 9: Validate ──────────────────────────────────────────────────────────

def _validate(root: Node) -> None:
    all_nodes = root.all_nodes()
    errors: list[str] = []
    phrase_counts: list[int] = []
    node_chars: list[int] = []

    for n in all_nodes:
        if n.is_leaf() and n.full_text_char_count > MAX_NODE_CHARS:
            errors.append(f"  OVERSIZE leaf [{n.id}] {n.full_text_char_count}c")
        if not n.title:
            errors.append(f"  EMPTY title [{n.id}]")
        if not n.topics:
            errors.append(f"  EMPTY topics [{n.id}]")
        pc = len([p for p in n.topics.split(";") if p.strip()])
        phrase_counts.append(pc)
        node_chars.append(n.full_text_char_count)

    if errors:
        print("[validate] WARNINGS:")
        for e in errors:
            print(e)
            _blog(f"  WARNING: {e.strip()}")
    else:
        print("[validate] All checks passed.")
        _blog("  All checks passed.")

    if phrase_counts:
        line = (f"phrase_count  min={min(phrase_counts)} "
                f"max={max(phrase_counts)} avg={sum(phrase_counts)//len(phrase_counts)}")
        print(f"[validate] {line}")
        _blog(f"  {line}")
    if node_chars:
        line = (f"node_chars    min={min(node_chars)} "
                f"max={max(node_chars)} avg={sum(node_chars)//len(node_chars)}")
        print(f"[validate] {line}")
        _blog(f"  {line}")


# ── Build pipeline ────────────────────────────────────────────────────────────

async def build_index(source_path: Path, output_path: Path) -> dict:
    """
    Full build pipeline:
      parse → hoist preamble → split large leaves → thin small leaves →
      summarise remaining leaves → rewrite intermediates → validate → save JSON.
    """
    _reset_build_log()
    log_path = output_path.with_suffix("").with_suffix(".build.log")

    _blog(f"Build: {source_path.name}  ({source_path.stat().st_size // 1024}KB)")
    _blog(f"Started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    _blog(f"MAX_NODE_CHARS={MAX_NODE_CHARS}  MIN_NODE_CHARS={MIN_NODE_CHARS}")
    _blog(f"MODEL_STRUCTURAL={MODEL_STRUCTURAL}  MODEL_QUALITY={MODEL_QUALITY}")

    print(f"[build] Reading {source_path.name} ({source_path.stat().st_size // 1024}KB)...")
    text = source_path.read_text()
    doc_name = source_path.stem

    _blog_section("Step 1 — Parse")
    print("[build] Parsing heading tree...")
    root = parse_tree(text)

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

    _node_stats("After parse")
    _blog(f"  {_node_stats_str(root)}")

    _blog_section("Step 2 — Preamble hoisting")
    print("[build] Hoisting preamble content...")
    _hoist_preamble(root)
    _node_stats("After hoist")
    _blog(f"  {_node_stats_str(root)}")

    structural_model = get_model(MODEL_STRUCTURAL)
    quality_model = get_model(MODEL_QUALITY)
    t0 = time.monotonic()

    _blog_section("Steps 3–5 — Split oversized leaves")
    print(f"[build] Splitting oversized leaves "
          f"(threshold={MAX_NODE_CHARS}c, model={MODEL_STRUCTURAL})...")
    await _split_all(structural_model, root, doc_name, [])
    _node_stats("After split")
    _blog(f"  {_node_stats_str(root)}")

    _blog_section("Step 7 — Thin small nodes")
    print(f"[build] Thinning small nodes "
          f"(threshold={MIN_NODE_CHARS}c, model={MODEL_STRUCTURAL})...")
    await _thin_all(structural_model, quality_model, root, doc_name, [])
    _node_stats("After thin")
    _blog(f"  {_node_stats_str(root)}")

    _blog_section("Step 6 — Summarise unprocessed leaves")
    print(f"[build] Summarising unprocessed leaves (model={MODEL_QUALITY})...")
    await _summarise_leaves(quality_model, root, doc_name, [])

    _blog_section("Step 8 — Rewrite intermediates (bottom-up)")
    print(f"[build] Rewriting intermediates bottom-up (model={MODEL_QUALITY})...")
    await _rewrite_intermediates(quality_model, root, doc_name, [])

    build_time = round(time.monotonic() - t0, 1)
    print(f"[build] Build done in {build_time}s")

    _blog_section("Step 9 — Validate")
    print("[build] Validating...")
    _validate(root)

    _blog_section("Cost Estimate")
    total_build_cost = 0.0
    for mn, u in sorted(_BUILD_USAGE.items()):
        c = _cost_usd(mn, u["input_tokens"], u["output_tokens"])
        total_build_cost += c
        _blog(f"  {mn}")
        _blog(f"    calls={u['calls']}  "
              f"in={u['input_tokens']:,} tok  "
              f"out={u['output_tokens']:,} tok  "
              f"≈${c:.4f}")
    _blog(f"  ────────────────────────────────────────────────")
    _blog(f"  Total build cost: ≈${total_build_cost:.4f}")
    price_parts = [f"{k} in=${v['input']}/out=${v['output']}" for k, v in PRICING_PER_1M_USD.items()]
    _blog(f"  (Prices: {', '.join(price_parts)} per 1M tokens)")

    _blog("")
    _blog(f"Build time: {build_time}s")
    log_path.write_text("\n".join(_BUILD_LOG), encoding="utf-8")
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
        "build_token_usage": dict(_BUILD_USAGE),
        "build_log": str(log_path.resolve()),
        "level_counts": level_counts,
        "nodes_flat": nodes_flat,
        "tree": root.to_dict(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"[build] Index saved → {output_path}")
    return index


# ── Query ─────────────────────────────────────────────────────────────────────

def _render_outline(root: Node) -> str:
    """Indented outline of all node IDs + topics, as shown to the step-1 LLM."""
    lines = []
    for n in root.all_nodes():
        indent = "  " * (n.level - 1)
        lines.append(f"{indent}[{n.id}] {n.title}: {n.topics}")
    return "\n".join(lines)


async def query_index(question: str, index: dict, model: GenerativeModel) -> dict:
    """
    Two-step PageIndex query.

    Step 1 — Node selection:
      LLM sees full outline (all topics). Returns JSON with selected_ids + reasoning.

    Step 2 — Synthesis:
      Full text of selected nodes sent to LLM. Free-text answer with inline section citations.

    Returns a dict with every intermediate artefact for eval drill-down.
    """
    root = Node.from_dict(index["tree"])
    all_nodes = root.all_nodes()
    nodes_by_id = {n.id: n for n in all_nodes}

    # ── Step 1: Node selection ───────────────────────────────────────────────

    outline = _render_outline(root)

    step1_prompt = (
        "You are helping answer a question about a school policy document. "
        "Below is an outline of the document: each line is [section_id] Title: topics.\n\n"
        f"OUTLINE:\n{outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select the section IDs whose full text must be read to answer the question. "
        "Be selective — only include sections directly relevant. "
        "Return JSON with:\n"
        "  selected_ids: array of section IDs (exactly as shown in the outline)\n"
        "  reasoning: one sentence explaining why these sections were chosen"
    )

    step1_raw, step1_ms, step1_usage = await _llm_call(
        model, step1_prompt, response_schema=_NODE_SELECTION_SCHEMA
    )

    try:
        step1_parsed = json.loads(step1_raw)
        selected_ids: list[str] = step1_parsed.get("selected_ids", [])
        selection_reasoning: str = step1_parsed.get("reasoning", "")
    except json.JSONDecodeError as e:
        selected_ids = []
        selection_reasoning = f"[JSON parse error: {e}] raw: {step1_raw[:300]}"

    selected_nodes: list[Node] = []
    unresolved_ids: list[str] = []
    for sid in selected_ids:
        if sid in nodes_by_id:
            selected_nodes.append(nodes_by_id[sid])
        else:
            unresolved_ids.append(sid)

    selected_depth = {n.id: ("leaf" if n.is_leaf() else "parent") for n in selected_nodes}
    parent_selections = [nid for nid, depth in selected_depth.items() if depth == "parent"]

    # ── Step 2: Synthesis ────────────────────────────────────────────────────

    if selected_nodes:
        sections_text = "\n\n---\n\n".join(
            f"[Section {n.id}: {n.title}]\n{n.full_text(include_heading=False)}"
            for n in selected_nodes
        )
    else:
        sections_text = f"(no sections selected — outline follows)\n\n{outline}"

    step2_prompt = (
        "Answer the following question using ONLY the document sections provided. "
        "For each claim, cite the section ID in square brackets, e.g. [3.4]. "
        "If the sections do not contain a clear answer, respond: "
        "'The provided sections do not answer this question.'\n\n"
        f"QUESTION: {question}\n\n"
        f"SECTIONS:\n{sections_text}"
    )

    step2_raw, step2_ms, step2_usage = await _llm_call(model, step2_prompt)
    answer = step2_raw.strip()

    chars_to_synthesis = len(sections_text)
    model_name = getattr(model, "_name", MODEL_QUALITY)
    total_input  = step1_usage.get("input_tokens", 0) + step2_usage.get("input_tokens", 0)
    total_output = step1_usage.get("output_tokens", 0) + step2_usage.get("output_tokens", 0)
    query_cost   = _cost_usd(model_name, total_input, total_output)

    return {
        "question": question,
        "node_ids_selected": selected_ids,
        "chars_to_synthesis": chars_to_synthesis,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "cost_usd": query_cost,
        "step1": {
            "outline_line_count": len(outline.splitlines()),
            "outline_char_count": len(outline),
            "outline": outline,
            "prompt_char_count": len(step1_prompt),
            "raw_response": step1_raw,
            "selected_ids": selected_ids,
            "selection_reasoning": selection_reasoning,
            "unresolved_ids": unresolved_ids,
            "selected_depth": selected_depth,
            "parent_selections": parent_selections,
            "input_tokens": step1_usage.get("input_tokens", 0),
            "output_tokens": step1_usage.get("output_tokens", 0),
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
            "sections_text_char_count": chars_to_synthesis,
            "sections_text": sections_text,
            "prompt_char_count": len(step2_prompt),
            "raw_response": step2_raw,
            "answer": answer,
            "input_tokens": step2_usage.get("input_tokens", 0),
            "output_tokens": step2_usage.get("output_tokens", 0),
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
    if s1.get("parent_selections"):
        print(f"⚠  Parent selections (may over-fetch): {s1['parent_selections']}")
    if s1["unresolved_ids"]:
        print(f"⚠  Unresolved IDs (not in index): {s1['unresolved_ids']}")
    print(f"Latency: {s1['latency_ms']}ms")

    print(f"\n── Step 2: Synthesis ───────────────────────────────────────────────")
    if s2["selected_nodes"]:
        print("Nodes selected for full-text read:")
        for n in s2["selected_nodes"]:
            depth = s1["selected_depth"].get(n["id"], "?")
            print(f"  [{n['id']}] {n['title']}  ({depth})")
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
