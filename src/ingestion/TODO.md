# TODO — ingestion open work

_Append-only. Resolve items by striking through and noting the outcome._

---

## DESIGN: multi-tenant corpus management via Google Drive

Full design in `src/ingestion/gdrive_integration_plan.md`.

Summary: tenants share a Drive folder (DOCX / Google Docs / Markdown) with the
ingestion service account; the pipeline runs invisibly on their behalf and writes
the index to GCS. Accepted formats: DOCX, native Google Docs, Markdown.

**Prerequisite before implementation:** resolve the open questions in the plan
(admin UI access model, subfolder recursion scope).

**Build order:** GCS bucket → Workload Identity → sources Firestore schema →
POST /admin/sources with Drive verify → parameterized pipeline job →
manual ingest trigger → knowledge service GCS read → scheduled polling (v2).

---

## SPIKE: multilingual corpus — EN → ES translation quality

This task is unavoidable once real users are active. The current approach (let the synthesis
LLM translate on the fly) produces inconsistent results and loses control over school-specific
terminology. Do not implement anything until the spike is complete.

**The core problem:**
Source documents are in English. Users ask in Spanish (continental and/or Latin American).
High-quality answers require that the Spanish text be produced once, reviewed, and stored —
not generated fresh on every query from a model that may render the same term differently
each time.

### Options to evaluate

**Option A — Translate at ingestion time (recommended starting point)**
Add a translation step to the pipeline (after AI cleanup, before chunking) that produces
`es_*.md` alongside the existing `en_*.md` files. Build a bilingual or parallel index.
At query time, knowledge retrieves and synthesizes from the language-appropriate variant.

- Pro: deterministic, auditable, human-correctable. Fix once, correct everywhere.
- Pro: fits the existing pipeline step model (step3 AI cleanup is a similar LLM-over-doc pass).
- Con: doubles index build cost and storage. Rebuild required on every corpus update.
- Translation engine candidates: Google Cloud Translation API, DeepL API, or a carefully
  prompted LLM (Gemini) with a controlled vocabulary overlay for school-specific terms.

**Option B — Translate answer post-synthesis**
Synthesize in English (corpus language), then pass the answer through a translation API
before returning it to the user. No index changes required.

- Pro: simpler pipeline change; no index rebuild needed.
- Con: still non-deterministic per query. School-specific terminology translates
  inconsistently across calls. No ability to review or correct.
- Con: translates the same underlying content on every request instead of once.

**Option C — Controlled vocabulary glossary (complement to A or B, not a replacement)**
Maintain a curated EN→ES glossary for school-specific terms (uniform names, procedural
vocabulary, role names). Inject into the synthesis or translation prompt.
Does not solve full translation but eliminates the most common recurring terminology errors
at very low cost. Implement this regardless of which option above is chosen.

### Open questions for the spike (answer these before evaluating options)

1. **Which Spanish variant(s) do actual users speak?** Continental (Spain) and Latin American
   Spanish differ in vocabulary and some grammar. If users are from a single region, one
   variant is the right target and the problem simplifies significantly.
   If mixed, both variants may be needed — does that mean two ES indexes?

2. **Who reviews translations?** For Option A to deliver on its "human-correctable" promise,
   someone must be able to review and correct the translated `.md` files. Is that feasible?
   If there is no reviewer, Option A's advantage over Option B shrinks.

3. **How often does the corpus update?** If documents change weekly, Option A's rebuild cost
   accumulates. If the corpus is stable for months at a time, rebuild cost is negligible.

4. **Are there school-specific terms that general translation models consistently get wrong?**
   Collect 10–20 examples before evaluating translation engines. These become the controlled
   vocabulary glossary (Option C) and the benchmark for comparing engines.

### What Option A would add to the pipeline

```
pipeline/steps/
  step3_ai_cleanup.py     — existing: LLM-based markdown cleanup
  step3b_translate.py     — NEW: EN → ES translation per document
                             input:  data/pipeline/latest/02_ai_cleaned/en_*.md
                             output: data/pipeline/latest/02_ai_cleaned/es_*.md
                             engine: TBD (Cloud Translation / DeepL / Gemini)
                             glossary: data/translation_glossary.json (controlled vocab)
```

Knowledge service change required: `POST /search` and `POST /topics` must accept a
`language` parameter and route to the appropriate index variant. The gateway threads
the detected query language through (see `src/gateway/TODO.md` — language detection item).

### Regional variant handling

Until question 1 above is answered, do not implement. If both variants are needed,
the least-cost path is a single "neutral" Latin American Spanish translation plus a
small regional override glossary for continental Spain terms — not two full indexes.
