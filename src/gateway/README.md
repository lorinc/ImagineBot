# Gateway

Single entry point for all channels (web UI, future WhatsApp). Channels call this service only — they have no direct access to knowledge, auth, or any other backend service.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/chat` | Bearer token | Streaming chat — returns SSE |
| GET | `/health` | None | Liveness probe |

## POST /chat

**Request**
```json
{
  "message": "What is the dress code?",
  "session_id": "optional-uuid-for-conversation-continuity"
}
```

**Response** — Server-Sent Events stream

```
event: progress
data: {"key": "received"}

event: progress
data: {"key": "contacting"}

event: progress
data: {"key": "querying_ai"}

event: progress
data: {"key": "processing"}

event: answer
data: {
  "answer": "Students are not required to wear a uniform...",
  "facts": [{"fact": "...", "source_id": "en_policy2_behaviour", "title": "..."}],
  "session_id": "abc123",
  "warning": null
}
```

`warning` is present (non-null) only when HTML was stripped from the input. `facts` is always present; it is empty when the pipeline short-circuits before reaching the knowledge service (out-of-scope, vague).

## Request pipeline

```
POST /chat
  1. sanitize          Strip HTML, normalize whitespace, enforce 512-char limit
  2. classify          LLM call → (in_scope, specific_enough)
  3. rewrite           If session history exists: rewrite follow-up as standalone question
  4. Stage A: topics   Knowledge GET /topics → L1 topic list, no synthesis
  5. breadth check     Sibling consolidation → is query broad?
  6. Stage B: search   Knowledge POST /search → {answer, facts}
  7. stream answer     Prepend BROAD_QUERY_PREFIX if broad; emit answer event
```

Steps 3–7 are skipped when classify returns out-of-scope or not-specific-enough.

## Routing tiers

The classifier runs a single Gemini call with the corpus summary as context and returns two booleans. These drive three tiers:

### Tier 3 — Out of scope
`in_scope = false`

Query has no relation to school policies, staff, students, or events. No knowledge call is made.

```
"How do I bake a cake?"        → out-of-scope refusal
"What is the Tesla stock price?" → out-of-scope refusal
"Tell me a joke"               → out-of-scope refusal
```

### Tier 2 — Vague / not specific enough
`in_scope = true, specific_enough = false`

Query is about the school but has no topic anchor a search could match against. The orientation response is returned directly; no knowledge call is made.

```
"What are the rules?"          → orientation response listing example topics
"What do I need to know?"      → orientation response
"Tell me about the school"     → orientation response
"How does it work?"            → orientation response
```

The threshold is semantic, not lexical. Short questions can be specific (`"What about balls?"` → specific, because "balls" is a topic anchor). Long questions can be vague (`"What is important for me to be aware of as a parent?"` → not specific enough).

### Tier 1 — In scope and specific
`in_scope = true, specific_enough = true`

Standard path. Two sub-variants:

**Normal (focused)** — `topic_count <= MAX_TOPIC_PATHS (5)` after sibling consolidation

Full synthesis against the selected document sections. Answer is returned as-is.

```
"What is the dress code?"
"What happens if my child is sick?"
"What should a teacher do if a student is injured?"
"When is pick-up time?"
"What are the fee payment terms?"
```

**Overview (broad)** — `topic_count > MAX_TOPIC_PATHS (5)` after sibling consolidation

Query spans many distinct areas of the corpus. Knowledge service synthesises with the overview prompt; answer is prefixed with `BROAD_QUERY_PREFIX`.

```
"What does the school cover?"
"Give me a summary of all school policies"
"What are all the rules for students and staff?"
```

**Sibling consolidation rule:** if a single document contributes `>= SIBLING_COLLAPSE_THRESHOLD (3)` L1 sections to the topic list, those sections collapse to one doc-level entry. This means "tell me everything about the health policy" does not trigger overview mode even though it touches many sections — it is one document, one subject area.

## Conversation continuity

Sessions are stored in-process (memory, not Firestore). Each session retains the last 10 turns. Session ID is returned in every answer event; pass it back in subsequent requests.

When a session exists, follow-up questions are rewritten into standalone questions before the knowledge call:

```
Turn 1: "What is the dress code?"
Turn 2: "What about PE?" → rewritten to "What is the dress code for PE lessons?"
```

The rewrite uses the same Gemini model as the classifier (gemini-2.5-flash-lite). If the rewrite fails, the original query is used unchanged.

Sessions are lost on instance restart. Cloud Run may spin down idle instances.

## Sanitization

All input passes through `services/sanitize.py` before any LLM call:

- `<script>` and `<style>` blocks are removed entirely (tag + content)
- All other HTML tags are stripped (text content preserved)
- Whitespace is normalized
- Input is truncated to 512 characters

When HTML is detected a `warning` field is included in the answer event. Empty input after stripping raises an error event instead of an answer.

## Configuration

All values in `config.py`. Tunable without code changes via environment variables:

| Variable | Default | Effect |
|----------|---------|--------|
| `GCP_PROJECT_ID` | `img-dev-490919` | GCP project for Vertex AI calls |
| `VERTEX_AI_LOCATION` | `europe-west1` | Vertex AI region |
| `KNOWLEDGE_SERVICE_URL` | *(required in prod)* | Internal Cloud Run URL of knowledge service |
| `MAX_TOPIC_PATHS` | `5` | Topic count threshold for overview mode |
| `SIBLING_COLLAPSE_THRESHOLD` | `3` | L1 sections from same doc before collapsing to doc-level |

`MAX_TOPIC_PATHS` and `SIBLING_COLLAPSE_THRESHOLD` are empirically tunable — see `src/knowledge/TODO.md` for threshold calibration notes.

## Running locally

```bash
cd src/gateway
pip install -r requirements.txt
export GCP_PROJECT_ID=img-dev-490919
export VERTEX_AI_LOCATION=europe-west1
export KNOWLEDGE_SERVICE_URL=https://knowledge-jeyczovqfa-ew.a.run.app
uvicorn main:app --reload --port 8000
```

Requires GCP Application Default Credentials:
```bash
gcloud auth application-default login
```

## Tests

```bash
# Unit + integration (no external services needed for unit tests)
pytest tests/gateway/ -v

# Scope gate tests make real Vertex AI calls — requires ADC
pytest tests/gateway/test_scope_gate.py -v
```

Tests are split across three files:

| File | Type | What it covers |
|------|------|----------------|
| `test_chat_flow.py` | Unit (mocked) | Full pipeline: routing tiers, overview mode, session rewrite, sanitization errors |
| `test_scope_gate.py` | Integration (live Gemini) | Classifier decisions for in/out-of-scope and specific/vague queries |
| `test_sanitize.py` | Unit | HTML stripping, length truncation, empty input |
