# admin — Architecture

## Role in the system

The admin service is the **management plane** for multi-tenant operation. It owns every
action that changes system configuration: tenant provisioning, user management, corpus
connection, and ingestion triggers. None of this belongs in the gateway (request path)
or in auth/access (which only answer queries).

```
School admin (browser or CLI)  →  admin service  →  auth service (elevated token)
                                               →  access service (grant writes)
                                               →  ingestion (trigger runs)
                                               →  Firestore (tenant/user/source records)
```

The user-facing gateway does not route to admin. Admin has its own ingress, separate
from the public chatbot. End users never reach this service.

---

## Responsibilities

**Tenant management:** provision new schools, set display names, create Firestore
namespaces, suspend or deprovision tenants.

**User management:** invite users (admin-initiated, not self-serve), assign roles
(`admin` vs. `member`), remove users, list users per tenant.

**Source (corpus) management:** connect a Google Drive folder as a data source, trigger
ingestion runs, report corpus status (last ingested, document count, staleness warning).

**Access grant writes:** grant or revoke a user's access to a source. This is the write
side of `src/access/` — the access service handles reads.

**Long-term goal:** a new school admin can sign up, connect their Drive folder, invite
their users, and have a working chatbot without any engineering involvement.

---

## Boundaries — what admin owns vs. what it does NOT own

| Admin owns | Admin does NOT own |
|---|---|
| Tenant CRUD | Query routing (gateway) |
| User invite and role assignment | Token validation (auth service) |
| Source connection and ingestion trigger | Access grant reads (access service) |
| Corpus status reporting | The ingestion pipeline itself |
| Audit log of all config changes | User-facing chat interface |

---

## Guardrails

**⚠ NO SPIKE WRITTEN. NOT STARTED.** Do not implement any part of this service until:
1. `docs/spikes/auth.md` is complete (admin auth is a superset of user auth)
2. `docs/spikes/access.md` is complete (source grants are access service writes)
3. A decision is made on whether ingestion is triggered by admin via HTTP or by
   writing to a Firestore queue that the ingestion service polls

**Admin endpoints are never exposed to end users.** Separate Cloud Run service,
separate ingress rule, admin-level auth token required on every request. The gateway's
`--allow-unauthenticated` pattern used by channel_web is explicitly prohibited here.

**All state changes must be audit-logged.** Who did what to which tenant, when.
This is a hard requirement for a school deployment handling sensitive configuration.
The audit log is append-only — no record is ever updated or deleted.

**Ingestion is push, not poll.** Admin triggers ingestion; the ingestion service does
not detect corpus changes on its own. The trigger mechanism (HTTP call, Pub/Sub, Firestore
trigger) is TBD by the design spike.

**All tenant/user/source configuration flows through this service.** No other service
writes these records directly. If a change needs to happen, it goes through admin.
Direct Firestore writes to these collections outside of admin are an architecture violation.

---

## Implementation status

Not implemented. No spike written.
Blocked on: auth spike, access spike, ingestion service deployment design.
