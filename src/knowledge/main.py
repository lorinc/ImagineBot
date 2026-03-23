import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import vertexai
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import firestore
from pydantic import BaseModel
from vertexai.generative_models import GenerationConfig
from vertexai.preview.caching import CachedContent
from vertexai.preview.generative_models import GenerativeModel

GCP_PROJECT = os.environ["GCP_PROJECT_ID"]
REGION = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")

# Cache name refreshed from Firestore at most once every 5 minutes per instance.
_cache_name: str | None = None
_cache_checked_at: datetime | None = None
_CACHE_REFRESH_SECS = 300

_SYSTEM_PROMPT_BASE = (
    "You are a school information assistant. "
    "Answer questions using ONLY the information in the provided documents. "
    "- Cite the exact document source_id for every claim you make. "
    "- If the documents do not contain enough information to answer, set answer to exactly: "
    '"I don\'t have that information in the school documents." and citations to []. '
    "- Never invent, extrapolate, or guess."
)

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "document": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
                "required": ["document", "excerpt"],
            },
        },
    },
    "required": ["answer", "citations"],
}

db: firestore.Client | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    vertexai.init(project=GCP_PROJECT, location=REGION)
    db = firestore.Client(project=GCP_PROJECT)
    yield


app = FastAPI(lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str
    group_ids: list[str] | None = None


class Fact(BaseModel):
    fact: str
    source_id: str
    valid_at: str | None = None


class SearchResponse(BaseModel):
    answer: str
    facts: list[Fact]


def _read_cache_name_from_firestore() -> str:
    """Synchronous Firestore read — called via asyncio.to_thread."""
    doc = db.collection("config").document("context_cache").get()
    if not doc.exists:
        raise RuntimeError(
            "No context cache configured. Run tools/create_cache.py first."
        )
    return doc.to_dict()["cache_name"]


async def _get_cache_name() -> str:
    global _cache_name, _cache_checked_at
    now = datetime.now(timezone.utc)
    if (
        _cache_name
        and _cache_checked_at
        and (now - _cache_checked_at).total_seconds() < _CACHE_REFRESH_SECS
    ):
        return _cache_name
    try:
        name = await asyncio.to_thread(_read_cache_name_from_firestore)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    _cache_name = name
    _cache_checked_at = now
    return _cache_name


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    name = await _get_cache_name()

    try:
        cached_content = await asyncio.to_thread(CachedContent.get, name)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Context cache unavailable: {e}")

    # system_instruction cannot be used alongside cached_content (SDK constraint).
    # The base system prompt is baked into the cache at creation time (tools/create_cache.py).
    # Per-request group_ids filtering is appended to the user query.
    model = GenerativeModel.from_cached_content(cached_content=cached_content)

    query = req.query
    if req.group_ids:
        query += (
            f"\n\n[Answer only from these documents: {', '.join(req.group_ids)}. "
            "Ignore information from any other document.]"
        )

    try:
        response = await model.generate_content_async(
            query,
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Generation failed: {e}")

    try:
        data = json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        raise HTTPException(status_code=500, detail=f"Malformed model response: {e}")

    facts = [
        Fact(fact=c["excerpt"], source_id=c["document"], valid_at=None)
        for c in data.get("citations", [])
    ]

    return SearchResponse(answer=data["answer"], facts=facts)


@app.post("/search/stream")
async def search_stream(req: SearchRequest):
    async def generate():
        yield 'event: progress\ndata: {"key": "cache_lookup"}\n\n'

        try:
            name = await _get_cache_name()
            cached_content = await asyncio.to_thread(CachedContent.get, name)
        except HTTPException as e:
            yield f'event: error\ndata: {json.dumps({"error": e.detail})}\n\n'
            return
        except Exception as e:
            yield f'event: error\ndata: {json.dumps({"error": f"Context cache unavailable: {e}"})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "querying_ai"}\n\n'

        model = GenerativeModel.from_cached_content(cached_content=cached_content)
        query = req.query
        if req.group_ids:
            query += (
                f"\n\n[Answer only from these documents: {', '.join(req.group_ids)}. "
                "Ignore information from any other document.]"
            )

        try:
            response = await model.generate_content_async(
                query,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                ),
            )
        except Exception as e:
            yield f'event: error\ndata: {json.dumps({"error": f"Generation failed: {e}"})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "processing"}\n\n'

        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, AttributeError) as e:
            yield f'event: error\ndata: {json.dumps({"error": f"Malformed model response: {e}"})}\n\n'
            return

        facts = [
            {"fact": c["excerpt"], "source_id": c["document"], "valid_at": None}
            for c in data.get("citations", [])
        ]
        yield f'event: answer\ndata: {json.dumps({"answer": data["answer"], "facts": facts})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
