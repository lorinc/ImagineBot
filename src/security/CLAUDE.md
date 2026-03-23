# src/security/ — Claude Code context

## Purpose
Rate limiting, abuse detection, and malicious input screening. Runs as middleware in the
gateway before any service call. Stateless where possible. Never calls the LLM.

## Responsibilities
- **Rate limiting:** per-user and per-IP request limits. Configurable via env vars.
- **Input screening:** detect prompt injection, jailbreak attempts, and abusive inputs.
  Block before the request reaches the knowledge or LLM layer.
- **Load protection:** reject requests when system load exceeds thresholds.

## What this service does NOT do
- It does not authenticate users (that's auth service)
- It does not check data source permissions (that's access service)
- It does not log conversation content (that's the gateway's job)

## Implementation pattern
Security checks are implemented as FastAPI middleware or as dependency-injected functions,
called explicitly in the gateway. The gateway imports from this service as a library
(same monorepo, direct import) rather than via HTTP — security checks must be fast.

```python
# In gateway middleware:
from security.rate_limiter import check_rate_limit
from security.screener import screen_input

# Both raise HTTPException on violation. Gateway catches nothing — let it propagate.
```

## Rate limiting design
Store rate limit counters in Firestore (simple, no extra infra) or in-memory with
periodic Firestore sync. Decision TBD — document here when made.

Key: `rate_limits/{user_id}` or `rate_limits/{ip}` depending on auth state.

## Input screening
Initial implementation: regex + heuristic blocklist. No LLM for screening (circular).
Log every blocked request with: user_id, input_hash (not raw input), rule_triggered, timestamp.
Never log raw user input in security events.

## Environment variables
```
RATE_LIMIT_RPM          Requests per minute per authenticated user (default: 20)
RATE_LIMIT_RPM_ANON     Requests per minute per IP for unauthenticated (default: 5)
RATE_LIMIT_BURST        Burst allowance (default: 3)
SECURITY_LOG_COLLECTION Firestore collection for security events (default: security_events)
```

## Key invariants
- Security checks run before auth. A blocked IP never touches the database.
- Blocking is silent from the user's perspective: return 429 with no details on why.
- Rate limit state survives service restarts. Do not use in-memory-only counters in production.

## Known issues
[Populate as work proceeds]
