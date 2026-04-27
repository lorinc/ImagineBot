# ImagineBot — Claude Code root context

## Read first
At the start of every session, before anything else:
1. Read `.claude/SESSION.md`
2. Read `.claude/SPRINT.md`
3. Run `tail -40 .claude/HEURISTICS.log`
4. Read `docs/ARCHITECTURE.md`
5. Output a session brief — 3–5 sentences max: what was done last session, what comes next. No headers, no bullet trees, no essay.

## Operational files

| File | Purpose | Key rule |
|------|---------|----------|
| `.claude/SESSION.md` | Per-session working state | Read at session start. Overwrite each new session. Gitignored. |
| `.claude/SPRINT.md` | Active multi-session work queue | Check off items when done; also strike in TODO.md. Updated by `/wrap`. Gitignored. |
| `.claude/HEURISTICS.log` | Append-only institutional memory | Never edit past entries. `tail -40` to review recent. |
| `docs/ARCHITECTURE.md` | Cross-cutting topology, protocols, invariants, guardrails | Read at session start. Update when cross-service contracts change. |
| `docs/PROJECT_PLAN.md` | Sprint breakdown and phase status | Update when phases complete or are added. |
| `docs/specs/` | **Human-owned acceptance criteria and principles** | Read before implementing. Never modify without explicit approval. Surface conflicts — do not resolve them. |
| `src/<service>/CLAUDE.md` | Service-level context, architecture, current state | Read before touching that service. |
| `src/<service>/TODO.md` | Service-level backlog | Append-only. Strike through resolved items. |

Each file has a purpose header with its own format rules. CLAUDE.md does not duplicate them.

**Conflict rule:** If an implementation or test disagrees with anything in `docs/specs/`, stop and surface the conflict. Do not adapt the spec or the test to match the code.

Use `/wrap` at the end of each session to update SESSION.md, HEURISTICS.log, and PROJECT_PLAN.md consistently.

**One sprint item per session.** After a sprint item is committed: stop, update SESSION.md with the completed item and NEXT_SESSION for the following item, then wait. Do not start the next sprint item. Do not run `/wrap` or end the session — the user does that.

## Per-service context
Load the CLAUDE.md in the service directory before making changes to that service.
