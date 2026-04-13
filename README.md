# ImagineBot

A multi-service Q&A system. Documents are ingested and kept current; users ask questions through a web UI and receive cited answers drawn from those documents. Access is controlled per user per data source.

## Stack

Python 3.12 · FastAPI · Firestore · Vertex AI (Gemini 2.5 Flash, text-embedding-004) · GCP Cloud Run

## Services

```
channel_web   Web UI. Thin client — formats requests, renders responses. No business logic.
gateway       Single entry point for all channels. Handles auth and routing.
knowledge     Retrieval layer. Given a query + permitted source IDs, returns context for the LLM.
ingestion     Document intake. Watches sources, processes changes, writes to the knowledge store.
access        User-to-source mapping. Returns the set of sources a user may query.
auth          Token issuance and validation.
security      Rate limiting and input screening. Sits before the LLM call.
```

## Request flow

```
User → channel_web → gateway → auth → access → security → knowledge → LLM → response
```

## Development

See `CLAUDE.md` for session protocol, spike queue, and service-level context.
See `.claude/HEURISTICS.log` for recorded failure modes and their root causes.
