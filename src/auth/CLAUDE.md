# src/auth/ — Claude Code context

## Purpose
Authentication. Issues and validates tokens. Called by the gateway's auth middleware.
Users never call this directly.

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
