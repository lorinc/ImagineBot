"""parser.py — markdown parsing and text boundary detection.

All functions are pure (no LLM calls, no I/O). Safe to unit test directly.
"""

import re

from .node import Node

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


# ── Breadcrumb ────────────────────────────────────────────────────────────────

def make_breadcrumb(doc_name: str, ancestors: list[Node]) -> str:
    parts = [doc_name] + [a.title for a in ancestors if a.level > 0]
    return " > ".join(parts)


# ── Boundary detection ────────────────────────────────────────────────────────

# Inline markdown characters stripped during normalisation
_MARKDOWN_INLINE = frozenset("*_`#")


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Strip inline markdown markers and collapse whitespace runs to a single space.

    Returns (norm_text, pos_map) where pos_map[i] is the original index of
    norm_text[i]. Handles both whitespace normalisation ('1.  ' → '1. ') and
    markdown stripping ('**bold**' → 'bold') so LLM start-string matching is
    robust to both classes of LLM copy-paste variation.
    """
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


def split_text_by_starts(text: str, starts: list[str]) -> tuple[list[str], list[int]]:
    """Locate each start phrase within text using whitespace-normalised matching.

    Returns (slices, start_positions). start_positions[i] is the offset of
    slice i in the original text.
    Returns ([], []) on any failure so callers can leave the node untouched.

    Tries prefix lengths (50, 30, 15) per boundary to handle LLM copy-paste truncation.
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
