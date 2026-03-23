# src/ingestion/ — Claude Code context

## Purpose
Convert school DOCX files from Google Drive into knowledge-graph facts in Neo4j via Graphiti.
Runs on demand (not on the user request path). This is a batch pipeline, not a service.

**Document format: DOCX only.** No PDF, HTML, or plaintext support planned.
All source documents live in Google Drive — Drive is the authoritative source.

---

## Full pipeline (5 steps)

```
Google Drive: 0-docx-sources/
    ↓ Step 1 — DOCX → native Google Docs (Drive API, OAuth)
Google Drive: 1-native-gdocs/
    ↓ Step 2 — Google Docs → baseline Markdown (Docs export API)
data/pipeline/<run_id>/01_baseline_md/         ← local copy
    ↓ Step 3 — AI header cleanup (Gemini Flash Lite)
      Fixes header hierarchy using font-size metadata extracted in Step 2.
      IMPORTANT: Step 3 prompt explicitly PRESERVES tables — it does NOT convert them.
data/pipeline/<run_id>/02_ai_cleaned/
    ↓ Step 4 — Table-to-prose conversion (NEW — not in DOCX2MD reference)
      Converts markdown tables to narrative sentences before Graphiti ingestion.
      WHY: Graphiti entity extraction (LLM) does not produce graph edges for tabular data.
           Validated empirically: timetable table → 0 extracted facts; prose → extracted correctly.
      Rule: every cell value must appear in at least one prose sentence with its row/column context.
data/pipeline/<run_id>/03_chunked/
    ↓ Step 5 — Semantic chunking (split by ## headers)
      Each ## section becomes one Graphiti episode.
      WHY: ingesting a full document as one episode causes the LLM to fixate on the most
           prominent entities (e.g. staff directory) and skip lower-salience operational
           facts (e.g. "school starts at 9:00 AM").
      Rule: split on ## headings; each chunk ≥ 1 paragraph, ≤ ~2000 tokens.
data/pipeline/<run_id>/03_chunked/
    ↓ Step 6 — Graphiti ingestion
      graphiti.add_episode() per chunk, with:
        - group_id = source_id (e.g. "en_family_manual_24_25")
        - custom_extraction_instructions (see below — REQUIRED)
data/pipeline/<run_id>/04_ingested/<name>.done  ← idempotency marker
Neo4j Aura Free
```

### custom_extraction_instructions (REQUIRED for Step 6)

Without this, Graphiti skips facts like "school starts at 9:00 AM" because they lack
named-entity pairs. Always pass this to every add_episode() call:

```python
custom_extraction_instructions="""
Extract ALL operational facts, not just named-entity relationships.
Include facts where one side is implicit:
  - times and schedules ("school starts at 9:00 AM" → school STARTS_AT 9:00 AM)
  - procedures ("parents must sign the consent form" → parents MUST consent_form)
  - contact details, locations, platform names
Do not skip a fact because it lacks two named entities.
"""
```

See root CLAUDE.md `CORPUS_STATE` and `NEXT_SESSION` blocks for full context.

---

## Local data layout

Each pipeline run writes to a timestamped subfolder. See `docs/ARCHITECTURE.md`
"Ingestion pipeline: local data layout" for the full layout and rationale.

```
data/pipeline/
  2026-03-22_001/
    00_docx/          ← downloaded from Drive (never edited)
    01_baseline_md/   ← Step 2 output
    02_ai_cleaned/    ← Step 3 output
    03_chunked/       ← Steps 4+5 output
    04_ingested/      ← Step 6 markers (e.g. en_family_manual_24_25.done)
    manifest.json     ← per-file state: step, chunk_count, edges, ingested_at
  latest -> 2026-03-22_001/   ← symlink, updated after each run
```

`data/` is gitignored. Test fixtures for a small representative document
live in `tests/fixtures/pipeline/` (committed).

---

## Authentication

**All Drive/Docs API calls require OAuth (user account credentials).**
Service accounts have no Drive storage quota and cannot create or export files.

- **Dev:** `token.json` OAuth flow (personal account). See `REFERENCE_REPOS/DOCX2MD/` for reference.
- **Production:** service account + Domain-Wide Delegation impersonating
  `ingestion-bot@imaginemontessori.es`. See `TODO.md` item A1 and root `CLAUDE.md` for details.

---

## Idempotency

- Presence of `04_ingested/<name>.done` skips re-ingestion for that document.
- To re-ingest: delete the `.done` marker and re-run Step 6.
- Steps 1–5 are also idempotent: output files are overwritten if the step runs again.
- `manifest.json` tracks current state per file; do not trust it as a history log.

---

## Reference implementation

`REFERENCE_REPOS/DOCX2MD/` implements Steps 1–3 (Drive-centric, all OAuth).
Steps 4–6 are new and must be added to `src/ingestion/`.

Key files in the reference:
```
main.py                         Pipeline orchestrator (--step1/2/3/--all)
config.py                       Folder names, auth method, AI model
modules/auth_oauth.py           OAuth credential handling
modules/step1_docx_to_gdocs.py  DOCX → Google Docs (Drive API)
modules/step2_gdocs_to_markdown.py  Docs export → Markdown + font-size metadata
modules/step3_ai_cleanup.py     Gemini Flash Lite header cleanup
```

**Do not copy reference code without user approval.** REFERENCE_REPOS/ is read-only.

---

## Key invariants

- Tables must be converted to prose BEFORE Graphiti ingestion (Step 4 before Step 6).
- `custom_extraction_instructions` must be passed to every `add_episode()` call.
- `group_id` must equal `source_id` on every episode — never null, never shared across documents.
- Never ingest a full document as a single episode — always chunk by ## headers first.
- Drive is the authoritative source. `data/` is a local processing scratch space.

---

## Known issues

- O4: Timetable data in original corpus not extracted — root cause: table format, no prose conversion.
  Fix: Step 4 (table-to-prose) in this pipeline. See `TODO.md`.
