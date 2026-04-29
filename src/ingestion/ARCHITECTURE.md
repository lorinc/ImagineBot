# ingestion — Architecture

## Role in the system

The ingestion pipeline converts school documents from Google Drive into a PageIndex
that the knowledge service loads at startup. It runs as a Cloud Run Job, triggered
by Cloud Scheduler. Drive is the authoritative document source — the pipeline never
writes back to Drive.

```
Google Drive (source folder)
    ↓ Step 1 — DOCX → native Google Docs (Drive server-side copy; native Google Docs are a no-op)
    ↓ Step 2 — Google Docs → baseline Markdown (Docs export API) + TOC strip
/tmp/pipeline/01_baseline_md/
    ↓ Step 3 — AI header cleanup (Gemini Flash Lite via REST API)
/tmp/pipeline/02_ai_cleaned/
    ↓ Step 4 — Table-to-prose conversion (pure Python)
/tmp/pipeline/02_ai_cleaned/  ← overwritten in-place
/tmp/pipeline/03_chunked/
    ↓ Step 5 — Semantic chunking by ## headers (pure Python)
    ↓ build_all() — PageIndex build (Vertex AI / ADC)
/tmp/index/
    ↓ GCS upload
gs://img-dev-index/<SOURCE_ID>/  ←  knowledge service reads at startup
```

The knowledge service never calls the ingestion pipeline. They are coupled only through GCS.

---

## Package layout

```
src/ingestion/
  job/
    main.py          Entrypoint: ADC auth → advisory lock → list files → diff → rebuild
    config.py        Env var defaults: DRIVE_FOLDER_ID, SOURCE_ID, GCS_BUCKET
    drive_sync.py    list_accepted_files() — DOCX + native Google Doc MIME types
    gcs_io.py        load/save manifest, upload_index, has_changes
    advisory_lock.py GCS-based lock with if_generation_match (create-only acquire)
  pipeline/
    config.py        DRIVE_GDOCS_FOLDER, GEMINI_MODEL, GEMINI_API_KEY_FILE, MAX_DOCUMENT_SIZE_FOR_AI
    drive_utils.py   find_or_create_folder(), list_google_docs_in_folder()
    steps/
      step1_docx_to_gdocs.py   Drive server-side files().copy() with mimeType conversion
      step2_gdocs_to_md.py     Export + _strip_toc()
      step3_ai_cleanup.py      Gemini header cleanup; skips docs > MAX_DOCUMENT_SIZE_FOR_AI
      step4_table_to_prose.py  table_to_prose(); overwrites 02_ai_cleaned/ in-place
      step5_chunk.py           Split on ## headings → chunk files
    _archive/
      auth_oauth.py  Archived (personal OAuth — incompatible with headless Cloud Run)
      run.py         Archived (local CLI runner — dead code in Cloud Run)
  build_index.py     build_all(corpus_dir, output_dir): Vertex AI PageIndex build
  log.py             Structured JSON logging: info/warning/error → one JSON line per call
  table_to_prose.py  Table → prose conversion (pure Python)
```

---

## Pipeline steps

```
Step 1  DOCX → native Google Docs    Drive server-side files().copy() — no local download.
                                     Native Google Docs (mimeType=application/vnd.google-apps.document)
                                     pass through unchanged (Step 1 is a no-op for them).
                                     Converted docs land in DRIVE_GDOCS_FOLDER subfolder.

Step 2  Google Docs → Markdown       Drive export API (text/markdown). _strip_toc() removes
                                     Google's anchor-link TOC blocks before writing to disk.
                                     Also extracts font-size styles metadata for Step 3.

Step 3  AI header cleanup            Gemini Flash Lite via REST. Strips base64 images first.
                                     Safety gate: aborts if any image data survives stripping.
                                     Skips docs > MAX_DOCUMENT_SIZE_FOR_AI chars (copies as-is).
                                     NOTE: chunked processing replaces this skip in Phase 1 item 19.

Step 4  Table-to-prose               pure Python. Overwrites 02_ai_cleaned/<stem>.md in-place
                                     (build_all() reads from here). Also writes copy to
                                     03_chunked/<stem>_prose.md for step5.

Step 5  Semantic chunking            Splits <stem>_prose.md on ## headings → <stem>_chunk_NN.md.

build_all()  PageIndex build         Called directly (asyncio.run) — no subprocess. Reads from
                                     /tmp/pipeline/02_ai_cleaned/. Writes to /tmp/index/.
```

