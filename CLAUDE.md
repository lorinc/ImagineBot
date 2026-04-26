# ImagineBot — Claude Code root context

## Read first
At the start of every session, before anything else:
1. Read `.claude/SESSION.md`
2. Run `tail -40 .claude/HEURISTICS.log`
3. Output a session brief — 3–5 sentences max: what was done last session, what comes next. No headers, no bullet trees, no essay.

## Service map
```
src/
  gateway/        Entry point for all channels. Routing, session, tracing, feedback.
                  Deployed. Calls knowledge service directly (auth/access/security stubbed).

  knowledge/      Retrieval layer. PageIndex + Gemini 2.5 Flash. Given a query + source IDs,
                  returns cited answer. Deployed. Index loaded from GCS (or baked image fallback).

  ingestion/      Document intake. CLI pipeline: Drive → Markdown → PageIndex → GCS.
                  Not yet deployed as a service. See gdrive_integration_plan.md for roadmap.

  channel_web/    Web UI. Jinja2 SSR. Thin client: calls gateway, renders SSE stream.
                  Deployed. Google Sign-In auth, allowed-email list in Secret Manager.

  admin/          Tenant + corpus management. [not yet implemented]
  auth/           Token issuance and validation. [not yet implemented]
  access/         User-to-source mapping. [not yet implemented]
  security/       Rate limiting and input screening. [not yet implemented]
```

## Operational files

| File | Purpose | Key rule |
|------|---------|----------|
| `.claude/SESSION.md` | Per-session working state | Read at session start. Overwrite each new session. Gitignored. |
| `.claude/HEURISTICS.log` | Append-only institutional memory | Never edit past entries. `tail -40` to review recent. |
| `docs/PROJECT_PLAN.md` | Sprint breakdown and phase status | Update when phases complete or are added. |
| `src/<service>/CLAUDE.md` | Service-level context, architecture, current state | Read before touching that service. |
| `src/<service>/TODO.md` | Service-level backlog | Append-only. Strike through resolved items. |

Each file has a purpose header with its own format rules. CLAUDE.md does not duplicate them.

Use `/wrap` at the end of each session to update SESSION.md, HEURISTICS.log, and PROJECT_PLAN.md consistently.

## Per-service context
Load the CLAUDE.md in the service directory before making changes to that service.
