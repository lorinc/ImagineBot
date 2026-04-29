# Ingestion Redesign — Implementation Tracker
# Gitignored. Updated inline as work progresses.
#
# CADENCE:
#   1. Plan + implement one logical chunk (1–4 spike items).
#   2. Run tests / smoke-check locally where possible.
#   3. Commit (git commit with meaningful message).
#   4. After all Phase 1 items done: deploy + UAT.
#   5. /wrap at end of session.
#
# SOURCE OF TRUTH: docs/spikes/ingestion_redesign.md §Implementation sequence
# Phase scope decision (Q4): PENDING — user decides Phase 1 only vs Phase 1+2.

---

## Pre-work (must land before any Phase 1 code)

- [x] Commit uncommitted files from prior sessions — already committed (commit 0bdb416)

---

## Phase 1 — Correctness + Contract

Items from spike §Implementation sequence Phase 1 (numbered 1–22):

- [x] 1. Commit prior-session files — already committed
- [x] 2. Dead code archived to pipeline/_archive/; OAUTH_TOKEN_PATH, upload_intermediaries,
         download_docx_to_local, _next_run_id, _setup_run_dir, _update_symlink removed (commit 4a9e6a6)
- [x] 3. subprocess.run(build_index.py) → asyncio.run(build_all()) (commit 4a9e6a6)
- [x] 4. Step 1: Drive server-side files().copy() with mimeType conversion (commit 4a9e6a6)
- [x] 5. list_accepted_files() accepts DOCX + native Google Doc MIME types (commit 4a9e6a6)
- [x] 6. Change detection: md5Checksum (DOCX) / version (Google Doc) fingerprints (commit 958466a)
- [x] 7. _strip_toc() in step2_gdocs_to_md.py (commit 958466a)
- [x] 8. /tmp/pipeline/ flat scratch; numbered run dirs eliminated (commit 4a9e6a6)
- [x] 9. Advisory lock: if_generation_match on acquire + release (commit 4b263e5)
- [x] 10. Structured JSON logging via src/ingestion/log.py across all pipeline files (commit c1491bd)
- [x] 11. ValidationError hierarchy: one subclass per error_type in rejection table (commit bd2a6cd)
- [x] 12. Pre-flight validation pass: run all files through Steps 1–2, collect ValidationErrors, abort before Step 3 (commit bd2a6cd)
- [x] 13. Error handling: retry wrapper (3× exp backoff) + StepError hierarchy + top-level catch → run_report.json + exit non-zero (commit bd2a6cd)
- [x] 14. run_report.json writer: called on every exit path; schema per spike §Error surface design (commit bd2a6cd)
- [x] 15. GCS debug prefix: DEBUG_MODE=true copies step outputs to gs://<bucket>/<source_id>/debug/<run_id>/; 7-day lifecycle in setup_gcp.sh (commit 7013834)
- [x] 16. tools/status.py: reads run_report.json, structured summary; --debug flag; documented in src/ingestion/CLAUDE.md (commit 7c46806)
- [x] 17. Layer 1 Drive comment: on validation failure; dedup by error_type before adding (commit 47e60cf)
- [ ] 18. Layer 3 knowledge service warning: read run_report.json at startup + /health; emit warning in SSE if status ≠ ok
- [ ] 19. Large doc handling: _split_at_headings() + _process_large_doc() + output size guard (reject if output > 3× input)
- [ ] 20. Cost tracking: token accumulation per run; MAX_RUN_COST_USD abort threshold
- [ ] 21. Cloud Monitoring alert on job failure + GCP Budget Alert in setup_gcp.sh
- [ ] 22. Update src/ingestion/ARCHITECTURE.md and CLAUDE.md to reflect all of the above

---

## Phase 2 — Event detection + incremental (pending Q4)

- [ ] 1. Drive Changes API: pageToken in GCS, drive.changes.list() replacing manifest diff
- [ ] 2. GCS baseline cache for Step-2 outputs (baseline/{stem}.md)
- [ ] 3. main.py delta logic: only process changed files through Steps 3–5
- [ ] 4. Cloud Scheduler interval → 15 minutes

---

## DONE

_(items move here when committed)_
