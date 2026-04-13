# docs/ — Claude Code context

## Documentation philosophy
Each fact lives in exactly one document. No narratives. No duplication.
When delivering something: update DELIVERY.md and COMPONENTS.md. That's it.
Do not create new documentation files without explicit discussion.

## Document ownership map
| File | Owns | Does NOT own |
|------|------|--------------|
| FUNCTIONAL_SPEC.md | Product behaviour, user flows, validation rules | Implementation, schemas |
| ARCHITECTURE.md | Services, data flow, infrastructure, why choices were made | Schemas, API specs |
| DATA_MODEL.md | Firestore collections, fields, types, relationships | Business logic, endpoints |
| COMPONENTS.md | Inventory: services, routes, models + current status | Implementation details |
| TEST_DESIGN.md | Test strategy, coverage philosophy | Commands, setup |
| TEST_EXECUTION.md | Exact commands, environment setup, troubleshooting | Strategy |
| PROJECT_PLAN.md | Sprint breakdown, status, priorities, spike queue | Implementation details |
| DELIVERY.md | Dense log: features, tests, deploys, breaking changes | Narrative, explanation |
| DEPLOYMENT.md | Deploy commands, Cloud Run config, rollback procedure | Architecture rationale |
| spikes/ | One file per spike — options, tradeoffs, decision | Implementation |

## DELIVERY.md format
Dense. Facts only. No prose.

Table row: `| Sprint N.x | Feature | tests: pass/total | ✅/🚧 | Note |`

Per-sprint section: features delivered, API endpoints added, files created,
dependencies added, breaking changes, deploy history.

Wrong: "We decided to use X because it offers Y benefits."
Right: "X v2.1.0 — added for Z — deployed 2024-01-15"

## Spike document format
File: `docs/spikes/[topic].md`

```markdown
# Spike: [topic]
Date: [YYYY-MM-DD]
Status: COMPLETE | IN_PROGRESS

## Question
[One sentence: what decision does this spike resolve?]

## Options considered
### Option A: [name]
- How it works: ...
- Pros: ...
- Cons: ...
- Estimated complexity: ...

### Option B: [name]
...

## Dead ends
[What was tried and ruled out, and why. This section feeds .claude/HEURISTICS.log.]

## Decision
[Which option, and why. Be direct.]

## Implementation notes
[Anything the implementer needs to know that isn't obvious from the decision.]
```

## Update triggers
| What happened | Update these docs |
|---------------|-------------------|
| Feature delivered | DELIVERY.md + COMPONENTS.md |
| Schema changed | DATA_MODEL.md |
| Infrastructure changed | ARCHITECTURE.md and/or DEPLOYMENT.md |
| Spec changed | FUNCTIONAL_SPEC.md |
| Spike completed | spikes/[topic].md → update relevant service CLAUDE.md |
| Sprint boundary | PROJECT_PLAN.md |

## Current state
[Update at end of every session]
- Last delivery: Sprint 1 Phase 1.3 — channel_web deployed (2026-03-21)
- Spikes pending: auth, access
- Spikes complete: retrieval (Graphiti + Neo4j), local validation (validate.py passed),
  css_framework (decision: hand-written CSS — no framework, no build step, no CDN)
