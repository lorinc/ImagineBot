# SaaS Maturity Framework — ImagineBot

A benchmark, not a plan. Use it to say: "We are at L1 in Identity, L0 in Tenancy, L2 in Observability."

**Architecture context:** Cloud Run services (gateway, knowledge, channel_web, ingestion, auth, access, security, admin), GCP-native stack (Firestore, Secret Manager, Vertex AI, Cloud IAM, Artifact Registry, GCS), Gemini 2.5 Flash via Vertex AI.

---

## How to read this

Each row is a maturity dimension. Columns are levels:

| Level | Meaning |
|---|---|
| **L0** | Capability absent or entirely manual one-off |
| **L1** | Exists for one tenant; requires developer/operator action each time |
| **L2** | Reliable and automated for one tenant; no dev intervention for normal operation |
| **L3** | Multi-tenant capable; self-service or operationally isolated per tenant |
| `◀ now` | Marks current state |
| `[verified]` | Cell content discussed with and approved by the developer. **Cells without this flag are drafts. Do not use an unverified cell as the basis for a decision or implementation plan.** |

---

## Pillar 1 — Identity & Access

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **User authentication** | No auth | Google Sign-In; email list in Secret Manager; redeploy to add user `◀ now` | Cloud IAP + LB; user list in Firestore; add user without redeploy | Per-tenant OIDC mapping; tenant-scoped token claims; service account per tenant |
| **Service-to-service auth** | Open or API-key | Cloud Run Invoker role; per-service service account `◀ now` | All internal services `--ingress=internal`; no service reachable from internet except gateway | Per-tenant service account grant scoping (for silo tier) |
| **Tenant model** | No tenant concept `◀ now` | Tenant ID in Firestore; tenant context injected into every request | All data writes tagged with tenant; cross-tenant query impossible by construction | Self-service tenant registration; automatic resource provisioning on signup |
| **Access control (per user → source)** | `group_ids` always null; every user sees every document `◀ now` | `group_ids` enforced in knowledge service prompt | `group_ids` enforced in index selection (pre-synthesis); not prompt-based | Per-tenant ACL admin UI; invite flow; role hierarchy (admin/user) |
| **Token revocation** | No server-side revocation; removing an email takes effect at token expiry (≤1h) `◀ now` | Allowlist checked per-request (not cached); effective within seconds of removal | Session invalidation endpoint; active token blacklist in Firestore | Per-tenant admin can revoke individual user sessions |

---

## Pillar 2 — Corpus & Data Lifecycle

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **Corpus ingestion** | Laptop CLI; personal OAuth token; no schedule `◀ now` | Cloud Run Job; service account auth; ops-triggered via CLI | Scheduled Cloud Run Job or Drive webhook; ops-triggered only for first-time setup | Admin UI; any authorized user connects a Drive folder; per-tenant corpus namespace |
| **Index lifecycle** | Index baked into Docker image; update = redeploy `◀ now` | Index in GCS; knowledge service downloads at startup | Ingestion job pushes new index to GCS; knowledge service hot-reloads | Per-tenant index in GCS namespace; index version tracked in Firestore |
| **Corpus freshness signal** | `valid_at` always null; no user-visible freshness signal `◀ now` | Corpus last-updated timestamp written to Firestore at each ingest | "Last updated" shown in UI per document; source-level freshness dates | Per-tenant freshness dashboard; staleness alert if corpus not refreshed in N days |
| **Source document provenance** | `source_id` is opaque technical identifier; no human-readable title `◀ now` | Source metadata (title, Drive URL, last modified) in Firestore `sources` collection | Citations show document title + link; valid_at from source metadata | Per-tenant source registry; docs visible/manageable in admin UI |
| **Language coverage** | Spanish documents silently excluded; Spanish queries answered via English translation; not disclosed `◀ now` | Spanish exclusion disclosed in UI; query language detection routes user to English fallback explicitly | Spanish corpus ingested; language-specific index segments; query language respected | Per-tenant language configuration; corpus language coverage report |
| **GDPR / data deletion** | No mechanism to identify or delete user data `◀ now` | Trace records linked to user ID; deletion deletes traces | Automated deletion workflow; deletion logged in audit trail | Per-tenant DPA; tenant-scoped deletion; right-to-erasure API endpoint |

