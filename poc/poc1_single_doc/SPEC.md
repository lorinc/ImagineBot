# PageIndex — Technical Specification & Usage Guide

Single-document retrieval over markdown. No vector database, no embeddings, no RAG pipeline.
Build once, query many times. The index is a JSON file that fits in memory.

---

## Table of contents

1. [Concepts](#1-concepts)
2. [Package structure](#2-package-structure)
3. [Build pipeline](#3-build-pipeline)
4. [Query pipeline](#4-query-pipeline)
5. [Index JSON schema](#5-index-json-schema)
6. [Concurrency model](#6-concurrency-model)
7. [CLI reference](#7-cli-reference)
8. [Programmatic API](#8-programmatic-api)
9. [Configuration reference](#9-configuration-reference)
10. [Cost & performance](#10-cost--performance)
11. [Failure modes & known limitations](#11-failure-modes--known-limitations)

---

## 1. Concepts

### Node

A node is one section of the document. It has:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Stable identifier derived from the section number or title slug |
| `level` | `int` | Heading depth: 1 = `#`, 2 = `##`, 3 = `###` |
| `title` | `str` | Section heading text, cleaned of markdown formatting |
| `content` | `str` | Direct text of this section only — not children's text |
| `topics` | `str` | Semicolon-separated 1–5 word phrases summarising what this node covers |
| `is_preamble` | `bool` | True if this node was synthesised to hold text that appeared before the first child heading |
| `children` | `list[Node]` | Direct child nodes (one level deeper) |

`char_count` — characters in `content` (direct only).  
`full_text_char_count` — characters in heading + content + all children's full text, recursively.

### Leaf vs parent

A **leaf** node has no children. A **parent** node has at least one child. The retrieval step only selects leaf nodes; the outline explicitly marks parents as off-limits.

### Preamble node

When a section's markdown has text before its first sub-heading, that text gets hoisted into a synthetic child with `is_preamble=True`. This ensures that after build, all content lives in leaves (parents hold no content themselves).

### Index

The index is a JSON file produced by the build pipeline. It encodes the full document tree (titles, content, topics), plus build metadata (cost, timing, log path). Query only needs this file — the source markdown is not accessed again.

### Topics

A list of short phrases describing what a leaf node covers, e.g.:

```
Racism incident investigation; Racial slurs; Disciplinary escalation; Parent notification
```

Topics are the "search surface" the LLM sees during node selection. Well-formed topics are:
- 1–5 words each
- Noun phrases or gerund phrases, not sentences
- Specific enough to distinguish sibling nodes
- Separated by semicolons

### Outline

The outline is the text the LLM receives during node selection. One line per node:

```
[1] Child Protection Policy: safeguarding framework; legal duty; document scope
  [1.1] Definitions: child definition; harm categories; significant harm threshold  [+3 children — do not select]
    [1.1.1] Physical Harm: physical abuse indicators; non-accidental injury
    [1.1.2] Emotional Harm: emotional abuse signs; persistent emotional maltreatment
```

Parent lines carry the `[+N children — do not select]` annotation. The LLM is explicitly instructed to ignore these.

---

## 2. Package structure

```
poc/poc1_single_doc/
  indexer/
    __init__.py        Re-exports: get_model, MODEL_QUALITY, PRICING_PER_1M_USD
    config.py          Constants: models, thresholds, pricing, GCP project/region
    node.py            Node dataclass + to_dict / from_dict / full_text / all_nodes
    parser.py          parse_tree, make_breadcrumb, split_text_by_starts, _norm_map
    llm.py             get_model, llm_call, get_sem, response schemas (TOPICS_SCHEMA etc.)
    prompts.py         One make_*_prompt() function per LLM call site
    observability.py   BuildContext, ContextVar isolation, blog, track_usage, validate, render_outline
    pageindex.py       Build pipeline + query pipeline + CLI entry point
  run/
    run_eval.py        Eval harness: runs a query battery, writes results JSON + log
  eval/
    index_*.json       Pre-built indexes
    queries_*.json     Query batteries per document
    results_*.json     Eval results (output)
    *.log              Combined build + query pipeline logs
```

### Module dependencies (no cycles)

```
config  ←  node  ←  parser
config  ←  llm
config  ←  observability  ←  node
config, node, parser, llm, prompts, observability  ←  pageindex
```

`prompts.py` only imports `node.py`. All LLM calls are in `pageindex.py` (via `llm.py`). `prompts.py` never calls the LLM.

---

## 3. Build pipeline

Invoked by `build_index(source_path, output_path)`. Fully async; all LLM calls are concurrent up to the semaphore limit (default: 12).

### Step 1 — Parse

`parser.parse_tree(text) → Node`

Scans the markdown line by line. Every `#`/`##`/`###` heading starts a new node. Direct content is the text between a heading and the next heading of any level. Headings deeper than `###` are treated as content, not structure.

ID assignment:
- If the title begins with a decimal section number (`1.2.3`), the number is the ID.
- Otherwise, the title is slugified (lowercase, non-alphanumeric → `-`, truncated to 24 chars).
- Duplicates get a suffix: `intro`, `intro-1`, `intro-2`.

After parse, the tree mirrors the document's heading structure exactly. No LLM calls.

### Step 2 — Preamble hoisting

`_hoist_preamble(root)` — recursive, in place, no LLM calls.

Any parent node whose `content` is non-empty gets a synthetic child prepended:

```
Node(id=f"{parent.id}.p", level=parent.level+1, title=parent.title,
     content=parent.content, is_preamble=True)
```

After hoisting, every parent's `content` is `""`. All text lives in leaves. This is a prerequisite for the size-based processing in steps 3–8 to behave predictably.

### Steps 3–5 — Split oversized leaves

`_split_all(model, root, doc_name, ancestors)` — recursive, concurrent per sibling group.

A leaf is oversized if `full_text_char_count > MAX_NODE_CHARS` (default: 5,000).

For each oversized leaf, `make_split_prompt` asks the structural model to identify 2–6 semantic sub-section boundaries. The response is a JSON array of `{title, start, topics}` objects where `start` is the first ~50 characters of that sub-section, copied from the source text.

Boundary matching uses `split_text_by_starts`, which normalises both the needle and haystack before `str.find()`:

1. Strip inline markdown markers (`*`, `_`, `` ` ``, `#`)
2. Collapse all whitespace runs to a single space

This handles the two LLM copy-paste failure modes: extra spaces (`1.  text` → `1. text`) and markdown stripping (`**bold**` → `bold`). Prefix fallback tries lengths 50, 30, 15 in order so truncated LLM output still matches.

If boundary matching fails, the node is left unchanged (no partial split). The failure is logged.

After splitting, `_split_all` recurses into the new children immediately so still-oversized synthetic children are caught in the same pass.

### Step 7 — Thin small nodes

`_thin_all(structural_model, quality_model, root, doc_name, ancestors)` — post-order, concurrent per level.

A node is thin if `full_text_char_count < MIN_NODE_CHARS` (default: 1,500).

For each sibling list, a left-to-right pass considers adjacent leaf pairs:
- **Preamble node adjacent to anything** → always merge (no LLM call)
- **At least one thin node, combined ≤ MAX** → ask structural model: `should_merge: bool`
- **Both normal-sized** → skip

When merged, the quality model generates a new `(title, topics)` for the merged node. The loop repeats until a full pass produces no merges.

Note: step 7 runs after step 5 in the code (preamble hoisting creates thin nodes that need merging), but before step 6 in the pipeline numbering. The numbering reflects logical ordering, not code order.

### Step 6 — Summarise unprocessed leaves

`_summarise_leaves(quality_model, root, doc_name, ancestors)` — concurrent across all leaves.

Every leaf with no `topics` yet (i.e., not already processed by split or merge) gets a call to `make_topics_prompt`. The LLM returns `{title, topics}`. The leaf's `title` and `topics` fields are updated in place.

The breadcrumb (`doc_name > Parent > Grandparent`) is passed as context so the LLM does not repeat path information in the title.

### Step 8 — Rewrite intermediates

`_rewrite_intermediates(quality_model, root, doc_name, ancestors)` — bottom-up, concurrent per level.

Every non-leaf node (except root) gets a call to `make_intermediate_topics_prompt`. Crucially, this prompt only sees the children's `(title, topics)` — not the corpus text. This keeps intermediate-node topic generation cheap and fast, and ensures intermediate topics are aggregated from children rather than independently generated.

Root (`level=0`) is skipped.

### Step 9 — Validate

`validate(root)` — synchronous, no LLM calls.

Checks:
- No leaf exceeds `MAX_NODE_CHARS`
- No node has an empty `title`
- No node has empty `topics`

Reports per-tree statistics: phrase count (min/max/avg) and node char count (min/max/avg).

### Build context and logging

Every LLM call in the build pipeline writes to a `BuildContext` via `blog()` and `track_usage()`. The context is task-local (see §6). At the end of the pipeline:

- `write_build_log(log_path)` dumps the full log to `<index>.build.log`
- `log_cost_summary()` appends a per-model cost breakdown to the log and returns the total USD
- `get_build_usage()` snapshots the usage dict for embedding in the index JSON

---

## 4. Query pipeline

Invoked by `query_index(question, index, model)`. Two LLM round trips. No build context — query observability is not yet implemented.

### Step 1 — Node selection

The index tree is reconstructed from JSON (`Node.from_dict`). The outline is rendered by `render_outline`:

```
[1.1.1] Physical Harm: physical abuse indicators; non-accidental injury
[1.1.2] Emotional Harm: emotional abuse signs; persistent emotional maltreatment
[1.1] Definitions: child definition; harm categories  [+3 children — do not select]
```

`make_select_prompt(outline, question)` instructs the LLM to return `{selected_ids, reasoning}`. The LLM must only select leaf node IDs (those without the `[+N children]` annotation).

Unresolved IDs (not found in the tree) are captured and reported but do not cause failure.

### Lever 2 — Parent expansion fallback

If the LLM selects a parent despite the instruction, it is replaced by its direct children (not the full subtree). This is a conservative fallback: one level down, no recursion. In iter4 eval, this fallback never fired (0/16 queries).

### Step 2 — Synthesis

The full text of each selected node is retrieved via `node.full_text(include_heading=False)` — this recursively includes the node's direct content and all of its children's full text. Sections are concatenated with `\n\n---\n\n` separators and labelled `[Section {id}: {title}]`.

`make_synthesize_prompt(question, sections_text)` asks the LLM to answer using only the provided text and cite section IDs inline.

If no nodes resolved (all IDs were unresolvable), the full outline is used as fallback context.

### Return value

`query_index` returns a dict with every intermediate artefact:

```python
{
  "question": str,
  "node_ids_selected": list[str],
  "chars_to_synthesis": int,          # len(sections_text)
  "total_input_tokens": int,
  "total_output_tokens": int,
  "cost_usd": float,
  "step1": {
    "outline_line_count": int,
    "outline_char_count": int,
    "outline": str,                   # full outline shown to LLM
    "prompt_char_count": int,
    "raw_response": str,
    "selected_ids": list[str],
    "selection_reasoning": str,
    "unresolved_ids": list[str],
    "selected_depth": dict[str, str], # id → "leaf" | "parent"
    "parent_selections": list[str],   # IDs that were parents (expanded by lever 2)
    "expanded_ids": list[str],        # IDs added by lever 2 expansion
    "input_tokens": int,
    "output_tokens": int,
    "latency_ms": int,
  },
  "step2": {
    "selected_nodes": list[{          # nodes actually sent to synthesis
      "id": str,
      "level": int,
      "title": str,
      "direct_content_chars": int,    # node.char_count
      "full_text_chars": int,         # node.full_text_char_count
      "content_preview": str,         # first 400 chars of direct content
    }],
    "sections_text_char_count": int,
    "sections_text": str,             # full text sent to synthesis LLM
    "prompt_char_count": int,
    "raw_response": str,
    "answer": str,
    "input_tokens": int,
    "output_tokens": int,
    "latency_ms": int,
  },
  "total_latency_ms": int,
}
```

---

## 5. Index JSON schema

```json
{
  "source":           "/absolute/path/to/source.md",
  "built_at":         "2026-04-13T14:22:01Z",
  "node_count":       120,
  "build_time_s":     71.4,
  "build_cost_usd":   0.0162,
  "build_token_usage": {
    "gemini-2.5-flash-lite": {"calls": 43, "input_tokens": 18200, "output_tokens": 3100},
    "gemini-2.5-flash":      {"calls": 77, "input_tokens": 41000, "output_tokens": 8900}
  },
  "build_log":        "/absolute/path/to/index.build.log",
  "level_counts":     {"1": 12, "2": 48, "3": 60},
  "nodes_flat": [
    {
      "id":                   "1.2.3",
      "level":                3,
      "title":                "Referral Procedures for Child Protection Cases",
      "char_count":           2847,
      "full_text_char_count": 2847,
      "topics":               "referral procedure; local authority contact; timeline",
      "phrase_count":         3,
      "is_preamble":          false,
      "content":              "..."
    }
  ],
  "tree": {
    "id": "root", "level": 0, "title": "Document Root", "content": "",
    "topics": "", "is_preamble": false,
    "children": [ ... ]
  }
}
```

`nodes_flat` is a depth-first list of all non-root nodes, identical to what `root.all_nodes()` returns. It is included for eval convenience — `query_index` uses `tree` exclusively.

`build_log` is an absolute path on the machine that ran the build. It is informational; queries do not use it.

---

## 6. Concurrency model

### Build isolation via ContextVar

`observability.py` holds a single module-level `ContextVar`:

```python
_BUILD_CTX: ContextVar[BuildContext | None] = ContextVar("_BUILD_CTX", default=None)
```

`BuildContext` contains the log list and usage dict for one build call. When `build_index` is called, it does:

```python
token = init_build_context(request_id=source_path.name)
try:
    ...  # all blog() and track_usage() calls read _BUILD_CTX.get()
finally:
    reset_build_context(token)  # restores to pre-call state
```

Python's asyncio copies the current `contextvars.Context` when creating each new `Task`. So when `asyncio.gather` runs two `build_index` coroutines concurrently, each Task gets its own copy of the context. The `_BUILD_CTX.set()` inside each `build_index` only affects that Task's copy. The two builds have completely isolated logs and usage counters regardless of interleaving.

`blog()`, `track_usage()`, and `write_build_log()` all call `_BUILD_CTX.get()` and raise `RuntimeError` if called outside a `build_index` context. This makes misuse fail loudly.

### LLM call concurrency within a build

All LLM calls within a single build share a module-level `asyncio.Semaphore` (`_SUMMARISE_CONCURRENCY = 12`). This caps the number of simultaneous Vertex AI requests to avoid 429 ResourceExhausted errors.

If a 429 is received, `llm_call` retries with exponential backoff: 5s, 10s, 20s, 40s (up to 5 attempts). This covers typical Vertex quota reset windows for large documents.

The semaphore is module-level (not per-build). When multiple builds run concurrently, they share the semaphore, which is correct: the quota applies globally, not per document.

### Query concurrency

`query_index` is stateless with respect to observability. Multiple concurrent query calls are safe without any additional coordination.

---

## 7. CLI reference

The working directory for all commands must be `poc/poc1_single_doc/`.

### Build an index

```bash
python3 -m indexer.pageindex build <source.md> <index.json>
```

Example:
```bash
python3 -m indexer.pageindex build \
  ../../data/pipeline/latest/02_ai_cleaned/en_policy1_child_protection.md \
  eval/index_policy1.json
```

Output:
- `eval/index_policy1.json` — the index file
- `eval/index_policy1.build.log` — full pipeline trace

### Query an index

```bash
python3 -m indexer.pageindex query <index.json> "<question>"
```

Example:
```bash
python3 -m indexer.pageindex query eval/index_policy1.json \
  "What happens when a child discloses abuse to a teacher?"
```

Prints the full drill-down: outline shown to LLM, selected IDs with reasoning, nodes fetched (with char counts), and the synthesised answer.

### Run an eval battery

```bash
python3 run/run_eval.py <index.json> <queries.json> <results.json>
```

Example:
```bash
python3 run/run_eval.py \
  eval/index_policy1.json \
  eval/queries_policy1.json \
  eval/results_iter4_policy1.json
```

Output:
- `eval/results_iter4_policy1.json` — structured results (all intermediate artefacts per query)
- `eval/results_iter4_policy1.log` — human-readable combined build + query pipeline log

The summary table prints to stdout:

```
 #  Q (first 45 chars)                              #IDs  chars→synth      cost      ms  flags
 1  What are the reporting obligations for staff?      3        4,821  $0.00142   18204
 2  What happens when abuse is disclosed by a chi...   7       17,563  $0.00274   26891
```

---

## 8. Programmatic API

### Build

```python
import asyncio
from pathlib import Path
from indexer.pageindex import build_index

index = asyncio.run(build_index(
    source_path=Path("data/en_policy1.md"),
    output_path=Path("/tmp/policy1.json"),
))
# index is the full index dict (same as the JSON file)
```

### Query

```python
import asyncio, json
from pathlib import Path
from indexer import get_model, MODEL_QUALITY
from indexer.pageindex import query_index

index = json.loads(Path("/tmp/policy1.json").read_text())
model = get_model(MODEL_QUALITY)

result = asyncio.run(query_index(
    question="What is the school's policy on physical restraint?",
    index=index,
    model=model,
))

print(result["step2"]["answer"])
print(f"Cost: ${result['cost_usd']:.5f}")
print(f"Chars sent to synthesis: {result['chars_to_synthesis']}")
```

### Concurrent builds

```python
import asyncio
from pathlib import Path
from indexer.pageindex import build_index

async def main():
    results = await asyncio.gather(
        build_index(Path("doc_a.md"), Path("/tmp/a.json")),
        build_index(Path("doc_b.md"), Path("/tmp/b.json")),
    )
    for r in results:
        print(r["source"], r["build_cost_usd"])

asyncio.run(main())
```

Each build gets an isolated `BuildContext`. Logs and costs do not mix.

### Environment setup

Vertex AI auth uses Application Default Credentials. Before running locally:

```bash
gcloud auth application-default login
export GCP_PROJECT_ID=img-dev-490919    # default if unset
export VERTEX_AI_LOCATION=europe-west1  # default if unset
```

Dependencies (user-level install, not venv):

```bash
pip install google-cloud-aiplatform
```

Use `python3` directly, not a venv interpreter, unless the venv has the package installed.

---

## 9. Configuration reference

All constants live in `indexer/config.py`. Edit there to tune.

| Constant | Default | Effect |
|----------|---------|--------|
| `GCP_PROJECT` | `img-dev-490919` (or `$GCP_PROJECT_ID`) | Vertex AI project |
| `REGION` | `europe-west1` (or `$VERTEX_AI_LOCATION`) | Vertex AI region |
| `MODEL_STRUCTURAL` | `gemini-2.5-flash-lite` | Split detection, merge decisions |
| `MODEL_QUALITY` | `gemini-2.5-flash` | Topic generation, node selection, synthesis |
| `_SUMMARISE_CONCURRENCY` | `12` | Max simultaneous LLM calls per build |
| `MAX_NODE_CHARS` | `5000` | Leaf nodes larger than this are split |
| `MIN_NODE_CHARS` | `1500` | Leaf nodes smaller than this are merge candidates |
| `PRICING_PER_1M_USD` | see below | Used for cost logging only; does not affect behaviour |

Pricing defaults:

| Model | Input ($/1M) | Output ($/1M) |
|-------|-------------|--------------|
| `gemini-2.5-flash-lite` | 0.075 | 0.30 |
| `gemini-2.5-flash` | 0.15 | 0.60 |

Verify against current Vertex AI pricing before using for budgeting.

### Tuning MAX_NODE_CHARS and MIN_NODE_CHARS

The 5,000/1,500 defaults were calibrated on school policy documents (10–110 KB, dense prose). With these settings:

- avg chars sent to synthesis: ~5,500
- avg query cost: ~$0.0015
- no synthesis explosions (>40K chars) across 16 diverse queries

For documents with more uniform section sizes, `MIN_NODE_CHARS` can be raised to reduce fragmentation. For documents with very long procedural sections, `MAX_NODE_CHARS` can be raised to avoid unnecessary splits (at the cost of more chars per query).

The ratio `MIN / MAX = 0.3` is a reasonable starting point. Below `0.2` you get many merge candidates; above `0.4` you get fewer but larger nodes.

---

## 10. Cost & performance

Measured in iter4 on 4 documents, 16 queries.

### Build cost (one-time per document)

| Document | Size | Nodes | Build cost | Build time |
|----------|------|-------|-----------|------------|
| Child protection (policy1) | 38 KB | 35 | $0.005 | 74s |
| Health & safety (policy3) | 42 KB | 83 | $0.010 | 58s |
| Family manual | 52 KB | 49 | $0.006 | 60s |
| Code of conduct (policy5) | 107 KB | 120 | $0.016 | 71s |

Build time is dominated by LLM latency, not document size. Large documents hit the semaphore and retry limits; the 107 KB document took only marginally longer than the 38 KB one.

### Query cost

| Metric | Value |
|--------|-------|
| Average per query | ~$0.0015 |
| Cheapest | $0.00064 |
| Most expensive | $0.00274 |
| Queries per dollar | ~660 |

### Context sent to synthesis LLM

| Metric | Chars |
|--------|-------|
| Average | 5,518 |
| Minimum | 223 |
| Maximum | 17,563 |

The maximum (17,563 chars) was a genuine multi-section query requiring 7 leaf nodes across the child protection policy. It is not an anomaly — the answer required that breadth.

### Query latency

Two LLM round trips. Wall time is dominated by the Vertex AI calls:

- Typical: 15–25s total
- Fast (narrow query, single node): ~3s
- Slow (broad query, many nodes): ~30s
- Outlier (Vertex quota retry): up to 140s

### Memory

The index JSON is 120–365 KB on disk and roughly 2–5 MB when deserialised into Python objects. Loading is synchronous and takes <100ms. There is no streaming; the full tree is always in memory.

---

## 11. Failure modes & known limitations

### Split boundary detection fails silently

If `split_text_by_starts` cannot locate all section boundaries, the node is left unsplit and a warning is logged. The build succeeds with an oversized leaf. The validation step (`step 9`) will flag it.

When this happens: check the build log for `split FAILED`. The normalisation in `_norm_map` handles the two known LLM copy-paste failure modes (whitespace collapse, markdown stripping), but new modes are possible.

### Merge check is left-to-right, single pass per outer loop

The merge algorithm processes siblings left to right. If merging A+B makes the result small enough to then merge with C, that only happens in the next outer loop iteration. The loop repeats until stable, so eventually all mergeable pairs are handled, but it may take multiple passes.

### Intermediate node topics are aggregated, not re-read

Non-leaf topics are generated from children's summaries only — not from the corpus text. This is cheaper and fast, but means intermediate topics can miss nuance that is in the text but not reflected in any child's topics. If retrieval is missing relevant sections, check whether the intermediate node topics accurately represent the content below.

### Parent selections in queries

Lever 2 (parent expansion) replaces a selected parent with its direct children only — not the full subtree. If the answer requires content more than one level below the selected parent, those deeper nodes are not fetched. In practice, direct children are usually the right granularity.

### No cross-document retrieval

This pipeline is single-document. `query_index` takes one index. Routing across multiple documents, and merging or selecting between them, is the POC2 open question.

### No incremental re-build

The entire build pipeline re-runs from scratch on every invocation. There is no diffing or cache of intermediate results. For a 107 KB document, a full rebuild costs ~$0.016 and takes ~70s.

### Semaphore is module-level

`_SEM` is created once per Python process. If the concurrency limit needs to differ between builds (e.g., test builds vs. production builds), that is not currently supported without changing `config.py`. Restarting the process resets the semaphore.

### Vertex AI auth is implicit

`vertexai.init()` is called once inside `get_model()` on every call (harmless but slightly wasteful). Auth relies on Application Default Credentials. If ADC is not configured, every LLM call fails. There is no explicit pre-flight check.
