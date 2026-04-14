"""llm.py — Vertex AI client, async call wrapper, semaphore, and response schemas."""

import asyncio
import time

import vertexai
from google.api_core.exceptions import ResourceExhausted
from vertexai.generative_models import GenerationConfig, GenerativeModel

from .config import GCP_PROJECT, REGION, MODEL_QUALITY, _SUMMARISE_CONCURRENCY

# ── Client init ───────────────────────────────────────────────────────────────

def _init_vertex() -> None:
    vertexai.init(project=GCP_PROJECT, location=REGION)


def get_model(model_name: str = MODEL_QUALITY) -> GenerativeModel:
    _init_vertex()
    m = GenerativeModel(model_name)
    m._name = model_name  # remembered for cost tracking
    return m


# ── Async call wrapper ────────────────────────────────────────────────────────

async def llm_call(
    model: GenerativeModel,
    prompt: str,
    response_schema: dict | None = None,
) -> tuple[str, int, dict]:
    """Single LLM call. Returns (response_text, latency_ms, usage).

    usage = {input_tokens: int, output_tokens: int} — may be empty if unavailable.
    Retries on 429 ResourceExhausted with exponential backoff (5s, 10s, 20s, 40s).
    """
    t0 = time.monotonic()
    config = GenerationConfig(
        response_mime_type="application/json" if response_schema else "text/plain",
        response_schema=response_schema,
        temperature=0.0,
    )
    delay = 5
    for attempt in range(5):
        try:
            response = await model.generate_content_async(prompt, generation_config=config)
            break
        except ResourceExhausted:
            if attempt == 4:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    ms = int((time.monotonic() - t0) * 1000)

    usage: dict = {}
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        usage = {
            "input_tokens":  getattr(um, "prompt_token_count",     0) or 0,
            "output_tokens": getattr(um, "candidates_token_count", 0) or 0,
        }

    return response.text, ms, usage


# ── Semaphore ─────────────────────────────────────────────────────────────────

_SEM: asyncio.Semaphore | None = None


def get_sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(_SUMMARISE_CONCURRENCY)
    return _SEM


# ── Response schemas ──────────────────────────────────────────────────────────

TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "topics": {"type": "string"},
    },
    "required": ["title", "topics"],
}

SPLIT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "topics": {"type": "string"},
                },
                "required": ["title", "start", "topics"],
            },
        }
    },
    "required": ["sections"],
}

MERGE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "should_merge": {"type": "boolean"},
    },
    "required": ["should_merge"],
}

NODE_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning": {"type": "string"},
    },
    "required": ["selected_ids", "reasoning"],
}

DOC_ROUTING_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_doc_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning": {"type": "string"},
    },
    "required": ["selected_doc_ids", "reasoning"],
}
