import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GATEWAY_SERVICE_URL = os.environ.get("GATEWAY_SERVICE_URL", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

_ALLOWED_EMAILS_PATH = Path("/secrets/allowed_emails/ALLOWED_EMAILS")


def _load_allowed_emails() -> list[str]:
    if not _ALLOWED_EMAILS_PATH.exists():
        return []
    return [e.strip() for e in _ALLOWED_EMAILS_PATH.read_text().strip().split(",") if e.strip()]


ALLOWED_EMAILS: list[str] = _load_allowed_emails()


def _verify_google_token(token: str) -> dict:
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, grequests.Request(), GOOGLE_CLIENT_ID)


async def _get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth_header[7:]
    try:
        claims = _verify_google_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if claims.get("email", "") not in ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Access denied")
    return claims


def _get_identity_token(audience: str) -> str:
    """Get Cloud Run service-account identity token for service-to-service auth."""
    import google.auth.transport.requests
    import google.oauth2.id_token

    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


_HERE = Path(__file__).parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(_HERE / "templates"))


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "google_client_id": GOOGLE_CLIENT_ID}
    )


@app.post("/chat")
async def chat(body: ChatRequest, _user: dict = Depends(_get_current_user)):
    if not body.message.strip():
        return JSONResponse(status_code=400, content={"error": "Message cannot be empty"})

    async def generate():
        try:
            token = _get_identity_token(GATEWAY_SERVICE_URL)
        except Exception as e:
            logger.error("Identity token error: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": "Authentication error"})}\n\n'
            return

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{GATEWAY_SERVICE_URL}/chat",
                    json={"message": body.message, "session_id": body.session_id},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=180.0,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n"
                        else:
                            yield "\n"
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gateway returned %s: %s",
                e.response.status_code,
                e.response.text,
            )
            yield f'event: error\ndata: {json.dumps({"error": "Gateway error"})}\n\n'
        except Exception as e:
            logger.error("Unexpected error calling gateway: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": "Service temporarily unavailable"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream")
