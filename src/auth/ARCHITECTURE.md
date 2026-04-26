# auth — Architecture

## Role in the system

The auth service issues and validates tokens for all users across all tenants. The
gateway's auth middleware calls it on every request. Users never call it directly.

```
Browser  →  channel_web  →  auth service  (token validation)
                         →  gateway  (with validated user context)
```

**Current state:** auth is not implemented as a service. channel_web handles auth
inline: Google Sign-In frontend + `ALLOWED_EMAILS` secret validation. This is a
single-tenant interim — adding a user requires a GCP secret update and service restart.
This service is the multi-tenant replacement for that inline flow.

---

## Planned interface contract

```
POST /token      Issue a token (credentials shape TBD by spike).
POST /validate   Validate a token; return user_id + tenant context.
POST /revoke     Invalidate a token before TTL.
```

The gateway's auth middleware calls `/validate` on every request. This must be fast.
In-process caching of valid tokens for their TTL is expected and required.

---

## Design constraints (invariants regardless of implementation)

**Token secrets are never class variables, module constants, or hardcoded.** A secret
generated as a class variable regenerates on every process restart, silently invalidating
all active sessions. Secrets come from environment variables or Secret Manager only.

**Auth service is the ONLY place tokens are created or validated.** The gateway
middleware calls the auth service. It does not validate tokens itself. channel_web's
inline validation (`verify_oauth2_token`) is the interim exception — when the auth
service is built, this inline code is deleted.

**Invite flow, not self-registration.** Users do not create their own accounts.
Tenant admins invite users. This is a hard requirement for school deployments where
the user population must be explicitly controlled.

**Runtime revocation must work.** Revoking a user takes effect on the next request,
not after the token TTL expires. This rules out pure stateless JWT without a revocation
list.

**Failed auth attempts are logged.** Every failed validation is logged with: timestamp,
IP, reason. Raw credentials are never logged.

---

## Guardrails

**⚠ SPIKE REQUIRED BEFORE IMPLEMENTATION.** Do not write any auth code until
`docs/spikes/auth.md` exists and contains a decision on:
- JWT (self-contained) vs. opaque tokens (validated against Firestore/Redis)
- Session length and refresh token strategy
- Whether WhatsApp channel uses the same mechanism (phone identity ≠ Google identity)
- Token storage in browser (HttpOnly cookie vs. localStorage — security implications)

**Do not copy the channel_web inline auth pattern.** The `verify_oauth2_token` approach
in channel_web is a single-tenant interim. It cannot scale to multi-tenant because it
has no concept of tenant context and uses a static email list.

**Token secrets in Secret Manager, not env vars in code.** The pattern is:
`Secret Manager → Secret Manager volume mount → read at startup`. Never
`os.environ.get("TOKEN_SECRET", "hardcoded_default")`.

---

## Implementation status

Not implemented. Spike pending. Design blocked on: multi-tenant requirements clarity,
WhatsApp channel identity model, token storage security model.
