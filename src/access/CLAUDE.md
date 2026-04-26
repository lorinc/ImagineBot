# src/access/ — Claude Code context

## Read first
Read `ARCHITECTURE.md` in this directory before making any changes to this service.

## Purpose
User-to-data-source mapping. Given a user ID, returns the set of source IDs that user
is permitted to query. Called by the gateway's access middleware after auth passes.

## Multi-tenant context
In a multi-tenant system, every user belongs to a tenant and can only see that tenant's
corpus. `permitted_source_ids` is the mechanism: the knowledge service accepts `group_ids`
(currently stubbed as null) and filters its index to only those sources. Access control
is enforced at the gateway — the knowledge service trusts whatever group_ids it receives.

The admin service (`src/admin/`) is responsible for managing access grants:
connecting sources to tenants and assigning users to tenants. The access service
answers read queries only; it does not manage grants directly.

## ⚠️ SPIKE REQUIRED BEFORE IMPLEMENTATION
Access control design is not yet decided. Do not implement until `docs/spikes/access.md`
exists and contains a decision.

Spike questions to answer:
- Data model: Firestore document per user with list of permitted source IDs?
  Or a join collection (user_id, source_id) for easier querying?
- Who manages access grants? Admin UI? Manual Firestore writes? API?
- Inheritance / groups: can users belong to a group that has access to sources?
- What happens when a user has no permitted sources? Error or empty response?
- Is "access to a source" binary, or are there permission levels (read, export, etc.)?
- How does the ingestion service register new sources so they can be granted?

## Interface contract (stable regardless of implementation)
```
GET /access/{user_id}
  Response: { "user_id": str, "permitted_source_ids": list[str] }
  Empty list means user exists but has no access — not an error.
  404 means user_id not recognised.

POST /access/{user_id}/sources
  Request:  { "source_id": str }
  Response: { "granted": bool }
  (Admin endpoint — requires elevated auth)

DELETE /access/{user_id}/sources/{source_id}
  Response: { "revoked": bool }
  (Admin endpoint)
```

## Key invariants
- An empty permitted_source_ids list is a valid response. The gateway must handle it:
  return a helpful "you don't have access to any sources" message, not a server error.
- Access grants are stored in Firestore, not in JWT claims. Claims go stale.
- The access service does not call the auth service. It trusts the user_id passed by
  the gateway (which has already validated the token).
- Access changes take effect on the next request. No cache invalidation needed
  if we don't cache (default). Document the tradeoff if caching is added later.

## Environment variables
```
GCP_PROJECT_ID
ACCESS_COLLECTION    Firestore collection for access grants (default: user_access)
```

## Known issues
- Design: SPIKE PENDING — see docs/spikes/access.md (not yet written)
