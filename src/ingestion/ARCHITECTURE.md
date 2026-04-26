# ingestion — Architecture

## Role in the system

The ingestion pipeline converts school documents from Google Drive into a PageIndex
that the knowledge service loads at startup. It is an **offline CLI tool** — not a
deployed service, not on the user request path.

```
Google Drive  →  [pipeline steps 1–5]  →  data/pipeline/<run_id>/02_ai_cleaned/
                                        →  [tools/build_index.py]
                                        →  data/index/multi_index.json  →  knowledge service
```

The knowledge service never calls the ingestion pipeline. The two are coupled only through
the filesystem: ingestion writes to `data/index/`, the knowledge service reads from it.

---

## Pipeline steps

```
Step 1  DOCX → native Google Docs       (Drive API, personal OAuth)
Step 2  Google Docs → baseline Markdown (Docs export API, personal OAuth)
Step 3  AI header cleanup               (Gemini Flash Lite via Vertex AI / ADC)
Step 4  Table-to-prose conversion       (pure Python, no LLM)
Step 5  Semantic chunking by ## headers (pure Python)
---
tools/build_index.py                    (PageIndex build from 02_ai_cleaned/, Vertex AI / ADC)
```

**Step 6 (Graphiti/Neo4j ingest) has been deleted.** It was dead code — never used in production,
Neo4j dependency gone. Removed 2026-04-26.

The index build (`tools/build_index.py`) is a separate tool, not a pipeline step. It reads
from `data/pipeline/latest/02_ai_cleaned/en_*.md`. Step 4 overwrites these files in-place with
prose-converted versions, so the index build always sees prose output provided Step 4 ran first.

---

## Run ID and the `latest` symlink

Each pipeline execution creates a timestamped directory: `data/pipeline/YYYY-MM-DD_NNN/`.
After any step completes, `data/pipeline/latest` symlink is updated to point at the current run.

`tools/build_index.py` and the knowledge service startup both reference `latest/`.
**If two pipeline runs happen in parallel, the symlink will point to whichever run finished last**,
potentially mixing outputs from different runs. The pipeline assumes single-operator
sequential execution — no locking mechanism exists.

---

## Authentication split

Steps 1–2 require **personal OAuth credentials** (`token.json`, created by `auth_oauth.py`'s
OAuth flow). These are the developer's personal Google credentials with Drive and Docs read
access to the specific folder. This is a personal-account dependency — if the developer's
account loses access, the pipeline cannot run.

Steps 3–5 and `build_index.py` require only **Application Default Credentials** (ADC):
`gcloud auth application-default login`. No personal OAuth needed.

**Production path:** Domain-Wide Delegation with a service account identity, not personal
OAuth. Do not implement this until the ingestion service is deployed as a Cloud Run job.

---

## Table-to-prose is mandatory before index build

Tables in markdown produce no structured facts in LLM extraction. This was validated
empirically: a school timetable table produced zero extracted facts; the same data as
prose sentences produced correct extraction. See HEURISTICS.log [2026-03-21] and
`table_to_prose.py`'s module docstring.

**Step 4 (table-to-prose) must always run before `build_index.py`.** Step 4 overwrites
`02_ai_cleaned/<stem>.md` in-place with prose-converted content and also writes a copy
to `03_chunked/<stem>_prose.md` for step5_chunk.py. Running `build_index.py` before
Step 4 will index tables instead of prose — producing zero extracted facts for table-heavy documents.

---

## Cell inheritance rule in table_to_prose

Empty cells inherit the value from the same column in the previous row **only if the
first column of the current row is also empty**. An empty first column signals a
"continuation" row (merged-cell pattern). A non-empty first column signals a new record —
empty subsequent cells are absent, not inherited.

This rule is documented in `table_to_prose.py`'s module docstring and enforced by
19 tests in `tests/ingestion/test_table_to_prose.py`. Do not change the inheritance
rule without updating the tests and the docstring simultaneously.

---

## Idempotency

Steps 1–5 overwrite their output directories if re-run. They are idempotent by
overwrite — not by skipping. `manifest.json` tracks current state per file as a status
record, not a skip-if-done gate.

---

## Boundaries — what ingestion owns vs. what it does NOT own

| Ingestion owns | Ingestion does NOT own |
|---|---|
| Drive→Docs→Markdown pipeline | Index serving (knowledge service) |
| Table-to-prose conversion | Query-time decisions |
| Semantic chunking | Knowing what questions users ask |
| Index build orchestration | Triggering itself (future: admin service triggers) |
| `data/pipeline/` and `data/index/` filesystem layout | Deployment of the knowledge service |

---

## Guardrails

**`group_id` per document must equal `source_id` — never null, never shared.**
Each document must have a unique, stable `group_id` that matches its `source_id` in the
knowledge service index. Sharing group IDs across documents breaks the per-source access
control model that the access service will enforce.

**Drive is the authoritative source; `data/` is scratch space.** Never treat local
`data/pipeline/` files as the canonical copy of a document. The canonical copy is in
Google Drive. If local data is lost, re-run the pipeline.

**Do not write personal OAuth tokens to the repo.** `token.json` is gitignored. Verify
with `git check-ignore -v token.json` if in doubt. See HEURISTICS.log [2026-04-12] for
the gitignore collision bug with `build/` directories.

**Test fixtures must be small representative documents, never full corpus files.**
`tests/fixtures/pipeline/` is committed. Full corpus documents are never in git.

**Before creating any new directory, check `.gitignore` for name collisions.**
Run `git check-ignore -v <path>`. The `build/` rule has already silently hidden source
files once (HEURISTICS.log [2026-04-12]).

---

## Known gaps (production blockers)

| Gap | Impact |
|---|---|
| Personal OAuth for Drive | Developer's machine and account required; non-transferable |
| Local filesystem only | Corpus lost if developer's machine is lost |
| No change detection | Full pipeline runs even when only one doc changed |
| No scheduling | Someone must remember to re-run after corpus updates |
| No audit trail | No record of when corpus was last refreshed or from what state |
| No multi-tenant isolation | All documents share a single corpus/index |

All of these are blocked on the ingestion service becoming a deployed Cloud Run job.
See `CLAUDE.md` "Future: deployed service" for the full roadmap.
