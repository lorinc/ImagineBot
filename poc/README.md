# POC — Knowledge Retrieval Experiments

Each POC answers specific open questions from `docs/design/RAG -- System Design.md`
before committing to an architecture. Run them in order; POC2 design depends on POC1 findings.

## POC1: Single-document PageIndex

**Source:** `data/pipeline/2026-03-22_001/02_ai_cleaned/en_policy5_code_of_conduct.md`

**Questions answered:**
- What is node density on a real document? (feeds routing layer design)
- Does two-step LLM (select sections → synthesise) work for vocab-mismatched queries?
- Is latency within the 5s soft limit?

### Workflow

```bash
# 1. Build the index (parse + summarise all nodes, save JSON)
cd poc/poc1_single_doc
python3 build/pageindex.py build \
  ../../data/pipeline/2026-03-22_001/02_ai_cleaned/en_policy5_code_of_conduct.md \
  eval/index.json

# 2. Run the eval battery (7 queries, full step trace to stdout + results.json)
python3 run/run_eval.py eval/index.json eval/results.json

# 3. One-off query
python3 build/pageindex.py query eval/index.json "Can students be excluded for drug use?"
```

Requires: `gcloud auth application-default login` + `GCP_PROJECT_ID=img-dev-490919` env var.

Note: use bare `python3`, not `.venv/bin/python`. google-cloud-aiplatform is installed at
user level (~/.local/lib/python3.12/site-packages), not in the project venv.

### Output

- `eval/index.json` — built tree: all node IDs, titles, summaries, full content
- `eval/results.json` — per-query: outline shown, selected IDs, reasoning,
  full text sent to synthesis, raw LLM responses, answer, latencies
- `post_mortem/findings.md` — fill in after reviewing results

## POC2: Multi-document routing

Planned after POC1 post-mortem. Design depends on findings.
