import httpx

from config import KNOWLEDGE_SERVICE_URL


def _get_identity_token(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token

    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


async def get_summary() -> str:
    """Fetch the L1 routing outline from the knowledge service for classifier prompts."""
    token = _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{KNOWLEDGE_SERVICE_URL}/summary",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json().get("outline", "")


async def get_topics(query: str) -> list[dict]:
    """Call knowledge /topics; return l1_topics list. Skips synthesis."""
    token = _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KNOWLEDGE_SERVICE_URL}/topics",
            json={"query": query, "group_ids": None},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json().get("l1_topics", [])


async def search(query: str, overview: bool = False) -> dict:
    """Call knowledge /search, return {answer, facts}. Raises on HTTP error."""
    token = _get_identity_token(KNOWLEDGE_SERVICE_URL)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KNOWLEDGE_SERVICE_URL}/search",
            json={"query": query, "group_ids": None, "overview": overview},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()