---

## Change detection

`list_accepted_files()` returns `{id, name, mimeType, md5Checksum, version}` for each file:
- DOCX files: `md5Checksum` — changes only on content edit, not metadata edits
- Native Google Docs: `version` integer — increments only on content changes

`has_changes()` compares the current fingerprint map against
`gs://<GCS_BUCKET>/<SOURCE_ID>/manifest.json`. Any add, remove, or fingerprint change
triggers a full rebuild.

---

## Advisory lock

Lock file: `gs://<GCS_BUCKET>/_lock/ingestion.json`. TTL: 1 hour.

- **Acquire:** `blob.upload_from_string(..., if_generation_match=0)` — create-only atomic op.
  Two concurrent jobs cannot both acquire silently; the loser gets `PreconditionFailed`.
- **Release:** `blob.delete(if_generation_match=<recorded_generation>)` — only deletes our own lock.
  A post-SIGKILL replacement lock (written by a recovery job) is not accidentally deleted.

---

## Scratch space

`/tmp/pipeline/` is the flat scratch directory for one container execution.
No numbered subdirectories, no symlink. The container is ephemeral — `/tmp/` is cleared on start.

---

## Authentication

All steps use **Application Default Credentials** (ADC) via the job's service account.
Personal OAuth has been eliminated. The service account has:
- Drive: read/copy on the source folder
- Docs: read (for export)
- GCS: `storage.objectAdmin` on `gs://img-dev-index/`
- Vertex AI: `aiplatform.user` (for build_all / embedding calls)

---

## Logging

`src/ingestion/log.py` provides `info(message, **fields)`, `warning(...)`, `error(...)`.
Each call emits one JSON line to stdout. Cloud Run / Cloud Logging parses the `severity`
field for log level routing. Every log entry carries a `step` field and relevant context
(stem, chars, count, etc.).

---

## Accepted file contract

`list_accepted_files()` returns top-level files matching:
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX)
- `application/vnd.google-apps.document` (native Google Doc)

No subfolders. No Slides, Sheets, PDFs, images.

---

## Document content filtering

| Element | Handling | Mechanism |
|---|---|---|
| Inline base64 images | Stripped | `_strip_images()` in Step 3, before Gemini call |
| URL-linked images | Pass through | Intentional — no pipeline cost, no indexing harm |
| Page headers/footers | Omitted | Google Drive Markdown export omits page-level elements |
| Table of Contents | Stripped | `_strip_toc()` in Step 2, after export |

---

## Table-to-prose is mandatory before build_all()

Tables in markdown produce no structured facts in LLM extraction (validated empirically —
see HEURISTICS.log [2026-03-21]). Step 4 must always run before `build_all()`. Step 4
overwrites `02_ai_cleaned/<stem>.md` in-place; `build_all()` reads from there.

**Cell inheritance rule:** empty cells inherit the value from the same column in the
previous row only if the first column of the current row is also empty (continuation row).
Non-empty first column = new record. Enforced by 19 tests in `tests/ingestion/test_table_to_prose.py`.

---

## GCS layout

```
gs://img-dev-index/<SOURCE_ID>/
  manifest.json       — {files: [{name, mimeType, fingerprint}], last_run}
  multi_index.json    — routing index (read by knowledge service at startup)
  index_<stem>.json   — per-doc PageIndex files
```

---

## Guardrails

**Drive is source-only.** The pipeline never writes to Drive (no upload_intermediaries,
no artifact folders). Processed artifacts stay in `/tmp/` (ephemeral) or GCS.

**`group_id` per document must equal `source_id` — never null, never shared.**

**Step 4 before build_all() is invariant.** Do not reorder.

**Do not write personal OAuth tokens to the repo.** `token.json` and `*.pickle` are gitignored.

---

## Phase 1 implementation status (as of 2026-04-29)

Items completed: 1–10 (dead code, scratch space, server-side Step 1, MIME filter,
fingerprint change detection, TOC stripping, advisory lock fix, structured logging).

Items pending: 11–22 (ValidationError hierarchy, pre-flight validation, retry+raise,
run_report.json, GCS debug prefix, tools/status.py, Drive comment Layer 1, knowledge
service warning Layer 3, large doc chunking, cost tracking, Cloud Monitoring alert,
ARCHITECTURE.md + CLAUDE.md update).

See `docs/spikes/ingestion_redesign.md` §Implementation sequence Phase 1 for the full list.
