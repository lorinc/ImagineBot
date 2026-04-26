# docs/specs — Acceptance criteria and cross-cutting principles

## Ownership rule

**Human-authored. Agent reads, never modifies without explicit approval.**

These files are the authoritative ground truth for intended behavior. When the agent
finds a conflict between a spec here and what the code does, it must surface the
conflict and ask — not silently adapt the test or the spec to match the implementation.

## Contents

| File | Scope |
|------|-------|
| `PRINCIPLES.md` | Invariants that apply across all services |
| `<module>.md` | Per-module acceptance criteria (one file per service/boundary) |

## Format for per-module specs

```
# Spec: <module name>
# Status: STUB | DRAFT | APPROVED
# Last reviewed: YYYY-MM-DD

## Acceptance criteria

AC-<id>: <one-line summary>
  Given: <precondition>
  When:  <action>
  Then:  <observable outcome>
  Test:  <how this is verified — file or "manual">
```

Status meanings:
- `STUB` — placeholder, not yet used for implementation decisions
- `DRAFT` — written, not yet reviewed with human
- `APPROVED` — reviewed and confirmed; agent must not change without approval

## What does NOT belong here

- Implementation details (those live in `src/<service>/CLAUDE.md`)
- Infrastructure topology (that lives in `docs/ARCHITECTURE.md`)
- Test commands (those live in `tests/CLAUDE.md`)
- Sprint priorities (those live in `docs/PROJECT_PLAN.md`)
