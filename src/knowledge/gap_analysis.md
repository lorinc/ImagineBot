# Gap Analysis — UX Framework vs. Current Implementation

Source: `docs/design/Chatbot_UX_framework.md`
Scope: gateway pipeline (`src/gateway/`) + knowledge service interface (`src/knowledge/`)
Date: 2026-04-23

---

## Summary

The UX framework defines five decision gates every user turn must pass through before
generating prose. The current pipeline correctly implements Gate 1 (scope) and has a
partial implementation of Gate 2 (ambiguity). Gates 3, 4, and 5 are absent or incomplete.
Several gaps require changes to the knowledge service interface, not only the gateway.

---

## Gate 1 — Scope classification ✅ Implemented

`classify()` returns `in_scope`; out-of-scope queries short-circuit to `OUT_OF_SCOPE_REPLY`
before any knowledge call. The framework's requirement — state the boundary, do not
partially answer from model memory — is met.

---

## Gate 2 — Ambiguity classification ⚠️ Partial

`classify()` returns `specific_enough`; vague queries return `ORIENTATION_RESPONSE` (a
static capability listing). The framework requires a targeted disambiguating question that
asks for exactly one missing routing variable. For a query like "What happens to my child?"
a capability listing is not the same as "Rules about what — attendance, behaviour, fees?"
This is a prompt/response design gap, not an architecture gap; no knowledge service change
is required.

---

## Gate 3 — Evidence classification ❌ Not implemented

**Framework requirement:** Distinguish "topic in scope, evidence missing" from scope miss
and ambiguity. These are three different user experiences; collapsing them to one generic
response makes the bot feel erratic. When retrieved evidence is weak or absent, abstain
rather than synthesise.

**Current behaviour:** When `POST /search` returns `facts: []`, the gateway emits the
synthesis answer unchanged. The user sees a confident-sounding response with no indication
that no supporting documents were found.

**Knowledge service role:** The gateway cannot gate on evidence quality if the knowledge
service does not signal it. `POST /search` must expose either:
- a `has_evidence: bool` field (simplest — false when selected_nodes is empty), or
- a `confidence: "high" | "low" | "none"` enum, or
- `selected_nodes` directly (already needed for BigQuery trace — see TODO.md)

With any of these, the gateway can route to a distinct "in scope but unsupported" response
instead of forwarding a zero-fact synthesis answer.

**See:** `TODO.md` §Evidence signal on POST /search

---

## Gate 4 — Single-hop vs. multi-hop ⚠️ Partial

**Breadth detection** (overview mode) handles the "query spans many topics" case via
`GET /topics` + sibling consolidation. This is the correct approach for broad queries.

**Multi-question decomposition** is not implemented. A message like "My son lost his hat,
who can I call?" contains two distinct sub-questions; the current pipeline retrieves on the
combined message and silently drops whichever sub-question the retrieval does not select.
This is a gateway-side gap.

**Cross-reference follow-up** is not implemented. When synthesis returns "see other policy /
see separate section", no second retrieval pass occurs. Detecting cross-reference phrases
in the answer and issuing a follow-up `POST /search` call would require no knowledge service
changes — the gateway would chain the calls itself.

**Knowledge service role for multi-hop:** Expose `selected_nodes` in `SearchResponse` so
the gateway can detect whether a cross-reference was in the selected set and whether a
second call retrieved new nodes. Without this, the gateway cannot tell whether a follow-up
retrieval actually added anything.

**See:** `TODO.md` §selected_nodes in SearchResponse (prerequisite)

---

## Gate 5 — Recover / abstain / hand off ❌ Not implemented

**Framework requirement:** Retries capped, failure preserves session state for resume or
human handoff. Pass conversation history and resolved variables to the handoff target.

**Current behaviour:** Any pipeline error yields an `error` SSE event and stops. No state
is preserved. No human handoff path exists. In-memory sessions never expire (memory leak).

**Knowledge service role:** None directly. Session management and handoff are gateway and
channel responsibilities.

---

## Retrieval miss vs. documentation gap ❌ Not distinguished

The framework explicitly separates "retrieval probably failed" (fixable by query
reformulation or relaxed retrieval settings) from "the information is genuinely not in the
corpus" (a corpus gap). Both currently produce the same response.

**Knowledge service role:** The distinction requires the knowledge service to signal
retrieval confidence or node coverage. A response with `selected_nodes: []` is a strong
signal of retrieval failure; a response with nodes but an answer that starts with "I don't
have information" is a synthesis abstention. The gateway can handle these differently only
if `selected_nodes` is exposed.

---

## Evaluation ❌ Not instrumented

The framework recommends separate scoring on groundedness, relevance, completeness,
ambiguity handling, and handoff quality. Nothing is currently instrumented. The BigQuery
trace (gateway TODO priority #1) is the prerequisite for all evaluation work.

**Knowledge service role:** `POST /search` must include `selected_nodes` in its response
so the trace can log which chunks were used. See gateway `TODO.md` §BigQuery trace.

---

## Gaps requiring knowledge service changes

| Gap | Required change | Gateway change |
|-----|----------------|----------------|
| Gate 3 — evidence signal | Add `has_evidence` / `confidence` / `selected_nodes` to `SearchResponse` | Gate on evidence quality before emitting answer |
| Gate 4 — multi-hop visibility | Expose `selected_nodes` | Cross-reference follow-up loop |
| Retrieval miss vs. doc gap | Expose `selected_nodes` (empty = retrieval miss) | Route to distinct "unsupported" response |
| Evaluation / BigQuery trace | Expose `selected_nodes` | Log full trace to BigQuery |

All four gaps share the same root prerequisite: **expose `selected_nodes` in `SearchResponse`**.
The gateway already reads `synthesis.selected_nodes` internally in `_facts_from_result` but
does not return it to callers. Adding it to `SearchResponse` unblocks Gate 3, Gate 4
visibility, and the full BigQuery trace.
