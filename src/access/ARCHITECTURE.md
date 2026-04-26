# access — Architecture

## Role in the system

The access service answers one question: **what sources is this user permitted to query?**
The gateway calls it after auth validates a token, before any knowledge service call.
The response determines the `group_ids` passed to the knowledge service.

```
gateway  →  access  →  Firestore (user → source grants)
        ↓
    group_ids  →  knowledge service
```

The access service only answers read queries. It does not manage grants. Grant management
(connecting sources to tenants, assigning users) is the admin service's responsibility.

---

## Planned interface contract

```
GET /access/{user_id}
  Response: { "user_id": str, "permitted_source_ids": list[str] }

POST /access/{user_id}/sources       (admin-only)
DELETE /access/{user_id}/sources/{source_id}  (admin-only)
```

An **empty `permitted_source_ids` list is a valid response** — the user exists but has
no sources. The gateway must handle this as a useful "you don't have access to any
sources" message, not a server error.

---

## Data model principles

Access grants are stored in **Firestore, not in JWT claims**. Claims go stale — a
revoked grant would remain valid until token expiry. Firestore grants take effect on
the next request.

The access service does not validate tokens. It trusts the `user_id` passed by the
gateway, which has already called the auth service. The access service is never called
directly by the browser.

---

## Connection to the knowledge service

The gateway passes `permitted_source_ids` as `group_ids` to `POST /topics` and
`POST /search`. The knowledge service currently ignores `group_ids` (stub). When this
service is implemented, the knowledge service must enforce the filter — it cannot trust
that the gateway will always pass correct values.

The enforcement model is: **knowledge service enforces, access service supplies, gateway
passes through**. No single component is solely responsible.

---

## Guardrails

**⚠ SPIKE REQUIRED BEFORE IMPLEMENTATION.** Do not write any access control code until
`docs/spikes/access.md` exists and contains a decision on:
- Firestore data model: user document with source list vs. join collection
- Inheritance/groups: can users belong to a group that has access to multiple sources?
- What happens when permitted_source_ids is empty?
- How does the ingestion service register new sources for granting?

**Do not implement post-filter access control in the knowledge service.** Post-filtering
(retrieve all, then filter by source_id) silently degrades recall — if the top-k
candidates are all from non-permitted sources, the caller receives fewer results with no
indication why. Access control must be a pre-filter on the retrieval stage. See
HEURISTICS.log [2026-03-21 00:00] for the original analysis.

**Empty permitted_source_ids is not an error.** The gateway must handle it gracefully
with a user-facing message, not a 500.

**Access changes take effect on the next request.** Do not cache access grants in the
gateway without a TTL and a revocation signal. Default: no cache, live Firestore lookup
per request. Document the tradeoff explicitly if caching is added.

---

## Implementation status

Not implemented. Spike pending. Design blocked on auth service (need stable `user_id`).
