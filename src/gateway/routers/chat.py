import json
import logging
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import (
    BROAD_QUERY_PREFIX,
    MAX_TOPIC_PATHS,
    ORIENTATION_RESPONSE,
    OUT_OF_SCOPE_REPLY,
    SIBLING_COLLAPSE_THRESHOLD,
)
from services.sanitize import sanitize
from services.scope_gate import classify
from services.rewrite import rewrite_standalone
from services import knowledge_client

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store: session_id -> last 10 turns [{q, a}]
_sessions: dict[str, list[dict]] = {}
_MAX_HISTORY = 10

# Cached corpus summary for the classifier prompt. Loaded lazily on first request.
_corpus_summary: str | None = None


async def _get_corpus_summary() -> str:
    global _corpus_summary
    if _corpus_summary is None:
        try:
            _corpus_summary = await knowledge_client.get_summary()
        except Exception as e:
            logger.warning("Could not fetch corpus summary, using fallback: %s", e)
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


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/chat")
async def chat(body: ChatRequest):
    async def generate():
        # 1. Sanitize
        try:
            query, sanitize_warning = sanitize(body.message)
        except ValueError as e:
            yield f'event: error\ndata: {json.dumps({"error": str(e)})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "received"}\n\n'

        # 2. Classify: scope + specificity in one LLM call
        corpus_summary = await _get_corpus_summary()
        try:
            in_scope, specific_enough = await classify(query, corpus_summary)
        except Exception as e:
            logger.error("Classifier error: %s", e)
            in_scope, specific_enough = True, True  # fail open

        session_id = body.session_id or str(uuid4())

        if not in_scope:
            yield f'event: answer\ndata: {json.dumps({"answer": OUT_OF_SCOPE_REPLY, "facts": [], "session_id": session_id})}\n\n'
            return

        if not specific_enough:
            yield f'event: answer\ndata: {json.dumps({"answer": ORIENTATION_RESPONSE, "facts": [], "session_id": session_id})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "contacting"}\n\n'

        # 3. Resolve session + standalone rewrite
        history = _sessions.get(session_id, [])
        final_query = query
        if history:
            try:
                final_query = await rewrite_standalone(query, history)
                logger.info("Rewrote query: %r → %r", query, final_query)
            except Exception as e:
                logger.warning("Rewrite failed, using original: %s", e)

        yield 'event: progress\ndata: {"key": "querying_ai"}\n\n'

        # 4. Stage A: topic breadth check (routing + selection only, no synthesis)
        overview = False
        try:
            l1_topics = await knowledge_client.get_topics(final_query)
            topic_count, _labels = _count_topics(l1_topics)
            if topic_count > MAX_TOPIC_PATHS:
                overview = True
                logger.info("Broad query (%d topics after consolidation) — overview mode", topic_count)
        except Exception as e:
            logger.warning("Topics check failed, skipping breadth detection: %s", e)

        # 5. Stage B: full synthesis (overview prompt when broad)
        try:
            result = await knowledge_client.search(final_query, overview=overview)
        except Exception as e:
            logger.error("Knowledge service error: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": "Knowledge service unavailable"})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "processing"}\n\n'

        # 6. Update session history
        answer = result.get("answer", "")
        history = history + [{"q": query, "a": answer}]
        _sessions[session_id] = history[-_MAX_HISTORY:]

        if overview:
            answer = BROAD_QUERY_PREFIX + answer

        payload = {
            "answer": answer,
            "facts": result.get("facts", []),
            "session_id": session_id,
        }
        if sanitize_warning:
            payload["warning"] = sanitize_warning
        yield f'event: answer\ndata: {json.dumps(payload)}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
