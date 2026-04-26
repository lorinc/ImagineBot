import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import (
    BROAD_QUERY_PREFIX,
    MAX_TOPIC_PATHS,
    ORIENTATION_RESPONSE,
    OUT_OF_SCOPE_REPLY,
    SERVICE_VERSION,
    SIBLING_COLLAPSE_THRESHOLD,
)
from services.sanitize import sanitize
from services.scope_gate import classify
from services.rewrite import rewrite_standalone
from services import knowledge_client
from services.observability import SpanCollector
from services.step_messages import format_span
from services.trace_writer import write_trace, update_feedback

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store: session_id -> last 10 turns [{q, a}]
_sessions: dict[str, list[dict]] = {}
_MAX_HISTORY = 10

# Cached corpus summary for the classifier prompt. Refreshed every 10 minutes so a
# knowledge service redeploy with a new index is picked up without restarting the gateway.
_corpus_summary: str | None = None
_corpus_summary_fetched_at: float = 0.0
_CORPUS_SUMMARY_TTL = 600  # seconds


async def _get_corpus_summary() -> str:
    global _corpus_summary, _corpus_summary_fetched_at
    if _corpus_summary is None or time.monotonic() - _corpus_summary_fetched_at > _CORPUS_SUMMARY_TTL:
        try:
            _corpus_summary = await knowledge_client.get_summary()
            _corpus_summary_fetched_at = time.monotonic()
        except Exception as e:
            logger.warning("Could not fetch corpus summary, using fallback: %s", e)
            if _corpus_summary is None:
                _corpus_summary = "A school information system covering policies and procedures."
    return _corpus_summary


def _count_topics(l1_topics: list[dict]) -> tuple[int, list[str]]:
    """
    Sibling consolidation: docs with >= SIBLING_COLLAPSE_THRESHOLD L1 sections selected
    collapse to a single doc-level label. Returns (count, human-readable label list).
    """
    by_doc: dict[str, list[dict]] = {}
    for t in l1_topics:
        by_doc.setdefault(t["doc_id"], []).append(t)

    labels: list[str] = []
    for doc_id, sections in by_doc.items():
        if len(sections) >= SIBLING_COLLAPSE_THRESHOLD:
            labels.append(doc_id.replace("_", " ").replace("-", " ").title())
        else:
            labels.extend(s["title"] for s in sections)

    return len(labels), labels


def _thinking_sse(span: dict) -> str | None:
    text = format_span(span)
    if text is None:
        return None
    return f'event: thinking\ndata: {json.dumps({"text": text, "ms": span["duration_ms"]})}\n\n'


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int
    comment: str | None = None


