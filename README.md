# ImagineBot

A multi-service Q&A system for school communities. Documents are ingested and kept
current; users ask questions through a web UI and receive cited answers drawn from
those documents. Access is controlled per user per data source.

## Stack

Python 3.12 · FastAPI · Firestore · Vertex AI (Gemini 2.5 Flash) · GCP Cloud Run · GCS

---

## SaaS maturity dimensions

Current state marked with `◀ now`. Target is L2 across all dimensions for a
production-grade single-tenant deployment; L3 for multi-tenant self-service.

| Dimension | Current | L2 target | L3 target |
|---|---|---|---|
| **User authentication** | Email allowlist in Secret Manager; redeploy to add user `◀` | Cloud IAP + Firestore; no redeploy | Per-tenant OIDC; tenant-scoped token claims |
| **Service-to-service auth** | Cloud Run Invoker role per service `◀` | All internal services unreachable from internet | Per-tenant service account scoping |
| **Tenant model** | No tenant concept `◀` | Tenant ID in every request + write | Self-service tenant registration |
| **Access control** | `group_ids` always null; all users see all documents `◀` | Pre-retrieval filter enforced in index selection | Per-tenant ACL admin UI + invite flow |
| **Corpus ingestion** | Laptop CLI; personal OAuth token `◀` | Scheduled Cloud Run Job; ops-triggered | Admin UI; any authorized user connects a Drive folder |
| **Index lifecycle** | Index baked into Docker image; update = redeploy `◀` | Index in GCS; hot-reload on update | Per-tenant index namespace; version tracked in Firestore |
| **Corpus freshness** | `valid_at` always null `◀` | Last-updated timestamp per source in Firestore | Staleness alert; per-tenant freshness dashboard |
| **Structured logging** | Default uvicorn logs `◀` | `trace_id` + service version in all log lines | `tenant_id`, `user_id` in every line; Cloud Logging queries |
| **Distributed tracing** | Custom OTel-inspired spans in Firestore `◀` | `X-Trace-Id` across all service hops | Cloud Trace integration; per-service latency breakdown |
| **Alerting** | None `◀` | Error rate + service unavailability alerts | Tenant-aware error budget breach notifications |
| **Cost attribution** | Vertex AI calls untagged `◀` | Calls labelled by service + environment | Per-tenant cost report; per-tenant query quota |
| **LLM quality monitoring** | 👍/👎 feedback collected in Firestore `◀` | Weekly thumbs-down rate report by topic | Automated regression alert on feedback spike |
| **CI/CD** | Manual `deploy.sh` only `◀` | CI runs lint + unit tests on push; blocks merge | Staging auto-deploy on merge; production manual trigger with smoke tests |
| **Rollback** | No documented procedure `◀` | Cloud Run traffic splitting; rollback tested each sprint | Canary deploys; auto-rollback on error-rate spike |

Full framework: `docs/SAAS_MATURITY_FRAMEWORK.md`

---

## What runs beneath the surface

Architecture and operational decisions are grounded in a set of design documents in
`docs/design/`: a RAG system design covering the document corpus model and retrieval
architecture; a pre-retrieval harness framework (sanitization, classification, query
rewriting, access enforcement); a mature infrastructure gap analysis benchmarking the
current system against reliable multi-tenant SaaS; UX and conversational design
frameworks; and observability design based on OpenTelemetry conventions.

Development is driven by Claude Code as the primary agent. Keeping that coherent across
sessions requires more than code: `docs/ARCHITECTURE.md` holds cross-cutting invariants
and guardrails (topology, auth flows, SSE protocol, access control chain) that no single
service owns. `.claude/HEURISTICS.log` is an append-only record of every significant
failure mode, structured so the `PREVENTED_BY` field encodes a structural fix, not advice.
Each service has its own `CLAUDE.md` (current state, known gaps) and `TODO.md`
(append-only backlog). `docs/PROJECT_PLAN.md` anchors sprint work to the maturity
framework above.

---

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

## Development

```
User → channel_web → gateway → knowledge → Vertex AI → response
                   ↘ Firestore (traces + feedback, fire-and-forget)
```

See `CLAUDE.md` for session protocol and service-level context.
See `.claude/HEURISTICS.log` for recorded failure modes and root causes.
See `docs/ARCHITECTURE.md` for cross-cutting invariants and guardrails.
See `docs/PROJECT_PLAN.md` for sprint status.
