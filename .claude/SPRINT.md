# SPRINT.md — active multi-session work queue
# Gitignored. Updated by /wrap at session end.
# When an item is done: check box here AND strike through in the relevant TODO.md.
# SESSION.md TASK field should name the specific item being worked.
# One item per session. Stop after the first commit. User ends the session.

## Active

- [ ] BUG-Q1 — Override does not bypass overspecified branch  UAT FAIL 2026-04-28
          DEFERRED to gateway classification/routing deep dive sprint (item P).
          When override_active=True, classify() still runs on the previous query and
          returns overspecified, triggering generalization+note. Override should bypass
          Gate 2 (overspecified/underspecified) entirely and proceed straight to retrieval,
          just as it bypasses Gate 1 (OOS). Fix: in chat.py, skip the overspecified/underspecified
          branch when override_active is set.
          (gateway/TODO.md §Bugs — Override active does not bypass overspecified branch)

- [x] O — Contextual classify: pass session turns into scope gate  DEPLOYED 2026-04-28 (gateway-00018-dt8)
          UAT DEFERRED — contact offer (Gate 3) does not trigger reliably until item J
          (has_answer flag). UAT will be covered by item P (routing pattern UAT sprint).
          Follow-up utterances ("yes", "go ahead", "please do") evaluated in isolation
          hit OOS. Pass last N session turns into classify() so short replies are
          interpreted in conversational context.
          SUPERSEDED BY Q — history param removed from classify() when Q landed.
          (gateway/TODO.md §Conversation policy — Contextual classify)
- [ ] N — Gate 3 contact offer follow-up  BUG — UAT fail on item L  RESOLVED BY O
          Root cause: classify() has no session history; "yes" is always OOS cold.
          Fix: ship item O. No gateway state machine or per-intent classifier needed.
          (gateway/TODO.md §Conversation policy — Gate 3 contact offer follow-up)
- [ ] P — Routing pattern UAT sprint  (after H, I, J, M are deployed)
          End-to-end UAT of all routing paths: OOS, orientation, broad, focused, no-evidence
          (has_answer=false), override, contextual follow-up. One session, manual test matrix.
          Closes deferred UAT for items L, N, O.
- [x] A — async token fetch    (gateway/TODO.md §Bugs — sync identity token)
- [x] B — session expiry       (gateway/TODO.md §Session management)
- [x] C — feedback trace_id    (gateway/TODO.md §Bugs — feedback buttons missing)
- [x] D — Gate 3 evidence      (knowledge/TODO.md §has_evidence / selected_nodes)
- [ ] F — Gateway conversation policy spec   (docs/specs/gateway.md — draft + human approval)
- [ ] E — citation verify      (gateway/TODO.md §Stage 3 — citation verification)
- [x] G — Gate 1 scope override              (gateway/TODO.md §Conversation policy — Gate 1 override) DEPLOYED+UAT 2026-04-27
- [x] H — Gate 2 classifier expansion        (gateway/TODO.md §Conversation policy — Gate 2 classifier schema expansion)  DEPLOYED 2026-04-28 (gateway-00019-9kb, with Q)
          ClassifyResult dataclass replaces (in_scope, specific_enough) tuple. query_type enum:
          answerable → proceed; underspecified → clarification Q; overspecified → generalize+retrieve+note;
          multiple → fall-through (item I adds orchestration). 36 tests pass.
          UAT PENDING — see SESSION.md UAT scenarios.
- [ ] Q — Rewrite before classify  DEPLOYED 2026-04-28 (gateway-00019-9kb, commit a1a4e78)
          rewrite_standalone() runs before classify(). classify() receives self-contained
          question; history param removed from classify() entirely. 34 tests pass.
          UAT PARTIAL — overspecified rewrite works; override+overspecified bug logged as BUG-Q1.
          (gateway/TODO.md §Pipeline order — rewrite before classify)
- [ ] I — Gate 2 multi-question orchestration  (gateway/TODO.md §Conversation policy — Gate 2 multiple questions; depends on H)
- [ ] J — Gate 3b has_answer + transparency  (knowledge/TODO.md §Gate 3b has_answer flag + gateway/TODO.md §Conversation policy — Gate 3b; cross-service)
- [ ] K — Gate 3a routing candidates + transparency  (knowledge/TODO.md §Gate 3a routing candidates + gateway/TODO.md §Conversation policy — Gate 3a; cross-service)
- [x] L — Gate 3 LLM fallback reply  (gateway/TODO.md §Conversation policy — Gate 3 fallback) COMMITTED 2026-04-27 — UAT FAILED (see item N)
- [ ] M — Gate 1 override intent: LLM classifier  (gateway/TODO.md §Gate 1 — Override intent: LLM classifier)
          Note: item O does NOT supersede this. "Look it up anyway" is a meta-command about
          pipeline behavior, not a school topic — classify() correctly returns OOS regardless
          of history. Override intent requires a dedicated classifier framed around
          "did the user ask to retry search?" not "is this about school topics?"
- [ ] R — Ingestion pipeline redesign  (tracked in .claude/INGESTION_R.md)
          Phase 1 items 1–17 complete. Items 18–22 pending:
            18. Knowledge service warning (plan: ~/.claude/plans/ingestion-r-item18-knowledge-warning.md)
            19. Large doc handling (_split_at_headings + output size guard)
            20. Cost tracking (MAX_RUN_COST_USD abort threshold)
            21. Cloud Monitoring alert + GCP Budget Alert in setup_gcp.sh
            22. Update src/ingestion/ARCHITECTURE.md + CLAUDE.md
          After Phase 1 complete: GCP setup (setup_gcp.sh) + deploy + UAT.
- [ ] S — GitHub Actions deploy  (after item R)
          Replace deploy.sh with a GitHub Actions workflow: push to main triggers
          docker build → push → gcloud run deploy via Workload Identity Federation.
          Eliminates mid-session deploy context burn. WIF auth setup ~30min.

## Upcoming sprints

High-level direction only. Sequence may shift as active items land.

1. **H+Q UAT** — manual test matrix (5 scenarios in SESSION.md). One session.
2. **Google Drive integration** — automated ingestion pipeline: Drive → cleaned docs → rebuilt index → redeploy knowledge. Replaces the current manual corpus upload workflow.
3. **GitHub Actions deploy spike** — WIF-authenticated Actions workflow replaces deploy.sh. Spike: evaluate WIF setup, secrets injection, per-service matrix vs monorepo trigger, rollback story. Decision + plan doc before implementation. Eliminates context burn from mid-session deploys.
4. **Gateway classification / routing deep dive** — exhaustive end-to-end UAT of all routing paths (item P), plus any fixes that fall out: OOS, underspecified, overspecified, multiple, broad, focused, no-evidence, override, contextual follow-up. Closes deferred UAT for L, N, O. Includes BUG-Q1 (override does not bypass overspecified branch).

## Done

_(none yet — items stay in Active until archive pass)_