@router.post("/chat")
async def chat(body: ChatRequest):
    async def generate():
        trace_id = str(uuid4())
        session_id = body.session_id or str(uuid4())
        spans = SpanCollector()

        trace: dict = {
            "trace_id": trace_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "versions": {"gateway": SERVICE_VERSION, "knowledge": "unknown"},
            "pipeline_path": None,
            "input": {
                "raw_message": body.message,
                "sanitized_query": None,
                "sanitize_warning": None,
            },
            "classifier": None,
            "rewrite": None,
            "topics": None,
            "knowledge": None,
            "output": None,
            "feedback": None,
        }

        # 1. Sanitize
        try:
            query, sanitize_warning = sanitize(body.message)
        except ValueError as e:
            yield f'event: error\ndata: {json.dumps({"error": str(e)})}\n\n'
            return

        trace["input"]["sanitized_query"] = query
        trace["input"]["sanitize_warning"] = sanitize_warning

        yield 'event: progress\ndata: {"key": "received"}\n\n'

        # 2. Classify: scope + specificity in one LLM call
        corpus_summary = await _get_corpus_summary()
        t_classify = time.monotonic()
        try:
            in_scope, specific_enough = await classify(query, corpus_summary)
        except Exception as e:
            logger.error("Classifier error: %s", e)
            in_scope, specific_enough = True, True  # fail open

        classify_ms = int((time.monotonic() - t_classify) * 1000)
        trace["classifier"] = {
            "in_scope": in_scope,
            "specific_enough": specific_enough,
            "latency_ms": classify_ms,
        }

        if not in_scope:
            span = spans.record("classify.out_of_scope",
                                {"in_scope": in_scope, "specific_enough": specific_enough},
                                duration_ms=classify_ms)
        elif not specific_enough:
            span = spans.record("classify.not_specific",
                                {"in_scope": in_scope, "specific_enough": specific_enough},
                                duration_ms=classify_ms)
        else:
            span = spans.record("classify",
                                {"in_scope": in_scope, "specific_enough": specific_enough},
                                duration_ms=classify_ms)
        if msg := _thinking_sse(span):
            yield msg

        if not in_scope:
            trace["pipeline_path"] = "out_of_scope"
            trace["output"] = {"answer": OUT_OF_SCOPE_REPLY}
            trace["spans"] = spans.spans()
            asyncio.create_task(write_trace(trace))
            yield f'event: answer\ndata: {json.dumps({"answer": OUT_OF_SCOPE_REPLY, "facts": [], "session_id": session_id, "trace_id": trace_id})}\n\n'
            return

        if not specific_enough:
            trace["pipeline_path"] = "orientation"
            trace["output"] = {"answer": ORIENTATION_RESPONSE}
            trace["spans"] = spans.spans()
            asyncio.create_task(write_trace(trace))
            yield f'event: answer\ndata: {json.dumps({"answer": ORIENTATION_RESPONSE, "facts": [], "session_id": session_id, "trace_id": trace_id})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "contacting"}\n\n'

        # 3. Resolve session + standalone rewrite
        history = _sessions.get(session_id, [])
        final_query = query
        rewritten: str | None = None
        t_rewrite = time.monotonic()
        if history:
            try:
                final_query = await rewrite_standalone(query, history)
                logger.info("Rewrote query: %r → %r", query, final_query)
                rewritten = final_query if final_query != query else None
            except Exception as e:
                logger.warning("Rewrite failed, using original: %s", e)

        rewrite_ms = int((time.monotonic() - t_rewrite) * 1000) if history else None
        trace["rewrite"] = {
            "rewritten_query": rewritten,
            "latency_ms": rewrite_ms,
        }
        if rewritten:
            span = spans.record("rewrite",
                                {"rewritten_query": rewritten, "original_query": query},
                                duration_ms=rewrite_ms)
        else:
            span = spans.record("rewrite.skipped", {}, duration_ms=None)
        if msg := _thinking_sse(span):
            yield msg

        yield 'event: progress\ndata: {"key": "querying_ai"}\n\n'

        # 4. Stage A: topic breadth check (routing + selection only, no synthesis)
        overview = False
        topic_count = 0
        doc_ids_selected: list[str] = []
        t_topics = time.monotonic()
        try:
            l1_topics = await knowledge_client.get_topics(final_query, trace_id=trace_id)
            topic_count, topic_labels = _count_topics(l1_topics)
            doc_ids_selected = list({t["doc_id"] for t in l1_topics})
            if topic_count > MAX_TOPIC_PATHS:
                overview = True
                logger.info("Broad query (%d topics after consolidation) — overview mode", topic_count)
            topic_labels_short = ", ".join(topic_labels[:4])
            if len(topic_labels) > 4:
                topic_labels_short += f" +{len(topic_labels) - 4} more"
            span = spans.record("topics", {
                "topic_labels_short": topic_labels_short,
                "topic_count": topic_count,
                "doc_ids_selected": doc_ids_selected,
            }, duration_ms=int((time.monotonic() - t_topics) * 1000))
            if msg := _thinking_sse(span):
                yield msg
        except Exception as e:
            logger.warning("Topics check failed, skipping breadth detection: %s", e)

        trace["topics"] = {
            "doc_ids_selected": doc_ids_selected,
            "topic_count": topic_count,
            "overview": overview,
            "latency_ms": int((time.monotonic() - t_topics) * 1000),
        }

        if overview:
            span = spans.record("breadth.overview", {"topic_count": topic_count}, duration_ms=None)
        else:
            span = spans.record("breadth.focused", {"topic_count": topic_count}, duration_ms=None)
        if msg := _thinking_sse(span):
            yield msg

        # 5. Stage B: full synthesis via streaming (overview prompt when broad)
        t_knowledge = time.monotonic()
        result: dict | None = None
        knowledge_version = "unknown"
        try:
            async for event_type, payload, kv in knowledge_client.search_stream(
                    final_query, trace_id=trace_id, overview=overview):
                knowledge_version = kv
                if event_type == "span":
                    spans.record_external(payload)
                    if msg := _thinking_sse(payload):
                        yield msg
                elif event_type == "answer":
                    result = payload
                elif event_type == "error":
                    raise RuntimeError(payload.get("error", "unknown error"))
        except Exception as e:
            logger.error("Knowledge service error: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": "Knowledge service unavailable"})}\n\n'
            return

        trace["versions"]["knowledge"] = knowledge_version

        yield 'event: progress\ndata: {"key": "processing"}\n\n'

        # 6. Update session history
        answer = (result or {}).get("answer", "")
        history = history + [{"q": query, "a": answer}]
        _sessions[session_id] = history[-_MAX_HISTORY:]

        trace["knowledge"] = {
            "nodes_selected": (result or {}).get("selected_nodes", []),
            "answer": answer,
            "facts": (result or {}).get("facts", []),
            "latency_ms": int((time.monotonic() - t_knowledge) * 1000),
        }

        if overview:
            answer = BROAD_QUERY_PREFIX + answer

        trace["pipeline_path"] = "broad" if overview else "specific"
        trace["output"] = {"answer": answer}
        trace["spans"] = spans.spans()
        asyncio.create_task(write_trace(trace))

        payload = {
            "answer": answer,
            "facts": (result or {}).get("facts", []),
            "session_id": session_id,
            "trace_id": trace_id,
        }
        if sanitize_warning:
            payload["warning"] = sanitize_warning
        yield f'event: answer\ndata: {json.dumps(payload)}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/feedback")
async def feedback(body: FeedbackRequest):
    await update_feedback(body.trace_id, body.rating, body.comment)
    return {"status": "ok"}
