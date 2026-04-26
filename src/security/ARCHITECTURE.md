# security — Architecture

## Role in the system

Security is a **library imported by the gateway**, not a deployed service. It provides
rate limiting and input abuse detection. A round-trip HTTP call before every user request
would add unacceptable latency and create a circular dependency with the gateway's hot path.

```
gateway  imports  security.rate_limiter
                  security.screener
```

No other service imports this package. If other services need rate limiting in future,
they import the same package — not a new service.

---

## Responsibilities

**Rate limiting:** per-user, per-tenant sliding window counter. Backend: Firestore
keyed by `{tenant_id}:{user_id}`. Target: 20 RPM per authenticated user, burst: 3.

**Input screening:** detect prompt injection and jailbreak attempts before the scope gate.
Regex + heuristic blocklist first. LLM-based detection only if precision demands it —
using the same LLM that would execute the prompt as the screener is circular and expensive.

**What it does NOT do:** authentication, permission checks, output screening.

---

## Call sequence in gateway (planned)

```python
check_rate_limit(user_id, tenant_id)   # raises HTTP 429 on violation
screen_input(query)                     # raises HTTP 400 on blocked input
# ... rest of pipeline
```

Rate limit checks run **before** auth succeeds — a blocked request never touches the
database. Input screening runs after sanitize, before classify.

---

## Guardrails

**⚠ NOT IMPLEMENTED.** This module is a stub folder with a CLAUDE.md. No code exists.
Do not implement until the auth service is implemented — rate limiting requires a stable
`user_id`, which requires validated tokens, which requires the auth service.

**Spike required before implementation:** confirm Firestore latency (~5ms) is acceptable
in the gateway hot path, or evaluate Cloud Memorystore (Redis) as alternative.
Firestore transactions read-modify-write under optimistic concurrency — validate that
concurrent requests from the same user do not produce excessive transaction retries.

**Blocking must be opaque.** Raise HTTP 429 with no rule details exposed. Do not reveal
which rule triggered or how close the caller is to the limit.

**Never log raw user input.** Log `user_id`, `input_hash` (not raw input), `rule_triggered`,
`timestamp`. Raw input in logs is a data leak.

**Rate limit state must survive gateway restarts.** In-memory-only counters in production
are not acceptable — they reset on every deploy and allow burst abuse across rolling
restarts.

**Do not use the protected LLM as the screener.** If LLM-based input screening is added,
it must use a separate, cheaper model. Using the same model creates a circular dependency
(the screener can itself be prompt-injected).

---

## Implementation status

Not implemented. Stub folder only.
Blocked on: auth service (need stable user_id), latency spike (Firestore vs. Redis).
