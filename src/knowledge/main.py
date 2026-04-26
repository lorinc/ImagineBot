import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import vertexai
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from indexer.config import GCP_PROJECT, REGION, MODEL_QUALITY, MODEL_STRUCTURAL
from indexer.llm import get_model
from indexer.multi import query_multi_index, render_routing_outline
from indexer.observability import get_query_spans, init_query_context, reset_query_context
from models import Fact, SearchRequest, SearchResponse, TopicNode, TopicsRequest, TopicsResponse

KNOWLEDGE_INDEX_PATH = Path(
    os.environ.get("KNOWLEDGE_INDEX_PATH", "/data/index/multi_index.json")
)

SERVICE_VERSION = os.getenv("MODULE_GIT_REV", "unknown")

_multi_index: dict | None = None
_structural_model = None
_quality_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _multi_index, _structural_model, _quality_model

    vertexai.init(project=GCP_PROJECT, location=REGION)

    if not KNOWLEDGE_INDEX_PATH.exists():
        raise RuntimeError(
            f"Multi-index not found at {KNOWLEDGE_INDEX_PATH}. "
            "Run tools/build_index.py first."
        )

    raw = json.loads(KNOWLEDGE_INDEX_PATH.read_text(encoding="utf-8"))

    # Resolve relative index_path values relative to the multi_index.json directory.
    # build_index.py writes relative paths; absolute paths (from dev builds) pass through.
    index_dir = KNOWLEDGE_INDEX_PATH.parent
    for doc in raw.get("documents", []):
        p = Path(doc["index_path"])
        if not p.is_absolute():
            doc["index_path"] = str(index_dir / p)

    _multi_index = raw
    _structural_model = get_model(MODEL_STRUCTURAL)
    _quality_model = get_model(MODEL_QUALITY)

    yield


app = FastAPI(lifespan=lifespan)


def _build_response(result: dict) -> dict:
    synthesis_nodes = result.get("synthesis", {}).get("selected_nodes", [])
    selected_nodes = [
        {"doc_id": n["doc_id"], "node_id": n.get("scoped_id", "")}
        for n in synthesis_nodes
    ]
    facts = [
        {"fact": f.fact, "source_id": f.source_id, "valid_at": f.valid_at}
        for f in _facts_from_result(result)
    ]
    return {
        "answer": result["synthesis"]["answer"],
        "facts": facts,
        "selected_nodes": selected_nodes,
    }


def _facts_from_result(result: dict) -> list[Fact]:
    # poc1 synthesis produces plain-text answers with inline [section_id] refs,
    # not structured citations. Facts are derived from the selected nodes sent to
    # synthesis (section title + doc_id). TODO: replace with structured citation
    # extraction once synthesis prompt is updated to output JSON.
    seen: set[str] = set()
    facts: list[Fact] = []
    for n in result.get("synthesis", {}).get("selected_nodes", []):
        key = n["scoped_id"]
        if key not in seen:
            seen.add(key)
            facts.append(Fact(fact=n["title"], source_id=n["doc_id"], valid_at=None))
    return facts


@app.get("/summary")
async def summary():
    """Return the routing outline (L1 node titles + topics) for classifier prompts."""
    return {"outline": render_routing_outline(_multi_index)}


@app.post("/topics", response_model=TopicsResponse)
async def topics(req: TopicsRequest):
    """Run routing + selection only; return L1 ancestor nodes without synthesis."""
    try:
        result = await query_multi_index(
            req.query, _multi_index, _structural_model, _quality_model,
            topics_only=True,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Topics query failed: {e}")
    return TopicsResponse(l1_topics=result["l1_topics"])


@app.get("/health")
async def health():
    return {"status": "healthy", "version": SERVICE_VERSION}


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request, response: Response):
    # group_ids: stub for future permission/multi-tenant filtering — ignored for now
    trace_id = request.headers.get("X-Trace-Id", "")
    ctx_token = init_query_context(trace_id)
    try:
        result = await query_multi_index(
            req.query, _multi_index, _structural_model, _quality_model,
            overview=req.overview,
        )
        spans = get_query_spans()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Query failed: {e}")
    finally:
        reset_query_context(ctx_token)

    response.headers["X-Service-Version"] = SERVICE_VERSION
    return {**_build_response(result), "spans": spans}


@app.post("/search/stream")
async def search_stream(req: SearchRequest, request: Request):
    trace_id = request.headers.get("X-Trace-Id", "")

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        def stream_cb(span: dict) -> None:
            queue.put_nowait({"_span": span})

        ctx_token = init_query_context(trace_id, stream_cb=stream_cb)

        async def run() -> None:
            try:
                result = await query_multi_index(
                    req.query, _multi_index, _structural_model, _quality_model,
                    overview=req.overview,
                )
                queue.put_nowait({"_done": result, "_spans": get_query_spans()})
            except Exception as e:
                queue.put_nowait({"_error": str(e)})
            finally:
                reset_query_context(ctx_token)

        asyncio.create_task(run())

        while True:
            item = await queue.get()
            if "_span" in item:
                yield f"event: span\ndata: {json.dumps(item['_span'])}\n\n"
            elif "_done" in item:
                response_data = {**_build_response(item["_done"]), "spans": item["_spans"]}
                yield f"event: answer\ndata: {json.dumps(response_data)}\n\n"
                break
            else:
                yield f"event: error\ndata: {json.dumps({'error': item['_error']})}\n\n"
                break

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Service-Version": SERVICE_VERSION})
