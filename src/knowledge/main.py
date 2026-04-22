import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import vertexai
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from indexer.config import GCP_PROJECT, REGION, MODEL_QUALITY, MODEL_STRUCTURAL
from indexer.llm import get_model
from indexer.multi import query_multi_index

KNOWLEDGE_INDEX_PATH = Path(
    os.environ.get("KNOWLEDGE_INDEX_PATH", "/data/index/multi_index.json")
)

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


class SearchRequest(BaseModel):
    query: str
    group_ids: list[str] | None = None  # stub — future access-control filter, ignored for now


class Fact(BaseModel):
    fact: str
    source_id: str
    valid_at: str | None = None


class SearchResponse(BaseModel):
    answer: str
    facts: list[Fact]


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


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    # group_ids: stub for future permission/multi-tenant filtering — ignored for now
    try:
        result = await query_multi_index(
            req.query, _multi_index, _structural_model, _quality_model
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Query failed: {e}")

    return SearchResponse(
        answer=result["synthesis"]["answer"],
        facts=_facts_from_result(result),
    )


@app.post("/search/stream")
async def search_stream(req: SearchRequest):
    async def generate():
        yield 'event: progress\ndata: {"key": "querying_ai"}\n\n'

        try:
            result = await query_multi_index(
                req.query, _multi_index, _structural_model, _quality_model
            )
        except Exception as e:
            yield f'event: error\ndata: {json.dumps({"error": str(e)})}\n\n'
            return

        yield 'event: progress\ndata: {"key": "processing"}\n\n'

        answer = result["synthesis"]["answer"]
        facts = [
            {"fact": f.fact, "source_id": f.source_id, "valid_at": f.valid_at}
            for f in _facts_from_result(result)
        ]
        yield f'event: answer\ndata: {json.dumps({"answer": answer, "facts": facts})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
