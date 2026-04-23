# src/security/ — Claude Code context

## Purpose
Rate limiting, abuse detection, and malicious input screening. Imported as a library
by the gateway — not a deployed HTTP service. A round-trip before every user request
would add unacceptable latency and create a circular dependency.

## How it is consumed
```python
# In gateway — imported directly, not called over HTTP:
from security.rate_limiter import check_rate_limit
from security.screener import screen_input

# Both raise HTTPException on violation. Let it propagate.
```

The gateway imports this package directly (same monorepo). No Cloud Run deployment for
this module. If other services need rate limiting in future, they import the same package.

## Responsibilities

### Rate limiting
Per-user, per-tenant request quotas. For multi-tenant operation, limits must be enforced
across all gateway instances, not just in-process. Backend: Firestore sliding window counter
keyed by `{tenant_id}:{user_id}`. In-memory fallback acceptable for single-instance dev.

Target: 20 RPM per authenticated user. Burst allowance: 3.

Firestore key: `rate_limits/{tenant_id}/{user_id}`. Read-modify-write under Firestore
transaction (optimistic concurrency). Cache the counter in-process for the token TTL
to reduce Firestore reads on sequential requests from the same user.

Spike before implementation: confirm Firestore latency (~5ms) is acceptable in the gateway
hot path, or evaluate Cloud Memorystore (Redis) as alternative.

### Input screening
Detect prompt injection and jailbreak attempts before the scope gate. Regex + heuristic
blocklist first; LLM-based detection only if precision demands it (LLM screening of every
request is expensive and circular). Never use the same LLM being protected as the screener.

Log every blocked request: `user_id`, `input_hash` (not raw input), `rule_triggered`,
`timestamp`. Never log raw user input.

### What this module does NOT do
- Authentication (that is `src/auth/`)
- Permission checks (that is `src/access/`)
- Output screening — handled by the gateway before SSE emission if needed

## Key invariants
- Rate limit checks run before auth — a blocked request never touches the database
- Blocking is opaque to the caller: raise HTTP 429 with no rule details exposed
- Rate limit state survives gateway restarts — do not use in-memory-only counters in production
- Never log raw user input

## Environment variables (read by gateway, passed to security functions)
```
RATE_LIMIT_RPM          Requests per minute per authenticated user (default: 20)
RATE_LIMIT_RPM_ANON     Requests per minute per IP for unauthenticated (default: 5)
RATE_LIMIT_BURST        Burst allowance above RPM (default: 3)
GCP_PROJECT_ID          For Firestore rate limit storage
```

## Implementation status
Not yet implemented. Stub folder only.
