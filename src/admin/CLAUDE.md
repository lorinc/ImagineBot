# src/admin/ — Claude Code context

## Purpose
Management plane for multi-tenant operation. Handles everything that changes the
system's configuration: tenant registration, user management, source (corpus)
connection, and corpus status visibility. None of this belongs in the gateway
(request path) or in auth/access (which only answer read queries).

## Why this service is separate
The gateway orchestrates user queries. Auth issues and validates tokens. Access answers
"what can this user see?" None of those services manages the configuration that makes
the system work for a new tenant. Admin owns that configuration lifecycle.

## Responsibilities

### Tenant management
- Provision a new tenant (school/organization): create tenant record, set display name,
  provision Firestore namespace, create service accounts
- Suspend or deprovision a tenant

### User management
- Invite a user to a tenant (admin-initiated, not self-serve)
- Assign roles: `admin` (can manage users and sources) vs. `member` (can query only)
- Remove a user from a tenant
- List users within a tenant

### Source (corpus) management
- Connect a Google Drive folder as a data source for a tenant
- Trigger an ingestion run for a source (calls `src/ingestion/`)
- Report corpus status: last ingested, document count, staleness warning if overdue
- Grant or revoke a user's access to a specific source (calls `src/access/`)

### Self-service onboarding
The long-term goal: a new school admin can sign up, connect their Drive folder, invite
their users, and have a working chatbot without any engineering involvement. This service
is the backend for that flow.

## Interface contract (placeholder — design TBD)
```
POST /tenants
  Request:  { "name": str, "admin_email": str }
  Response: { "tenant_id": str }

GET /tenants/{tenant_id}/users
  Response: { "users": [{ "user_id": str, "email": str, "role": str }] }

POST /tenants/{tenant_id}/users
  Request:  { "email": str, "role": "admin" | "member" }
  Response: { "invited": bool }

DELETE /tenants/{tenant_id}/users/{user_id}
  Response: { "removed": bool }

POST /tenants/{tenant_id}/sources
  Request:  { "drive_folder_id": str, "source_id": str }
  Response: { "connected": bool }

POST /tenants/{tenant_id}/sources/{source_id}/ingest
  Response: { "run_id": str }

GET /tenants/{tenant_id}/sources/{source_id}/status
  Response: { "last_ingested": str|null, "doc_count": int, "stale": bool }
```

All endpoints require admin-level auth. The gateway does not route to admin — admin
has its own ingress, separate from the user-facing gateway.

## Key invariants
- Admin endpoints are never exposed to end users — separate Cloud Run service, separate ingress
- All state changes go through this service; no other service writes tenant/user/source config
- Ingestion is triggered by this service, not by the ingestion service itself (push, not poll)
- Every action is audit-logged: who did what to which tenant, when

## Implementation status
Not yet implemented. No spike written. Design blocked on:
- Auth spike (`src/auth/`) — admin auth is a superset of user auth
- Access spike (`src/access/`) — source grants are access service writes
- Ingestion deployed-service design — admin triggers ingestion; ingestion must be callable
