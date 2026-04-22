import json
import logging
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import OUT_OF_SCOPE_REPLY
from services.sanitize import sanitize
from services.scope_gate import is_in_scope
from services.rewrite import rewrite_standalone
from services import knowledge_client

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store: session_id -> last 10 turns [{q, a}]
_sessions: dict[str, list[dict]] = {}
_MAX_HISTORY = 10


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/chat")
async def chat(body: ChatRequest):
    async def generate():
        # 1. Sanitize
        try:
            query = sanitize(body.message)
        except ValueError as e:
            yield f'event: error\ndata: {json.dumps({"error": str(e)})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "received"}\n\n'

        # 2. Scope gate
        try:
            in_scope = await is_in_scope(query)
        except Exception as e:
            logger.error("Scope gate error: %s", e)
            in_scope = True  # fail open — don't block on classifier failure

        if not in_scope:
            session_id = body.session_id or str(uuid4())
            yield f'event: answer\ndata: {json.dumps({"answer": OUT_OF_SCOPE_REPLY, "facts": [], "session_id": session_id})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "contacting"}\n\n'

        # 3. Resolve session + standalone rewrite
        session_id = body.session_id or str(uuid4())
        history = _sessions.get(session_id, [])

        final_query = query
        if history:
            try:
                final_query = await rewrite_standalone(query, history)
                logger.info("Rewrote query: %r → %r", query, final_query)
            except Exception as e:
                logger.warning("Rewrite failed, using original: %s", e)

        yield 'event: progress\ndata: {"key": "querying_ai"}\n\n'

        # 4. Call knowledge service
        try:
            result = await knowledge_client.search(final_query)
        except Exception as e:
            logger.error("Knowledge service error: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": "Knowledge service unavailable"})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "processing"}\n\n'

        # 5. Update session history
        history = history + [{"q": query, "a": result.get("answer", "")}]
        _sessions[session_id] = history[-_MAX_HISTORY:]

        payload = {
            "answer": result.get("answer", ""),
            "facts": result.get("facts", []),
            "session_id": session_id,
        }
        yield f'event: answer\ndata: {json.dumps(payload)}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
