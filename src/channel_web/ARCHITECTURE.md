# channel_web — Architecture

## Role in the system

channel_web is a **thin authenticated proxy**. It has three jobs: serve the HTML shell,
validate the user's Google identity token, and stream the gateway's SSE response
back to the browser. It contains no pipeline logic, no session management, and no
knowledge of the retrieval system.

```
Browser  →  channel_web  →  gateway  →  knowledge
                         ←  (SSE passthrough)
```

Auth is handled entirely in this service. The gateway does not validate user identity —
it trusts any caller with a Cloud Run identity token. channel_web is the auth gateway
between untrusted browsers and the trusted internal pipeline.

---

## Auth model

**User authentication: Google Sign-In (frontend) + ID token validation (backend)**

1. Browser loads the page, shows Google Sign-In overlay.
2. User completes OAuth → browser receives a Google ID token.
3. Browser sends `Authorization: Bearer <google-id-token>` on every `/chat` and `/feedback` request.
4. `_get_current_user` validates the token signature and checks `email` against `ALLOWED_EMAILS`.
5. If valid, the request proceeds. Otherwise: 401 (bad token) or 403 (email not listed).

**Service-to-service authentication: Cloud Run identity tokens**

channel_web calls the gateway using a service-account identity token fetched via ADC:
`google.oauth2.id_token.fetch_id_token(auth_req, GATEWAY_SERVICE_URL)`.
This token proves to the gateway's Cloud Run IAM that the caller is `channel-web-sa`.

These are two separate token flows. Never confuse them:
- User token: Google OAuth2 ID token, validated with `verify_oauth2_token()`.
- Service token: Cloud Run identity token, fetched with `fetch_id_token()`.

**`ALLOWED_EMAILS` is loaded at startup from the filesystem** (`/secrets/allowed_emails/ALLOWED_EMAILS`).
If the Secret Manager secret is rotated, the service must be restarted to pick up the change.
There is no live reload. If the file does not exist at startup (e.g. local dev without the
secret mount), `ALLOWED_EMAILS` is empty and all auth attempts return 403.

---

## SSE passthrough

`/chat` does not buffer the gateway response. It opens a streaming HTTP connection to
the gateway and proxies each line as-is. The browser receives `event: thinking`,
`event: progress`, and `event: answer` events in real time.

The proxy is intentionally thin — no rewriting, no buffering, no interpretation of
event types. If the gateway changes its SSE protocol, channel_web does not need to change.

`session_id` is passed through from the browser request body to the gateway call. The
browser is responsible for persisting its `session_id` between requests. channel_web
does not track sessions.

---

## Static assets

**All static asset paths must be root-relative (`/static/file.css`), never `url_for()`.**

Starlette's `url_for()` generates absolute URLs using the internal request scheme
(`http://`). Cloud Run terminates TLS at the load balancer — the container only sees
HTTP. The browser blocks `http://` assets on an `https://` page as mixed content.

Root-relative paths work because the browser resolves them against its current origin
(the `https://` URL the user sees).

This rule applies to: CSS `<link>`, JS `<script>`, image `<img src>`, any asset tag.
The heuristics log has the original incident: [2026-03-21 23:30].

**Template and static directory paths must use `Path(__file__).parent`**, not relative
strings or hardcoded absolute paths. The Docker container's working directory may differ
from the local dev layout. See HEURISTICS.log [2026-03-21] PATH_BUG entry.

---

## Frontend state model

The JavaScript in `static/app.js` is the entire client-side application. It is vanilla
JS — no framework, no build step, no bundler. It must be deployable as-is, served
directly from the filesystem.

State model (at the top of `app.js`):
- `sessionId` — UUID string, persisted across turns within a browser session
- `currentLang` — "en" | "es", persisted in a cookie
- Feedback state per answer card (track which thumb is selected, stored in DOM)

The `session_id` received in the gateway's `event: answer` payload is the authoritative
session ID. The client updates its local `sessionId` from each answer event.

---

## Boundaries — what channel_web owns vs. what it does NOT own

| channel_web owns | channel_web does NOT own |
|---|---|
| Google ID token validation | Query classification or rewriting |
| `ALLOWED_EMAILS` enforcement | Session logic (gateway owns sessions) |
| SSE stream proxying to browser | Retrieval or synthesis |
| Serving the HTML shell | Trace writes (gateway writes traces) |
| Feedback endpoint (proxies to gateway) | Knowledge of span structure |
| Language toggle state (cookie) | |

---

## Guardrails

**Never add business logic here.** If you find yourself parsing the gateway's answer
events, filtering facts, or making decisions about query routing inside channel_web,
stop — that belongs in the gateway.

**`_verify_google_token` and `fetch_id_token` are synchronous and block the event loop.**
Both `verify_oauth2_token()` and `fetch_id_token()` use `google.auth.transport.requests.Request()`,
which makes a blocking HTTP call to Google's servers (key endpoint; usually cached).
Under load, this will stall other coroutines. Fix with `run_in_executor` before scaling.

**Never use `url_for()` for static assets in Jinja2 templates.** The HEURISTICS.log
has documented the exact failure mode. Use `/static/filename.ext` directly.

**Never set both `width` and `height` on `<img>` unless the image is known square.**
Set only the constraining dimension. See HEURISTICS.log [2026-03-22 00:10].

**`google-auth` requires `requests` as a co-dependency.** Always pin both in
`requirements.txt`. google-auth does not declare `requests` as a hard dependency.
HEURISTICS.log [2026-03-21 23:00] documents the original 500 this caused.

**Do not run channel_web tests and gateway tests in the same pytest invocation.**
Both have a file named `main.py`. Python module cache collision causes one suite's
`main` to leak into the other. Run independently: `pytest tests/channel_web/`.

**ALLOWED_EMAILS changes require a service restart.** The list is loaded once at
startup. Do not add a live-reload mechanism without also considering the security
implications of hot-patching the allowlist at runtime.

**OAuth client ID is not a secret.** `GOOGLE_CLIENT_ID` is injected into the Jinja2
template and sent to the browser. This is correct and intentional — it is a public
identifier, not a credential.

---

## Deployment constraints

- `--allow-unauthenticated` (not `--no-allow-unauthenticated`): the login page must
  load before any auth check can run. Auth is enforced at the application layer.
- `GATEWAY_SERVICE_URL`: required at deploy time. Hardcoded in `deploy.sh` as
  `https://gateway-jeyczovqfa-ew.a.run.app` — update when the gateway URL changes.
- Secret: `ALLOWED_EMAILS` volume-mounted at `/secrets/allowed_emails/ALLOWED_EMAILS`.

---

## Known gaps

| Gap | Impact | Fix |
|---|---|---|
| `ALLOWED_EMAILS` requires restart to update | Can't hot-add/remove users | Move to Firestore-backed user store (auth service) |
| Synchronous token ops block async event loop | Latency under load | `run_in_executor` |
| No token refresh on expiry | User gets 401 after token TTL; must reload page | Frontend GIS silent refresh + retry |
| Auth lives in channel_web, not gateway | Adding a second channel (WhatsApp) requires re-implementing auth | Move auth enforcement to gateway (auth service Sprint 3+) |
