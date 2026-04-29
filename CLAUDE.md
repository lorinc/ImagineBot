# ImagineBot — Claude Code root context

## Read first
At the start of every session, before anything else:
1. Read `.claude/SESSION.md`
2. Read `.claude/SPRINT.md`
3. Run `tail -40 .claude/HEURISTICS.log`
4. Read `docs/ARCHITECTURE.md`
5. Read `docs/specs/PRINCIPLES.md`
6. Output a session brief — 3–5 sentences max: what was done last session, what comes next. No headers, no bullet trees, no essay.

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

Use `/wrap` at the end of each session to update all operational files consistently (see wrap checklist below).

## Sprint item lifecycle

Each sprint item runs across two sessions. Do not merge or skip phases without explicit user instruction.

### Session 1 — Plan + Implement

1. Read the sprint item (SPRINT.md + relevant TODO.md entry).
2. Draft a plan: which files change, what the logic is, how it will be tested.
3. **Ask for approval. Do not proceed until the user explicitly approves.**
   Revise and re-ask if feedback is given. Repeat until settled.
4. Implement the change and write tests. Run tests to confirm they pass.
5. Summarize: what changed, what tests cover, what the observable behavior is.
6. **Ask for approval. Do not commit until approved.**
   Revise, re-run tests, re-summarize, re-ask if feedback is given.
7. Once approved: commit, then run `/wrap`.
   Set SESSION.md NEXT_SESSION = deploy + UAT for this service.
8. Tell the user to run `/clear`.

_If planning is large enough to pollute context, the user may ask for implementation in a fresh session. Otherwise plan and implement in the same session._

### Session 2 — Deploy + UAT

1. Deploy the changed service (`./deploy.sh`). If deploy fails, diagnose and fix autonomously.
2. Run `pytest tests/<service>/` and confirm pass.
3. Update SESSION.md and SPRINT.md to reflect deploy complete.
4. Determine whether the change touches a user-facing scenario:
   - **If yes:** name the exact scenario and ask the user to test it on the frontend. Wait for confirmation.
   - **If no:** state this explicitly, confirm smoke tests passed, and ask the user to confirm no UAT is needed before wrapping.
5. On pass (UAT confirmed or UAT skipped with user confirmation):
   run `/wrap`, set SESSION.md NEXT_SESSION for the next sprint item's Plan phase.
   Tell the user to run `/clear`.
6. On UAT fail: add a bug item to the top of SPRINT.md Active,
   update SESSION.md accordingly. Tell the user to run `/clear`.

## Per-service context
Load the CLAUDE.md in the service directory before making changes to that service.
