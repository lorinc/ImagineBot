# Gap Analysis: ImagineBot → Reliable, Monitored, HA, Multi-Tenant Self-Service SaaS

This is not an implementation plan — it is a gap audit. The codebase is a working single-tenant POC
(Sprint 1 complete, one school, three known users, manually deployed). The question is: what stands
between this and a product another organization could sign up for, use reliably, and trust with their
institutional knowledge?

No solutions are proposed. These are observations about what the current system cannot do or does not handle.

---

## 1. Multi-Tenancy

**No tenant concept exists.**
The data model has no organization, school, or tenant entity. There is no isolation boundary in Firestore,
no per-tenant namespace, no per-tenant service account. The entire system is scoped to one implicit tenant.

**The corpus is global.**
`config/context_cache` is a single Firestore document. There is no foreign key to any tenant. Every user
on the system queries the same corpus. Adding a second school means forking the entire deployment, not
adding a tenant.

**Access control is a flat email list.**
`ALLOWED_EMAILS` is a comma-separated string in Secret Manager. Adding a user to an organization requires
GCP console access to update the secret and redeploy (secrets are volume-mounted, not live-reloaded).
There is no concept of admin vs. user role, no organization membership, no invite flow.

**`group_ids` is always `null`.**
The access filtering field exists in the API contract but is hardcoded to `null` in every call path.
Every user sees every document. The field is a promise the code does not keep.

**No self-service onboarding path exists.**
There is no signup flow, no tenant registration, no way for a new school to provision itself. Every
new customer requires direct engineering involvement in GCP.

---

## 2. Corpus and Cache — The Hidden Ceiling

**The corpus has a practical size limit the operator doesn't know about.**
Vertex AI Context Caching has a token limit. The current corpus is ~100K tokens. The system has no
mechanism to warn when approaching the limit, no measurement of current token usage surfaced anywhere,
and no guardrail preventing cache creation from failing silently on an oversized corpus.

**The cache does not auto-refresh.**
When documents change in Google Drive, the cache is not updated. The only refresh mechanism is a
developer running `python3 tools/create_cache.py` manually on a local machine with ADC credentials.
There is no trigger, no schedule, no webhook, no notification to operators that the corpus is stale.

**The cache has a TTL and no failover.**
The cache is created with a configurable TTL (default 48 hours). When it expires, every query returns
HTTP 503. There is no fallback, no grace period, no alert before expiry. The system fails completely
and silently until a developer notices and reruns the script.

**Firestore and Vertex AI cache can desync.**
If `create_cache.py` creates the Vertex AI cache but fails before writing to Firestore (or vice versa),
the system is in an inconsistent state — queries either fail (cache name missing from Firestore) or
the Vertex AI resource leaks (cache exists but is unreachable). No reconciliation mechanism exists.

**`valid_at` is always `null`.**
Citations carry a `valid_at` field that is always null. Users have no idea whether the cited information
reflects the document as it was last year or last week. Corpus freshness is invisible to end users.

**The Spanish corpus is silently excluded.**
Spanish-language documents are excluded from the cache. The system answers Spanish questions by
instructing the LLM to translate English knowledge. This is not disclosed anywhere in the UI.
A Spanish-speaking user asking about Spanish-specific content may get wrong or missing answers with
no indication of why.

---

## 3. Document Ingestion — No Self-Service, No Automation

**There is no way for a user (or admin) to connect a Google Drive folder.**
The Drive integration requires a developer to run the pipeline locally with personal OAuth credentials
(`token.json`) tied to one person's account, executing each pipeline step manually. There is no UI,
no API, no configuration mechanism for connecting a data source. The corpus is static unless a
developer intervenes.

**The Drive OAuth token is a personal credential.**
`token.json` is a personal OAuth token that expires and is not rotatable without re-authentication.
It is tied to the developer's Google account, not a service identity. If that person leaves or the
token expires, the ingestion pipeline stops working. Domain-Wide Delegation (the correct pattern) is
not configured.

**The pipeline is a local CLI process, not a service.**
There are no pipeline steps deployed anywhere. The pipeline runs on a developer's laptop. There is no
scheduling, no retries, no monitoring, no failure notification, no audit trail of when the corpus was
last refreshed and from what state.

**No notification when source documents change.**
There is no Drive webhook, no change detection, no polling. The system has no way to know that an
important policy document was updated in Drive. Staleness is invisible.

---

## 4. Security

**No rate limiting exists anywhere.**
Any authenticated user (valid Google account in the email list) can send unlimited queries. There is
no per-user limit, no per-IP limit, no global throughput cap. A single user can exhaust Vertex AI
quota or generate unbounded cost.