---

## Pillar 3 — Resilience & Availability

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **Index expiry / hard outage** | Index baked in image; never expires but requires redeploy `◀ now` (PageIndex era) | Index version in GCS; knowledge service checks GCS on startup; fails loudly with actionable error | Proactive index staleness check; alert before serving stale index | Automatic index refresh triggered by corpus update event; zero-downtime swap |
| **Cold start** | `min-instances=0` on all services; first request after idle pays full startup penalty `◀ now` | `min-instances=1` on gateway and knowledge (user-facing critical path) | Startup time <3s; pre-warmed with Firestore connection at container init | Per-tenant traffic-weighted warm pool; autoscaling tuned to tenant usage patterns |
| **Circuit breaking** | No timeout or circuit breaker between gateway and knowledge `◀ now` | Explicit timeout on knowledge client calls; 503 returned on timeout | Gateway retries once with backoff; falls back to "service temporarily unavailable" message | Tenant-aware circuit breaker; noisy-neighbor isolation |
| **Service health checks** | `/health` returns 200 unconditionally; does not exercise Vertex AI or GCS path `◀ now` | `/health` checks GCS index file reachability; returns 503 if index missing | `/health` exercises a full query against the index (lightweight sentinel query) | Per-tenant health check; tenant-scoped status page |
| **Multi-region** | Single region (`europe-west1`); regional outage = full outage `◀ now` | Documented RTO/RPO for regional failure; runbook for manual region failover | Automated failover to secondary region for stateless services | Active-active multi-region with tenant-level data residency controls |
| **Rollback** | No documented or tested rollback procedure `◀ now` | Cloud Run traffic splitting documented; previous-revision rollback tested once | Rollback in runbook; tested in staging each sprint; <5 min to previous revision | Canary deploys; automated rollback on error-rate spike |

---

## Pillar 4 — Observability & Cost

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **Structured logging** | FastAPI/uvicorn default logs; no request ID, user ID, or trace ID `◀ now` | `trace_id` in all log lines; service version in log; JSON log format | `tenant_id`, `session_id`, `user_id` in every log line; Cloud Logging structured queries work | Per-tenant log sink; tenant can query own logs via admin UI |
| **Distributed tracing** | Spans collected in Firestore via custom OTel-inspired spans `◀ now` | `X-Trace-Id` propagated across all service hops; spans queryable per trace | Cloud Trace integration; latency breakdown visible per service hop; p50/p99 per endpoint | Per-tenant trace filtering; tenant-level latency SLI dashboard |
| **Metrics & dashboards** | No Cloud Monitoring dashboards; no error rate or latency metrics `◀ now` | Cloud Monitoring: error rate + p50 latency per service; one dashboard | SLI dashboard: error budget, request volume, Vertex AI token usage, GCS read latency | Per-tenant metric slice; SLA-tier alerting (silver/gold) |
| **Alerting** | No alert policies configured `◀ now` | Alert on: error rate >5%, service unavailability, Cloud Run quota near limit | Alert on: p99 latency spike, cold start frequency, index staleness, Vertex AI quota at 80% | Tenant-aware alerting; tenant-level error budget breach notifies account owner |
| **Cost attribution** | All Vertex AI calls untagged; no way to know which user or query drives cost `◀ now` | Cloud Run and Vertex AI calls labelled with `service` and `environment` | Vertex AI calls carry `trace_id`; cost per query calculable from Firestore trace + billing export | Per-tenant cost attribution via label; cost-per-tenant monthly report; budget alert per tenant |
| **Cost controls** | No query quotas; no budget alerts; unbounded Vertex AI spend possible `◀ now` | GCP budget alert at 80% of monthly budget | Per-user daily query cap enforced in gateway; circuit breaker on Vertex AI quota exhaustion | Per-tenant query quota configurable by admin; overage notification; soft-cap with grace |
| **LLM quality monitoring** | No mechanism to detect answer degradation `◀ now` | 👍/👎 feedback collected; stored in Firestore traces `◀ now` | Weekly feedback report: thumbs-down rate, topics with most negative feedback | Automated regression alert: if thumbs-down rate for a tenant spikes >2σ, alert |

