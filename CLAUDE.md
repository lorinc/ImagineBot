# ImagineBot — Claude Code root context

## Read first
At the start of every session, before anything else:
1. Read `.claude/SESSION.md`
2. Run `tail -40 .claude/HEURISTICS.log`
3. Output a session brief — 3–5 sentences max: what was done last session, what comes next. No headers, no bullet trees, no essay.

## What this is
A multi-service knowledge system: documents are ingested and kept current,
a knowledge layer serves answers to an LLM, and users interact through channels
(web UI first, WhatsApp later) with access controlled per user per data source.

## Stack
- **Language/Runtime:** Python 3.12
- **Framework:** FastAPI (all services)
- **Database:** Firestore (primary)
- **Knowledge retrieval:** Vertex AI Context Caching + Gemini 2.5 Flash (full-context, not RAG)
- **LLM:** Gemini 2.5 Flash via Vertex AI (both knowledge retrieval and answer synthesis)
- **Auth:** [TBD — see SPIKE: auth]
- **Frontend:** Jinja2 SSR, hand-written CSS (no framework, no build step)
- **Infra:** GCP — 2 projects: `img-dev` (staging) and `img-prod` (production)
           Cloud Run per service, Firestore, Secret Manager, Artifact Registry, Vertex AI
- **CI/CD:** GitHub Actions + Workload Identity Federation (one pool per project, no stored keys)
           Note: CI/CD workflows have placeholder values and are not yet wired up.
           Deploy path is local Docker only — see .claude/HEURISTICS.log ARCHIVE block.

## Service map
```
src/
  gateway/        API gateway. Single entry point for all channels.
                  Channels are thin clients — they call this, nothing else.
                  Routes requests after auth + access checks pass.

  ingestion/      Document intake and freshness. Watches sources, processes
                  changes, writes to the knowledge store. Runs on schedule
                  or webhook trigger, not on user request path.

  knowledge/      Retrieval layer. Given a query + permitted source IDs,
                  returns relevant context for the LLM.
                  Vertex AI Context Caching + Gemini 2.5 Flash (full-context, not RAG).

  security/       Rate limiting, abuse detection, malicious input screening.
                  Sits before the LLM call. Stateless where possible.

  auth/           Authentication. Issues and validates tokens.
                  [Design TBD — see SPIKE: auth]

  access/         User-to-data-source mapping. Given a user ID, returns
                  the set of source IDs they may query.
                  [Design TBD — see SPIKE: access control]

  channel_web/    Web UI channel. Jinja2 SSR. Thin client: formats requests
                  for the gateway, renders responses. No business logic here.
```

## Request flow (current understanding)
```
User → channel_web → gateway → [auth] → [access: get permitted sources]
     → [security: rate limit + screen] → [knowledge: retrieve context]
     → LLM call → response → channel_web → User
```
This flow is an assumption. Validate it in the architecture spike before building services.

## Operational files

| File | Purpose | Key rule |
|------|---------|----------|
| `.claude/SESSION.md` | Per-session working state | Read at session start. Overwrite each new session. Gitignored. |
| `.claude/HEURISTICS.log` | Append-only institutional memory | Never edit past entries. `tail -40` to review recent. |
| `docs/PROJECT_PLAN.md` | Sprint breakdown and phase status | Update when phases complete or are added. |

Each file has a purpose header with its own format rules. CLAUDE.md does not duplicate them.

Use `/wrap` at the end of each session to update all three files consistently.

## Dependency policy
This project is deliberately conservative on dependencies.
Before adding any package:
1. State what problem it solves
2. State what the alternative without it would be
3. Get explicit approval

Never add a package to solve a problem that three lines of Python would solve.
Never add a Node.js toolchain dependency. Frontend must be serveable without a build step.

## External enforcement checklist
- [ ] CI runs on every push (lint → contracts → unit → integration)
- [ ] CI blocks merge on failure (branch protection on main)
- [ ] Integration tests run against Firestore emulator in CI
- [ ] Staging deploy is automatic on merge to main
- [ ] Staging smoke tests run after deploy, open GitHub issue on failure
- [ ] Production deploy is manual trigger only
- [ ] Secrets in environment variables only — never in code
- [ ] `.claude/SESSION.md` is in `.gitignore`
- [ ] `.claude/settings.local.json` is in `.gitignore`
- [ ] Contract tests exist for every field the gateway exposes

## Per-service context
Load the CLAUDE.md in the service directory before making changes to that service.
