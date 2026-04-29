# Cross-cutting principles
# Status: STUB
# Last reviewed: —

Invariants that apply across all services. Each principle has an ID so it can be
referenced from per-module specs and test assertions.

## Observability

P-OBS-01: Every user-facing request must produce a Firestore trace document.
P-OBS-02: Every trace must contain: trace_id, session_id, timestamp, input, output, spans.
P-OBS-03: output must contain: answer (str), facts (list, may be empty).

## API contracts

P-API-01: Every response to a client must include trace_id.
P-API-02: SSE streams must terminate with exactly one `event: answer` or one `event: error` — never both, never neither.
P-API-03: No endpoint may return HTTP 500 without a structured JSON error body.

## Security

P-SEC-01: All user-facing endpoints require a valid Google ID token.
P-SEC-02: The allowed-users list is the sole access gate; no role or group logic yet.

## Data integrity

P-DATA-01: Pipeline intermediary files are never deleted; trace-back requires them.
P-DATA-02: A new top-level .py file in any service directory requires a corresponding COPY line in that service's Dockerfile.

## Agent behaviour

P-AGENT-01: When two errors occur in a row, stop. Do not attempt a third fix.
Step back and ask: is this error caused by a gap in the design or underspecification?
If you find yourself guessing at a solution, assume the answer is yes.
Call out the specific gap explicitly and ask the user to resolve it before continuing.
Filling design gaps with assumptions is the most common cause of compounding errors.

P-AGENT-02: The correct resolution to a design gap is a principled, wide, research-based
analysis and plan — not a quick local fix. Do not perform that research yourself without
explicit instruction. State the gap, state that a deeper analysis is needed, and wait.
The user will direct the research when ready.
