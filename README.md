# ImagineBot

A multi-service Q&A system. Documents are ingested and kept current; users ask questions through a web UI and receive cited answers drawn from those documents. Access is controlled per user per data source.

## Stack

Python 3.12 · FastAPI · Firestore · Vertex AI (Gemini 2.5 Flash) · GCP Cloud Run · GCS

## Services

```
channel_web   Web UI. Thin client — formats requests, renders responses. No business logic.
gateway       Single entry point for all channels. Handles routing, session, tracing, feedback.
knowledge     Retrieval layer. PageIndex + Gemini: given a query, returns cited answer.
ingestion     Document intake. Converts Drive corpus → Markdown → PageIndex → GCS.
access        User-to-source mapping. Returns the set of sources a user may query. [planned]
auth          Token issuance and validation. [planned]
security      Rate limiting and input screening. [planned]
admin         Tenant + corpus management. [planned]
```

## Deployed (img-dev-490919, europe-west1)

```
channel_web   https://channel-web-jeyczovqfa-ew.a.run.app   public, Google Sign-In
gateway       https://gateway-jeyczovqfa-ew.a.run.app        internal
knowledge     https://knowledge-jeyczovqfa-ew.a.run.app      internal
```

## Request flow

```
User → channel_web → gateway → knowledge → Vertex AI → response
                   ↘ Firestore (traces + feedback, fire-and-forget)
```

## Development

See `CLAUDE.md` for session protocol and service-level context.
See `.claude/HEURISTICS.log` for recorded failure modes and root causes.
See `docs/PROJECT_PLAN.md` for sprint status.