---

## Pillar 5 — Operational Readiness

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **CI/CD** | GitHub Actions defined but not wired; all deploys via manual `deploy.sh` `◀ now` | Workload Identity Federation configured; CI runs lint + unit tests on push | CI blocks merge on failure; staging deploy automatic on merge to main | Production deploy requires manual trigger; smoke tests run post-deploy; GitHub issue opened on failure |
| **Secret management** | Secrets in Secret Manager; volume-mounted into Cloud Run; change requires redeploy `◀ now` | Secrets reloadable without redeploy (env-var mount, not volume) | All secrets rotated on schedule; rotation tested | Per-tenant secret namespace; tenant offboarding triggers secret deletion |
| **Audit log** | No record of who queried what `◀ now` | Firestore traces record `user_id` + query input for every chat request | Immutable audit log in Cloud Logging; tamper-evident; queryable per user | Tenant-level audit export; GDPR-compliant retention policy; export-on-request |
| **Runbook** | No runbook exists `◀ now` | Runbook covers: add user, refresh corpus, rollback deploy, respond to 503 | Runbook covers all alert scenarios; tested quarterly; linked from Cloud Monitoring alerts | Tenant onboarding runbook; automated where possible; ops time <30 min per new tenant |
| **Environments** | One environment (`img-dev`); no staging/prod separation `◀ now` | `img-prod` project provisioned; production deploy uses it | Staging is a functional replica of production; changes validated in staging before prod | Per-tenant staging option (for enterprise tier); tenant-level smoke test after deploy |
| **Corpus persistence** | Processed corpus lives only on developer's laptop `◀ now` | Index artifacts in GCS; laptop loss does not lose the corpus | Ingestion pipeline re-runnable from Drive without any local state | Ingestion pipeline runs on Cloud Run Job; no developer laptop involved |
| **Rate limiting** | No rate limiting at any layer `◀ now` | Gateway enforces per-session request rate (in-memory, resets on restart) | Rate limiter backed by Firestore; survives gateway restarts; returns 429 with retry-after | Per-tenant configurable rate limits; Cloud Armor at infrastructure layer for DDoS |

---

## Pillar 6 — UX

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **Conversation context** | Each query independent; no session memory; follow-up questions fail `◀ now` | Session history passed to LLM within a single browser session | Session persisted in Firestore; survives page refresh; user can scroll history | Per-tenant session retention policy; admin can search/export sessions |
| **Citation display** | Citations show opaque `source_id` (e.g. `en_policy3_admissions`); no human-readable title `◀ now` | Source metadata in Firestore; citations show document title | Citations show title + Drive link + last-modified date | Per-tenant source registry; admin can annotate sources with display names |
| **Freshness signal** | `valid_at` always null; no corpus-last-updated indicator anywhere in UI `◀ now` | Corpus last-updated timestamp shown in UI footer | Per-citation freshness date shown where available; stale corpus warning after N days | Per-tenant freshness threshold configurable; user-visible staleness badge |
| **Language / multilingual UX** | UI language toggle disconnected from LLM; Spanish corpus silently excluded; not disclosed `◀ now` | Spanish exclusion disclosed in UI; query language detection surfaces an explicit fallback notice | Spanish corpus ingested; query language respected; UI language and LLM language aligned | Per-tenant language configuration; corpus language coverage report in admin UI |
| **User feedback** | No thumbs up/down, no report mechanism `◀ now` | 👍/👎 stored in Firestore traces `◀ now` | Feedback linked to source and query; visible in ops dashboard; weekly thumbs-down report | Per-tenant feedback dashboard; low-rated topics surfaced to corpus admin |
| **Onboarding / access denied UX** | 403 with no explanation; no way to request access; no contact information `◀ now` | 403 shows human-readable message with contact email | Self-service access request form; email notification to admin | Per-tenant branded sign-in page; admin-controlled invite flow |
| **Suggested questions** | Static global `questions.json`; same for every user and corpus; change requires redeploy `◀ now` | Questions stored in Firestore; editable without redeploy | Questions configurable per tenant via admin UI | Questions personalized by usage history; surfaced from high-rated prior queries |
| **Error specificity** | Generic error messages; no actionable information `◀ now` | Distinct user-facing messages for: auth failure, corpus unavailable, rate limit, service error | Error messages include retry guidance and status page link | Per-tenant status page; errors link to tenant-specific support channel |
| **Mobile layout** | CSS authored for desktop demo; no responsive design `◀ now` | Responsive layout tested on 375px and 768px viewports | Mobile-first CSS; tested on iOS Safari and Android Chrome | Per-tenant theme/branding; mobile PWA manifest |