**No prompt injection or abuse screening.**
User queries go directly to the LLM with no input validation beyond JSON parsing. There is no detection
of jailbreak attempts, prompt injection, or attempts to extract data from other tenants' corpora.

**No output screening.**
LLM responses are returned verbatim. If the model generates harmful content or leaks system prompt
content, it is returned to the user with no filtering.

**No token revocation.**
Authentication relies entirely on Google's ID token validation. Once a token is issued, there is no
server-side revocation. If an email is removed from `ALLOWED_EMAILS`, in-flight requests with valid
tokens still succeed until the token expires (typically 1 hour).

**No audit log.**
There is no record of who asked what, when, or what was returned. For a system serving institutional
knowledge, this is a compliance gap. There is no way to investigate misuse, respond to a data
request, or understand how the system is being used.

**The knowledge service is publicly reachable.**
`--ingress=all` is documented as temporary (TODO E0) but is the current production state. The service
is reachable from the public internet with only a bearer token as protection.

**ALLOWED_EMAILS change requires a GCP secret update and redeploy.**
There is no runtime revocation, no user management API, no admin interface.

**No WAF, no DDoS protection.**
Cloud Run is exposed directly. There is no Google Cloud Armor, no CDN, no rate limiting at the
infrastructure layer.

---

## 5. Cost Control

**No per-user or per-tenant cost attribution.**
All Vertex AI calls go through a single project with no tagging, no labeling, no ability to attribute
cost to a specific user, organization, or query. There is no way to know which tenant is driving cost.

**No budget alerts.**
There are no GCP budget alerts configured. A bug causing infinite retries, a malicious user, or
unexpected traffic could exhaust quota or generate a large bill with no notification.

**No query quotas.**
There is no mechanism to limit how many queries a user, tenant, or the system overall can make per
day/month. The economics of the system are entirely uncontrolled.

**Cache creation cost is untracked.**
Every call to `create_cache.py` sends the entire corpus to Vertex AI as input tokens. Running this
script repeatedly (e.g., debugging) generates input token costs. There is no tracking or alerting.

**Cost per query is unknown and untested at scale.**
The system was designed for ~500 queries/day at one school. The cost model has not been validated
at even 10x that load. There is no load test, no cost projection, no circuit breaker.

---

## 6. High Availability and Reliability

**Min instances = 0 on all Cloud Run services.**
Every service cold-starts after idle periods. The first user waits for container startup, dependency
loading, and Firestore warmup. Under current scale this is acceptable, but it is a reliability gap
at SaaS scale.

**A single Firestore document is a synchronization bottleneck.**
All knowledge service instances read from `config/context_cache` — a single Firestore document. Under
high concurrency, this creates read pressure on one document. The 5-minute in-process TTL cache
partially mitigates this, but cold-start instances (min=0) all hit Firestore simultaneously.

**Cache expiry is a hard, undetected outage.**
When the cache TTL expires, every query fails with 503. There is no proactive monitoring of cache
expiry, no alert, no on-call notification. The failure mode is: users start getting errors, eventually
someone notices, eventually a developer runs the script.

**No circuit breaker between channel_web and knowledge.**
If the knowledge service is slow or erroring, channel_web blocks waiting for it. There is no timeout
tuning, no circuit breaker, no fallback response.

**No multi-region deployment.**
Both services are in `europe-west1`. A regional GCP outage takes the entire system down.

**No health monitoring beyond the /health endpoint.**
The `/health` endpoint returns `{ "status": "healthy" }` unconditionally. It does not check Firestore
connectivity, Vertex AI reachability, or cache validity. A "healthy" response from the service does
not mean the service can actually serve queries.

---

## 7. Observability

**No structured logging.**
Logs are whatever FastAPI and uvicorn emit by default. There is no request ID, no user ID, no tenant
ID, no query hash, no latency breakdown in any log line. Debugging a production issue requires
manually grepping Cloud Run logs.

**No distributed tracing.**
A single user query spans channel_web → knowledge → Vertex AI. There is no trace ID propagated
across services, no way to correlate logs from a single request across services.

**No metrics or dashboards.**
There is no Cloud Monitoring dashboard, no latency percentiles, no error rate, no cache hit rate,
no token usage trend. The system is operationally blind.

**No alerting.**
There are no alert policies for: error rate spikes, cache expiry, latency degradation, cold start
frequency, quota exhaustion, or service unavailability.

**No LLM quality monitoring.**
There is no mechanism to detect answer degradation. If the model starts hallucinating, returning
empty answers, or ignoring citations, no one will know unless a user reports it.

