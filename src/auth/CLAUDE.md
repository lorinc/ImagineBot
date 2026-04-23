# src/auth/ — Claude Code context

## Purpose
Authentication. Issues and validates tokens for all users across all tenants.
Called by the gateway's auth middleware on every request. Users never call this directly.

## Current state (Sprint 1)
Auth is not yet implemented as a service. Channel_web handles auth inline using
Google Sign-In + `ALLOWED_EMAILS` (a Secret Manager secret). This is a single-tenant
interim: changing the allowed user list requires a GCP secret update and redeploy.
This service is the multi-tenant replacement.

## Multi-tenant requirements
The auth service must support:
- An org/user/role hierarchy: tenant → users → roles (admin, member)
- Invite flows: admins invite users; users do not self-register
- Token issuance with tenant context embedded (so the gateway can route correctly)
- Runtime revocation: removing a user takes effect on the next request, not after token TTL
- Multiple channels: web (Google OAuth), future WhatsApp (phone identity — different mechanism)

## ⚠️ SPIKE REQUIRED BEFORE IMPLEMENTATION
Auth design is not yet decided. Do not implement until `docs/spikes/auth.md` exists
and contains a decision.

Spike questions to answer:
- JWT (self-contained) vs opaque tokens (validated against Firestore/Redis)?
- Session length, refresh token strategy?
- Will there be social login (Google, etc.) or username/password only?
- Does WhatsApp channel use the same auth mechanism? (phone number identity is different)
- How does the web UI manage the token? (HttpOnly cookie vs localStorage — security implications)

## Interface contract (stable regardless of implementation)
```
POST /token
  Request:  { "credentials": ... }   (shape TBD by auth mechanism)
  Response: { "token": str, "expires_at": int }

POST /validate
  Request:  { "token": str }
  Response: { "valid": bool, "user_id": str | null, "reason": str | null }

POST /revoke
  Request:  { "token": str }
  Response: { "revoked": bool }
```

The gateway's auth_middleware calls `/validate` on every request.
This must be fast. Consider caching valid tokens in-process for their TTL.

## Key invariants (regardless of implementation chosen)
- Token secrets are never hardcoded, never class variables, never module constants.
  They must come from environment variables or GCP Secret Manager.
  (A secret generated as a class variable regenerates on every process restart —
  this silently invalidates all sessions. This is a known failure mode.)
- Auth service is the ONLY place tokens are created or validated.
  Gateway middleware calls auth service. It does not validate tokens itself.
- Failed auth attempts are logged with: timestamp, ip, reason. Never log credentials.

## Environment variables (partial — expand post-spike)
```
TOKEN_SECRET          Secret for signing tokens (from Secret Manager in prod)
TOKEN_TTL_SECONDS     Token lifetime (default: 3600)
GCP_PROJECT_ID
```

## Known issues
- Design: SPIKE PENDING — see docs/spikes/auth.md (not yet written)
