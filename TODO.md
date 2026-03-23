# TODO

## Observability — Graphiti ingestion and retrieval quality

Identified during local validation (2026-03-21). No observability currently exists
to detect ingestion gaps or retrieval failures automatically.

### O1 — Post-ingestion fact enumeration
After ingesting a document, enumerate the facts extracted per source_id and print
a summary. Without this, it's impossible to know if critical content was captured.

Minimum: `python validate.py --inspect --group_id family-manual` prints all facts
extracted from that source, grouped by entity pair.

Acceptance: running it after ingestion of the family manual shows at least one
fact containing a time value (e.g. "9h", "16:40", "8:00").

### O2 — Entity coverage assertions
After ingestion, assert that specific expected entities exist in the graph.
Defined as a list of (group_id, keyword) pairs that MUST appear in at least one
extracted fact. If any assertion fails, ingestion is considered incomplete.

Example assertions for family-manual:
- "8:00" or "9h" or "16:40" → school hours were captured
- "pick-up" or "pickup" → logistics were captured
- "Phidias" → communication platform was captured

### O3 — Ground truth query/answer pairs
A small fixed set of (query, group_ids, expected_keywords) triples. After ingestion,
run these and check that the top result contains the expected keywords.
This is the minimum regression test for retrieval quality.

Example:
  query: "What time does school start?"
  group_ids: ["family-manual"]
  expected_keywords_in_any_result: ["9h", "9:00", "8:00", "Early Bird"]

If none of the top-5 results contain any expected keyword → retrieval FAIL.

### E0 — knowledge service ingress temporarily set to `all`
During Sprint 1 acceptance testing (2026-03-21), `--ingress=internal` was changed to
`--ingress=all` to allow testing from a local machine. The service still requires a
valid identity token (`--no-allow-unauthenticated`), so there is no unauthenticated
access risk — but the service URL is publicly reachable (though auth-gated).

Restore to `--ingress=internal` once channel_web is deployed and the end-to-end flow
is validated. At that point, no external caller needs direct access to the knowledge
service. This is a Sprint 1 cleanup item, before Sprint 2 begins.

Command to restore:
```
gcloud run services update knowledge --ingress=internal --project=img-dev-490919 --region=europe-west1
```

---

### E1 — Shared Neo4j Aura instance across dev and prod
Currently only one Neo4j Aura Free instance exists. Both `img-dev` and `img-prod` point
to the same graph database. Risk: dev ingestion or test data contaminates production data;
a dev schema change could break production queries. Sprint 1 accepts this (POC only).

Fix before any production use: provision a second Neo4j Aura Free instance dedicated to
`img-prod`. Store separate credentials in each GCP project's Secret Manager.
This is a blocker for Sprint 4 (production hardening).

---

### O4 — Known issue: table-formatted data not extracted
During validation, the family manual timetable (markdown table, lines 196-203)
was NOT extracted as graph facts. A query for school hours returned staff names.
The graph contains 0 facts mentioning "8:00", "9h", "16:40", or "timetable".

Root cause: Graphiti's entity extraction (GPT-4o) did not produce RELATES_TO edges
for data presented in markdown table format. Entities and relationships in prose
are extracted; tabular schedules are not.

Fix: will be addressed in the corpus pre-processing phase (DOCX2MD pipeline).
Tables must be converted to prose before ingestion — this is a pre-processing
responsibility, not a Graphiti configuration issue.

---

## O5 — Capture and display corpus token count

After cache creation, log `cached_content.usage_metadata.total_token_count` and store
it alongside the cache metadata in Firestore (`config/context_cache`). Display the value
on the admin page so operators can see how much of the 1M-token context window is in use.

Acceptance: admin page shows corpus token count (e.g. "Corpus: 97,432 tokens / 1,048,576 max").

---

## A1 — Google Drive auth: switch to Domain-Wide Delegation before production

**Current (dev):** OAuth with personal `token.json` — acceptable locally.

**Production pattern: GCP service account + Domain-Wide Delegation (DWD)**

1. Create a dedicated Workspace account: `ingestion-bot@imaginemontessori.es`
2. Share the school Drive folder(s) with that account
3. Google Workspace Admin Console → grant DWD to `ingestion-sa@img-dev.iam.gserviceaccount.com`
   (and `ingestion-sa@img-prod.iam.gserviceaccount.com` for production)
4. Pipeline impersonates `ingestion-bot@imaginemontessori.es` via the GCP service account —
   no `token.json`, no OAuth flow, no human in the loop

**Why:** Personal/user OAuth tokens break on staff turnover or password rotation.
DWD is the standard pattern for unattended Workspace automation in GCP.

**Action required from school IT admin:** Grant DWD in Google Workspace Admin Console.
Flag this early — admin access may have approval lead time.

**Code impact:** Write the ingestion pipeline auth layer as a swappable module.
Switching from OAuth to DWD before production is a config change, not a rewrite.
