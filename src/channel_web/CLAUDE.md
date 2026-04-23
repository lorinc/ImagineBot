# src/channel_web/ — Claude Code context

## Purpose
Web UI channel. The first user-facing surface. Thin client: formats requests for the
gateway, renders responses. No business logic here — all pipeline logic lives in the gateway.

## Sprint 1 vs. Sprint 2+ transition
Sprint 1: channel_web calls the knowledge service directly (`POST /search`). Auth is
inline — Google Sign-In + `ALLOWED_EMAILS` secret. Single tenant only.

Sprint 2+: channel_web calls the gateway (`POST /chat`). Auth moves to the gateway's
auth middleware backed by `src/auth/`. The ALLOWED_EMAILS approach is retired.

## Stack
- **FastAPI** — serves the Jinja2 template and handles POST /chat
- **Jinja2** — single template (`templates/index.html`). Injects `google_client_id` from env var.
- **Vanilla HTML/CSS/JS** — no framework, no build step, no CDN dependency
  - `static/style.css` — hand-written CSS, pixel-for-pixel from Vercel demo
  - `static/app.js` — all interactivity: language toggle, pills, submit, answer cards
  - `static/questions.json` — suggestion pill categories + questions in EN/ES. Edit this file
    to change questions without touching code.

## File map
```
main.py                      App factory. Mounts static files, registers routes.
templates/
  index.html                 Single-page Jinja2 template. Uses /static/... paths (NOT url_for).
static/
  style.css                  Hand-written CSS. All design tokens as CSS variables at top.
  app.js                     Vanilla JS. State at top, init() at bottom.
  questions.json             { "en": { "categories": [...] }, "es": { "categories": [...] } }
  images/
    logo-imagine-montessori-school.png
deploy.sh                    Manual deploy to Cloud Run (img-dev). Run from repo root.
```

## CRITICAL: static asset paths in templates
**Never use `url_for()` for static asset hrefs/srcs.** Use root-relative paths directly:
```html
<!-- WRONG — generates http:// absolute URL, blocked as mixed content on HTTPS Cloud Run -->
<link rel="stylesheet" href="{{ url_for('static', path='style.css') }}">

<!-- CORRECT -->
<link rel="stylesheet" href="/static/style.css">
```
`url_for()` uses the internal request scheme (http://). Cloud Run terminates TLS at the load
balancer — the container only sees HTTP. Browser blocks http:// assets on an https:// page.

## API contract
```
GET /
  Response: HTML page

POST /chat
  Request:  { "message": str }
  Response: { "answer": str, "facts": [{ "fact": str, "source_id": str, "valid_at": str|null }] }
  Error:    { "error": str }   (never exposes stack traces)

GET /health
  Response: { "status": "healthy" }
```

## Auth (Phase 1.4)
- `/chat` requires `Authorization: Bearer <google-id-token>` — returns 401/403 otherwise
- Backend validates with `google.oauth2.id_token.verify_oauth2_token(token, Request(), GOOGLE_CLIENT_ID)`
- Allowed emails loaded at startup from `/secrets/allowed_emails/ALLOWED_EMAILS` (comma-separated)
- `requests` package required alongside `google-auth` — transport won't load without it
- Frontend: Google Identity Services (GIS) login overlay; token stored in memory only
- OAuth client authorized JS origin must include the Cloud Run URL (Google Cloud Console → Credentials)

## Key invariants
- `/chat` calls `POST {KNOWLEDGE_SERVICE_URL}/search` with `group_ids: null`
- Service-account identity token attached via `google.oauth2.id_token.fetch_id_token()` (Cloud Run ADC)
- All errors returned as `{ "error": str }` — never expose stack traces to browser
- Static asset paths use `/static/...` — never `url_for()`
- img tags: never set both width and height unless the image is known square — set one dimension only

## Environment variables
```
KNOWLEDGE_SERVICE_URL    Internal Cloud Run URL for the knowledge service
GOOGLE_CLIENT_ID         OAuth 2.0 client ID (safe to expose to frontend) — set in Phase 1.4
```

## Secrets (Secret Manager, volume-mounted)
```
/secrets/allowed_emails/ALLOWED_EMAILS    Comma-separated permitted email list — used in Phase 1.4
```

## Deployment
```bash
# From repo root:
bash src/channel_web/deploy.sh
```
Cloud Run: `--allow-unauthenticated` (login page must load before auth check in Phase 1.4).
Service account: `channel-web-sa@img-dev-490919.iam.gserviceaccount.com`.

## Current status (Sprint 1 complete — 2026-03-22)
- Deployed: https://channel-web-jeyczovqfa-ew.a.run.app (revision channel-web-00005-7t9)
- Tests: 9/9 passing (`tests/channel_web/test_channel_web.py`)
- Auth: Google Sign-In + ID token validation + allowed-email gate ✅
- Sprint 1 acceptance pending: browser UAT sign-in + cited answer

## Running locally
```bash
cd /path/to/repo
export KNOWLEDGE_SERVICE_URL=https://knowledge-jeyczovqfa-ew.a.run.app
export GOOGLE_CLIENT_ID=<value from credentials file OAUTH_CLIENT_ID>
uvicorn src.channel_web.main:app --reload --port 8080
# ADC required for service-account identity token: gcloud auth application-default login
# Auth will not work locally — GIS only fires on registered JS origins (Cloud Run URL)
```