---

## Pillar 7 — Security & Compliance

| Dimension | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **Input validation / prompt injection** | User queries pass directly to LLM with no screening `◀ now` | Input length cap + basic injection pattern detection; flagged queries logged | Abuse screening service (jailbreak, prompt injection, data exfiltration patterns); flagged queries rejected with 400 | Per-tenant sensitivity tuning; tenant admin notified of repeated abuse attempts |
| **Output screening** | LLM responses returned verbatim; no filtering `◀ now` | Response length cap; error if model returns empty answer | Harmful-content classifier on responses; system-prompt leak detection | Per-tenant content policy; blocked response categories configurable by admin |
| **Infrastructure-layer security** | Cloud Run exposed directly; no WAF, no DDoS protection `◀ now` | knowledge service `--ingress=internal`; only gateway reachable from internet | Cloud Armor WAF in front of gateway; geo-restriction configurable | Per-tenant Cloud Armor policy; DDoS alert integrated with on-call |
| **Terms of service / DPA** | No ToS, no data processing agreement, no privacy policy `◀ now` | ToS and privacy policy published; linked from sign-in page | DPA template available for institutional customers; countersigned before onboarding | Per-tenant DPA executed and stored; auto-reminder on renewal |
| **Data residency** | All data in `europe-west1`; no per-tenant configuration `◀ now` | Data residency documented; communicated to customers at onboarding | Firestore and GCS bucket region selectable at tenant provisioning | Active enforcement of tenant data residency constraints; audit report available |

---

## Current state snapshot (2026-04-26)

| Pillar | Honest summary |
|---|---|
| Identity & Access | L1 — auth works for one school, single email list, no tenant concept |
| Corpus & Data Lifecycle | L0 / L1 — index on GCS (L1), but ingestion still a laptop CLI (L0), freshness invisible (L0) |
| Resilience & Availability | L0 / L1 — circuit breaker absent (L0), cold starts unaddressed (L0), no rollback procedure (L0), health check synthetic (L0) |
| Observability & Cost | L1 / emerging L2 — traces in Firestore, spans collected, 👍/👎 feedback (L1); no dashboards, no alerts, no cost controls (L0) |
| Operational Readiness | L0 / L1 — deploys manual (L0), no runbook (L0), corpus in GCS (L1), one environment (L0) |
| UX | L0 / L1 — 👍/👎 feedback collected (L1); conversation context absent (L0), citations opaque (L0), freshness invisible (L0), language toggle disconnected (L0) |
| Security & Compliance | L0 — no input/output screening, no WAF, no ToS/DPA, no data residency controls |

**L2 across all dimensions** is the threshold for a production-grade single-tenant deployment.  
**L3 across all dimensions** is the threshold for a second customer signing up without engineering involvement.
