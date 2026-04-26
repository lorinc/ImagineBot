# ImagineBot

A multi-service Q&A system for school communities. Documents are ingested and kept
current; users ask questions through a web UI and receive cited answers drawn from
those documents. Access is controlled per user per data source.

## What runs beneath the surface

This project is built with Claude Code as the primary development agent. Managing that
well requires infrastructure that goes beyond the code itself: the agent needs to know
what decisions were made and why, what has failed before and how to avoid repeating it,
and what invariants cut across service boundaries. The operational files below are that
infrastructure.

### `.claude/HEURISTICS.log` — institutional memory

An append-only structured log of every significant failure mode discovered during
development. Each entry records: category, affected service, symptom, root cause, and
— most importantly — a `PREVENTED_BY` field that encodes a structural change, not just
advice to "be careful." The log is read at the start of every session. It outlives every
conversation and is the primary mechanism for not making the same mistake twice.

Example categories recorded so far: contract violations between services, silent data
pipeline gaps (step wrote to the wrong directory for weeks), Cloud Run revision
accumulation, async/sync boundary bugs, SSE framing issues, and Firestore write
semantics.

### `docs/ARCHITECTURE.md` — cross-cutting invariants and guardrails

Not an overview document — a set of enforced constraints that no single service owns.
Topology invariants (`channel_web` never calls `knowledge` directly), authentication
flow separation (user tokens never leave `channel_web`), access control rules (no
partial enforcement, pre-filter only), SSE event protocol (all three services change
atomically), secret mount pattern, test isolation requirements, and coding agent
guardrails.

The document is read at every session start. Any change to a cross-service contract
triggers an update here.

### `docs/PROJECT_PLAN.md` + `docs/SAAS_MATURITY_FRAMEWORK.md`

Sprint breakdowns are anchored to a maturity framework that maps every operational
dimension (auth, access, ingestion, observability, tenancy, etc.) to four levels.
Before planning work, the framework identifies which dimensions are at L0 and block
the next milestone. This prevents building features on top of missing foundations.

### `src/<service>/CLAUDE.md` and `src/<service>/TODO.md`

Every service has a `CLAUDE.md` loaded before any change to that service: current
architecture, known gaps, invariants specific to that service. `TODO.md` is
append-only — resolved items are struck through, never deleted. Together they provide
continuity across sessions without requiring the agent to re-derive state from git history.

### `.claude/SESSION.md`

Overwritten at the start of each session via `/wrap`. Records what was completed, what
was left open, and what comes next. Not committed — it's working state, not history.

---

## Development approach

**Spikes before production.** The retrieval architecture was validated through two poc
phases (`poc1_single_doc`, `openkb_eval`) before any code was promoted to `src/`. The
poc directory was deleted once the architecture graduated. What remains in `src/` is
the production path; what informed the design is in the git history and `HEURISTICS.log`.

**Conservative dependencies.** Before adding any package: state what problem it solves,
state what three lines of Python would do instead, get explicit approval. The frontend
is served without a build step.

**Production deploy is always a manual trigger.** No CI pipeline, no merge hook, no
script may deploy to production without an explicit human action. Every service has a
`deploy.sh` that builds, pushes, and deploys locally.

**Architecture violations are named, not assumed.** Known gaps in the current
implementation (inline auth in `channel_web`, `group_ids=null`, synchronous I/O in
async paths) are documented with their exact location and the condition under which
they become blocking. Nothing is swept under the rug.

---

## Stack

Python 3.12 · FastAPI · Firestore · Vertex AI (Gemini 2.5 Flash) · GCP Cloud Run · GCS

## Services

```
channel_web   Web UI. Thin client — formats requests, renders responses. No business logic.
gateway       Single entry point for all channels. Handles routing, session, tracing, feedback.
knowledge     Retrieval layer. PageIndex + Gemini: given a query, returns cited answer.
ingestion     Document intake. Converts Drive corpus → Markdown → PageIndex → GCS.
access        User-to-source mapping. Returns the set of sources a user may query. [planned]
auth          Token issuance and validation. [planned]
security      Rate limiting and input screening. [planned]
admin         Tenant + corpus management. [planned]
```

## Request flow

```
User → channel_web → gateway → knowledge → Vertex AI → response
                   ↘ Firestore (traces + feedback, fire-and-forget)
```

## Development

See `CLAUDE.md` for session protocol and service-level context.
See `.claude/HEURISTICS.log` for recorded failure modes and root causes.
See `docs/ARCHITECTURE.md` for cross-cutting invariants and guardrails.
See `docs/PROJECT_PLAN.md` for sprint status.
