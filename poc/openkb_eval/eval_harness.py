"""OpenKB eval harness: compile KB, run queries, capture metrics."""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import litellm

litellm.drop_params = True  # Gemini rejects parallel_tool_calls=False from Agents SDK

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).parent.parent.parent / "data/pipeline/2026-03-22_001/02_ai_cleaned"
QUERIES_DIR = Path(__file__).parent.parent / "poc1_single_doc/eval"
KB_BASE = Path(__file__).parent / "kb"
RESULTS_DIR = Path(__file__).parent / "results"

MODEL = "gemini/gemini-2.5-flash"
JUDGE_MODEL = "gemini/gemini-2.5-flash"

# Gemini 2.5 Flash pricing (USD per 1M tokens)
PRICE_IN = 0.15 / 1_000_000
PRICE_OUT = 0.60 / 1_000_000

DOCUMENTS = [
    {
        "name": "policy1_hard",
        "doc_file": "en_policy1_child_protection.md",
        "queries_file": "queries_policy1_hard.json",
        "has_gold": True,
    },
    {
        "name": "policy3_hard",
        "doc_file": "en_policy3_health_safety_reporting.md",
        "queries_file": "queries_policy3_hard.json",
        "has_gold": True,
    },
    {
        "name": "policy5",
        "doc_file": "en_policy5_code_of_conduct.md",
        "queries_file": "queries_policy5.json",
        "has_gold": False,
    },
    {
        "name": "family_manual",
        "doc_file": "en_family_manual_24_25.md",
        "queries_file": "queries_family_manual.json",
        "has_gold": False,
    },
]

# ---------------------------------------------------------------------------
# Token/cost capture
# ---------------------------------------------------------------------------

_usage_log: list[dict] = []


def _capture_usage(kwargs, response_obj, start_time, end_time):
    try:
        usage = response_obj.usage
        _usage_log.append({
            "model": kwargs.get("model", ""),
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "latency_ms": int((end_time - start_time).total_seconds() * 1000),
        })
    except Exception:
        pass


async def _async_capture_usage(kwargs, response_obj, start_time, end_time):
    _capture_usage(kwargs, response_obj, start_time, end_time)


litellm.success_callback = [_capture_usage]
litellm._async_success_callback = [_async_capture_usage]  # noqa: SLF001
litellm.suppress_debug_info = True


def _compute_cost(log: list[dict]) -> float:
    return sum(u["input_tokens"] * PRICE_IN + u["output_tokens"] * PRICE_OUT for u in log)


def _sum_tokens(log: list[dict]) -> tuple[int, int]:
    return (
        sum(u["input_tokens"] for u in log),
        sum(u["output_tokens"] for u in log),
    )


# ---------------------------------------------------------------------------
# Chars tracking via module-level patch
# ---------------------------------------------------------------------------

_chars_read: int = 0


def _install_chars_patches():
    import openkb.agent.query as _qmod

    _orig_read = _qmod.read_wiki_file
    _orig_page = _qmod.get_wiki_page_content

    def _patched_read(path: str, wiki_root: str) -> str:
        global _chars_read
        result = _orig_read(path, wiki_root)
        _chars_read += len(result)
        return result

    def _patched_page(doc_name: str, pages: str, wiki_root: str) -> str:
        global _chars_read
        result = _orig_page(doc_name, pages, wiki_root)
        _chars_read += len(result)
        return result

    _qmod.read_wiki_file = _patched_read
    _qmod.get_wiki_page_content = _patched_page


# ---------------------------------------------------------------------------
# KB initialization
# ---------------------------------------------------------------------------

