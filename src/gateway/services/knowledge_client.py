import asyncio
import json
import time

import httpx

from config import KNOWLEDGE_SERVICE_URL

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_TTL = 55 * 60  # tokens valid 1 h; refresh 5 min early


def _fetch_identity_token_sync(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token

    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


async def _get_identity_token(audience: str) -> str:
    cached = _TOKEN_CACHE.get(audience)
    if cached and time.monotonic() < cached[1]:
        return cached[0]
    token = await asyncio.get_running_loop().run_in_executor(
        None, _fetch_identity_token_sync, audience
    )
    _TOKEN_CACHE[audience] = (token, time.monotonic() + _TOKEN_TTL)
    return token


async def get_summary(trace_id: str = "") -> str:
    """Fetch the L1 routing outline from the knowledge service for classifier prompts."""
    token = await _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{KNOWLEDGE_SERVICE_URL}/summary",
            headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json().get("outline", "")


async def get_topics(query: str, trace_id: str = "") -> list[dict]:
    """Call knowledge /topics; return l1_topics list. Skips synthesis."""
    token = await _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KNOWLEDGE_SERVICE_URL}/topics",
            json={"query": query, "group_ids": None},
            headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json().get("l1_topics", [])


async def search(query: str, overview: bool = False, trace_id: str = "") -> tuple[dict, str]:
    """Call knowledge /search, return (data, service_version). Raises on HTTP error."""
    token = await _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KNOWLEDGE_SERVICE_URL}/search",
            json={"query": query, "group_ids": None, "overview": overview},
            headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
            timeout=120.0,
        )
        response.raise_for_status()
        knowledge_version = response.headers.get("x-service-version", "unknown")
        return response.json(), knowledge_version


async def search_stream(query: str, trace_id: str = "", overview: bool = False):
    """Yield (event_type, payload, knowledge_version) from /search/stream."""
    token = await _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST", f"{KNOWLEDGE_SERVICE_URL}/search/stream",
            json={"query": query, "group_ids": None, "overview": overview},
            headers={"Authorization": f"Bearer {token}", "X-Trace-Id": trace_id},
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            knowledge_version = response.headers.get("x-service-version", "unknown")
            event_type, data_str = "message", ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:]
                elif line == "" and data_str:
                    yield event_type, json.loads(data_str), knowledge_version
                    event_type, data_str = "message", ""
