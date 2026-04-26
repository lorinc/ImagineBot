# ImagineBot — Claude Code root context

## Read first
At the start of every session, before anything else:
1. Read `.claude/SESSION.md`
2. Run `tail -40 .claude/HEURISTICS.log`
3. Read `docs/ARCHITECTURE.md`
4. Output a session brief — 3–5 sentences max: what was done last session, what comes next. No headers, no bullet trees, no essay.

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