def _init_kb(kb_dir: Path, model: str) -> None:
    """Create the KB directory structure + .openkb config if not present."""
    from openkb.config import DEFAULT_CONFIG, save_config
    from openkb.schema import AGENTS_MD

    openkb_dir = kb_dir / ".openkb"
    if openkb_dir.exists():
        return

    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki/sources/images").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki/summaries").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki/concepts").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki/AGENTS.md").write_text(AGENTS_MD, encoding="utf-8")
    (kb_dir / "wiki/index.md").write_text(
        "# Knowledge Base Index\n\n## Documents\n\n## Concepts\n\n## Explorations\n",
        encoding="utf-8",
    )
    (kb_dir / "wiki/log.md").write_text("# Operations Log\n\n", encoding="utf-8")

    openkb_dir.mkdir()
    config = {
        "model": model,
        "language": DEFAULT_CONFIG["language"],
        "pageindex_threshold": DEFAULT_CONFIG["pageindex_threshold"],
    }
    save_config(openkb_dir / "config.yaml", config)
    (openkb_dir / "hashes.json").write_text("{}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Build step
# ---------------------------------------------------------------------------

async def build_kb(doc_name: str, doc_path: Path, kb_dir: Path) -> dict:
    from openkb.agent.compiler import compile_short_doc
    from openkb.converter import convert_document

    _usage_log.clear()
    t0 = time.monotonic()

    convert_result = convert_document(doc_path, kb_dir)
    if convert_result.skipped:
        print(f"  [build] {doc_name}: already compiled (hash match), skipping")
        return {"build_time_s": 0, "build_cost_usd": 0, "build_input_tokens": 0, "build_output_tokens": 0, "skipped": True}

    await compile_short_doc(doc_name, convert_result.source_path, kb_dir, MODEL)
    build_time_s = time.monotonic() - t0

    in_tok, out_tok = _sum_tokens(_usage_log)
    return {
        "build_time_s": round(build_time_s, 2),
        "build_cost_usd": round(_compute_cost(_usage_log), 6),
        "build_input_tokens": in_tok,
        "build_output_tokens": out_tok,
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """\
Question: {question}
Reference answer: {correct_answer}
System answer: {system_answer}

Does the system answer correctly address the question, consistent with the reference?
Respond with exactly: PASS or FAIL
Then on the next line: one sentence explaining why.
"""

_judge_usage_log: list[dict] = []

async def _judge(question: str, correct_answer: str, system_answer: str) -> dict:
    _judge_usage_log.clear()
    prompt = JUDGE_PROMPT.format(
        question=question,
        correct_answer=correct_answer,
        system_answer=system_answer,
    )
    resp = await litellm.acompletion(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    # Note: _capture_usage fires for this call too — separate tracking via _judge_usage_log
    # We track judge tokens by snapshotting _usage_log before/after
    text = resp.choices[0].message.content.strip()
    lines = text.splitlines()
    verdict = lines[0].strip().upper() if lines else "FAIL"
    if verdict not in ("PASS", "FAIL"):
        verdict = "PASS" if "pass" in text.lower() else "FAIL"
    reason = lines[1].strip() if len(lines) > 1 else ""
    usage = resp.usage
    cost = (getattr(usage, "prompt_tokens", 0) * PRICE_IN +
            getattr(usage, "completion_tokens", 0) * PRICE_OUT)
    return {"judge_verdict": verdict, "judge_reason": reason, "judge_cost_usd": round(cost, 8)}


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

async def run_one_query(question: str, kb_dir: Path, correct_answer: str | None) -> dict:
    global _chars_read
    from openkb.agent.query import run_query

    _usage_log.clear()
    _chars_read = 0

    t0 = time.monotonic()
    answer = await run_query(question, kb_dir, MODEL)
    latency_ms = int((time.monotonic() - t0) * 1000)

    in_tok, out_tok = _sum_tokens(_usage_log)
    result = {
        "answer": answer,
        "latency_ms": latency_ms,
        "chars_read": _chars_read,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(_compute_cost(_usage_log), 8),
        "llm_calls": len(_usage_log),
    }

    if correct_answer is not None:
        judge = await _judge(question, correct_answer, answer)
        result.update(judge)
    else:
        result["judge_verdict"] = "no_gold_standard"
        result["judge_reason"] = ""
        result["judge_cost_usd"] = 0.0

    return result


# ---------------------------------------------------------------------------
# Document eval
# ---------------------------------------------------------------------------

async def eval_document(doc_cfg: dict, dry_run: bool = False) -> dict:
    doc_name = doc_cfg["name"]
    doc_path = DOCS_DIR / doc_cfg["doc_file"]
    kb_dir = KB_BASE / doc_name
    queries_path = QUERIES_DIR / doc_cfg["queries_file"]

    print(f"\n=== {doc_name} ===")

    queries_raw = json.loads(queries_path.read_text())
    queries = queries_raw if isinstance(queries_raw, list) else queries_raw.get("queries", [])
    if dry_run:
        queries = queries[:1]

    _install_chars_patches()
    kb_dir.mkdir(parents=True, exist_ok=True)
    _init_kb(kb_dir, MODEL)

    print(f"  Building KB...")
    build_meta = await build_kb(doc_name, doc_path, kb_dir)
    print(f"  Build: {build_meta['build_time_s']}s, ${build_meta['build_cost_usd']:.4f}")

    results = []
    pass_count = 0
    total_with_gold = 0

    for q in queries:
        q_id = q.get("id", "?")
        question = q["question"]
        correct_answer = q.get("correct_answer") if doc_cfg["has_gold"] else None

        print(f"  [{q_id}] {question[:60]}...")
        qr = await run_one_query(question, kb_dir, correct_answer)

        verdict = qr.get("judge_verdict", "")
        if verdict in ("PASS", "FAIL"):
            total_with_gold += 1
            if verdict == "PASS":
                pass_count += 1
            print(f"         → {verdict} | ${qr['cost_usd']:.5f} | {qr['chars_read']:,} chars | {qr['latency_ms']}ms")
        else:
            print(f"         → ${qr['cost_usd']:.5f} | {qr['chars_read']:,} chars | {qr['latency_ms']}ms")

        results.append({
            "query_id": q_id,
            "question": question,
            **qr,
        })

    accuracy = f"{pass_count}/{total_with_gold}" if total_with_gold > 0 else "no_gold_standard"

    all_costs = [r["cost_usd"] for r in results]
    all_chars = [r["chars_read"] for r in results]
    all_latencies = [r["latency_ms"] for r in results]

    output = {
        "eval_run_at": datetime.now(timezone.utc).isoformat(),
        "system": "openkb",
        "model": MODEL,
        "document": doc_name,
        "query_count": len(results),
        **build_meta,
        "avg_latency_ms": int(sum(all_latencies) / len(all_latencies)) if all_latencies else 0,
        "avg_chars_read": int(sum(all_chars) / len(all_chars)) if all_chars else 0,
        "avg_cost_per_query_usd": round(sum(all_costs) / len(all_costs), 8) if all_costs else 0,
        "total_query_cost_usd": round(sum(all_costs), 6),
        "total_query_input_tokens": sum(r["input_tokens"] for r in results),
        "total_query_output_tokens": sum(r["output_tokens"] for r in results),
        "accuracy": accuracy,
        "queries": results,
    }

    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OpenKB eval harness")
    parser.add_argument("--doc", choices=[d["name"] for d in DOCUMENTS] + ["all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Run 1 query only")
    args = parser.parse_args()

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

    docs = DOCUMENTS if args.doc == "all" else [d for d in DOCUMENTS if d["name"] == args.doc]

    async def main():
        for doc_cfg in docs:
            result = await eval_document(doc_cfg, dry_run=args.dry_run)
            out_path = RESULTS_DIR / f"results_openkb_{doc_cfg['name']}.json"
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print(f"  Written: {out_path}")

    asyncio.run(main())
