"""observability.py — build logging, token/cost tracking, validation, and outline rendering."""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import MAX_NODE_CHARS, PRICING_PER_1M_USD
from .node import Node

# ── Build context ──────────────────────────────────────────────────────────────

@dataclass
class BuildContext:
    log: list[str] = field(default_factory=list)
    usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    request_id: str = ""


_BUILD_CTX: ContextVar[BuildContext | None] = ContextVar("_BUILD_CTX", default=None)


def _ctx() -> BuildContext:
    ctx = _BUILD_CTX.get()
    if ctx is None:
        raise RuntimeError("observability call made outside a build_index context")
    return ctx


def init_build_context(request_id: str = "") -> "Token[BuildContext | None]":
    """Create a fresh BuildContext for this build call and bind it to the current task."""
    return _BUILD_CTX.set(BuildContext(request_id=request_id))


def reset_build_context(token: "Token[BuildContext | None]") -> None:
    """Restore the context to its state before init_build_context was called."""
    _BUILD_CTX.reset(token)


# ── Query context ──────────────────────────────────────────────────────────────

@dataclass
class QueryContext:
    trace_id: str
    spans: list[dict] = field(default_factory=list)
    stream_cb: Callable[[dict], None] | None = None


_QUERY_CTX: ContextVar["QueryContext | None"] = ContextVar("_QUERY_CTX", default=None)


def init_query_context(trace_id: str, stream_cb: Callable[[dict], None] | None = None) -> "Token[QueryContext | None]":
    return _QUERY_CTX.set(QueryContext(trace_id=trace_id, stream_cb=stream_cb))


def reset_query_context(token: "Token[QueryContext | None]") -> None:
    _QUERY_CTX.reset(token)


def emit_span(name: str, attributes: dict, duration_ms: int | None) -> dict:
    span = {"service": "knowledge", "name": name, "attributes": attributes, "duration_ms": duration_ms}
    ctx = _QUERY_CTX.get()
    if ctx:
        ctx.spans.append(span)
        if ctx.stream_cb:
            ctx.stream_cb(span)
    return span


def get_query_spans() -> list[dict]:
    ctx = _QUERY_CTX.get()
    return list(ctx.spans) if ctx else []


def get_build_usage() -> dict:
    """Snapshot of usage accumulated so far in the current build context."""
    return dict(_ctx().usage)


# ── Build log ─────────────────────────────────────────────────────────────────

def blog(msg: str) -> None:
    """Append a line to the current build context's log."""
    _ctx().log.append(msg)


def blog_section(title: str) -> None:
    ctx = _ctx()
    ctx.log.append("")
    ctx.log.append(f"── {title} {'─' * max(0, 66 - len(title))}")


def write_build_log(path: Path) -> None:
    path.write_text("\n".join(_ctx().log), encoding="utf-8")


# ── Usage & cost tracking ─────────────────────────────────────────────────────

def track_usage(model_name: str, input_tokens: int, output_tokens: int) -> None:
    usage = _ctx().usage
    if model_name not in usage:
        usage[model_name] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    usage[model_name]["calls"] += 1
    usage[model_name]["input_tokens"] += input_tokens
    usage[model_name]["output_tokens"] += output_tokens


def cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING_PER_1M_USD.get(model_name, {"input": 0.0, "output": 0.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def log_cost_summary() -> float:
    """Write per-model cost breakdown to the build log. Returns total cost USD."""
    usage = _ctx().usage
    total = 0.0
    for mn, u in sorted(usage.items()):
        c = cost_usd(mn, u["input_tokens"], u["output_tokens"])
        total += c
        blog(f"  {mn}")
        blog(f"    calls={u['calls']}  "
             f"in={u['input_tokens']:,} tok  "
             f"out={u['output_tokens']:,} tok  "
             f"≈${c:.4f}")
    blog(f"  {'─' * 48}")
    blog(f"  Total build cost: ≈${total:.4f}")
    price_parts = [f"{k} in=${v['input']}/out=${v['output']}"
                   for k, v in PRICING_PER_1M_USD.items()]
    blog(f"  (Prices: {', '.join(price_parts)} per 1M tokens)")
    return total


# ── Validation ────────────────────────────────────────────────────────────────

def validate(root: Node) -> None:
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
            blog(f"  WARNING: {e.strip()}")
    else:
        print("[validate] All checks passed.")
        blog("  All checks passed.")

    if phrase_counts:
        line = (f"phrase_count  min={min(phrase_counts)} "
                f"max={max(phrase_counts)} avg={sum(phrase_counts)//len(phrase_counts)}")
        print(f"[validate] {line}")
        blog(f"  {line}")
    if node_chars:
        line = (f"node_chars    min={min(node_chars)} "
                f"max={max(node_chars)} avg={sum(node_chars)//len(node_chars)}")
        print(f"[validate] {line}")
        blog(f"  {line}")


# ── Outline rendering ─────────────────────────────────────────────────────────

def render_outline(root: Node) -> str:
    """Indented outline of all node IDs + topics, as shown to the step-1 LLM."""
    lines = []
    for n in root.all_nodes():
        indent = "  " * (n.level - 1)
        suffix = (f"  [+{len(n.children)} children — do not select]"
                  if not n.is_leaf() else "")
        lines.append(f"{indent}[{n.id}] {n.title}: {n.topics}{suffix}")
    return "\n".join(lines)


def render_children_outline(nodes: list) -> str:
    """Flat outline of a specific node list, for hierarchical selection calls."""
    lines = []
    for n in nodes:
        suffix = (f"  [+{len(n.children)} children — do not select]"
                  if not n.is_leaf() else "")
        lines.append(f"[{n.id}] {n.title}: {n.topics}{suffix}")
    return "\n".join(lines)