**The `/health` check is synthetic, not functional.**
It does not exercise the actual query path. A service that can receive HTTP requests but cannot
query Vertex AI reports as healthy.

---

## 8. UX

**No onboarding flow.**
A new user who receives a link to the chatbot hits a Google Sign-In screen. If their email is not in
`ALLOWED_EMAILS`, they see a 403 with no explanation, no way to request access, no contact information.

**No feedback mechanism.**
Users cannot indicate whether an answer was helpful, wrong, or incomplete. There is no thumbs up/down,
no "report an issue," no way for the system to learn what's working.

**No conversation context.**
Each question is independent. Users cannot ask follow-up questions ("what about for secondary students?").
The system has no memory of the current session.

**Citations show `source_id`, not document names.**
Source citations display the source_id (a technical identifier like `en_policy3_admissions`). Users
see a technical identifier, not "Admissions Policy 2024–25." There is no mapping from source_id to a
human-readable document title.

**No freshness signal.**
Users cannot tell whether the information is from a policy updated last week or three years ago.
`valid_at` is null everywhere. There is no "corpus last updated" indicator anywhere in the UI.

**The language toggle is disconnected from LLM behavior.**
The UI has an EN/ES toggle, but the knowledge service returns answers based on what language the
question is asked in, not the UI language setting. These two signals are not connected. A user who
sets the UI to Spanish but asks in English will get an English answer.

**No error specificity.**
Error events return generic messages. Users get no actionable information when something goes wrong.

**Suggested questions are static and global.**
`questions.json` is a single static file. Questions are the same for every user and every corpus.
There is no personalization, no surfacing of what other users find useful, no per-tenant question
customization without a code change and redeploy.

**No mobile layout considered.**
The CSS was authored to match a desktop demo. No mention of responsive design or mobile testing.

**No way for users to request corpus updates.**
If a user notices the information is out of date, there is no mechanism to flag this or request a
refresh. They can only contact whoever manages the system outside the product.

---

## 9. Operational Readiness

**No CI/CD pipeline is active.**
GitHub Actions workflows are defined and committed, but Workload Identity Federation is not configured,
GitHub Secrets are not set, and branch protection is not enabled. Every deployment is a manual
`deploy.sh` script run from a developer's laptop. There is no automated testing on push, no
automated deploy on merge.

**No rollback procedure.**
There is no documented or tested rollback. Cloud Run supports traffic splitting and previous-revision
rollback, but this is not documented, not tested, and not in any runbook.

**No runbook.**
There is no operational runbook documenting: how to refresh the cache, how to add a user, how to
roll back a deploy, what to do when the cache expires, what to do when Vertex AI is down.

**Production project does not exist.**
The `img-prod` GCP project is referenced in planning documents but not provisioned. There is no
production environment, no production data, no tested production deploy process.

**No staging/production parity.**
There is one environment (`img-dev`). There is no way to validate a change in staging before
production because staging and production are the same environment.

**The corpus lives on a developer's laptop.**
`data/pipeline/` is gitignored local filesystem. If the developer's laptop is lost or corrupted, the
processed corpus is gone and must be regenerated from scratch.

---

## 10. Compliance and Privacy

**No audit trail for data access.**
There is no record of which users accessed which information. For educational institutions handling
policy documents, family manuals, or sensitive operational data, this is a potential compliance gap
(GDPR, FERPA, local equivalents).

**No data deletion capability.**
If a user requests deletion of their data (GDPR right to erasure), there is no mechanism to identify,
locate, or delete their query history — and when query history is added, there will be no deletion path.

**No terms of service or data processing agreement.**
For a SaaS serving schools, data processing agreements and privacy policies are typically legally
required. None exist.

**No data residency guarantees.**
All data is in `europe-west1`, which may or may not satisfy the data residency requirements of a
given customer. There is no per-tenant data location configuration.

---

## The Hardest Blockers for Any Second Tenant

1. **No tenant model** — the data model, Firestore schema, and auth system cannot represent multiple organizations
2. **Cache does not auto-refresh** — corpus staleness is invisible and cache expiry is a hard outage with no warning
3. **No self-service anything** — adding a user, connecting a Drive folder, or onboarding a new school all require developer intervention in GCP
4. **No Drive integration as a service** — the document source is a manual pipeline run on a laptop, not a connected service
5. **No rate limiting or cost controls** — any tenant can generate unbounded Vertex AI spend
6. **No observability** — the system has no metrics, no tracing, no alerting; failures are invisible until users report them
7. **`valid_at` is always null and citations show opaque identifiers** — users cannot evaluate answer freshness or source credibility
