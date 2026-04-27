from contextlib import asynccontextmanager

import vertexai
from fastapi import FastAPI

from config import GCP_PROJECT, REGION
from routers.chat import router as chat_router, start_session_sweeper


@asynccontextmanager
async def lifespan(app: FastAPI):
    vertexai.init(project=GCP_PROJECT, location=REGION)
    sweeper = start_session_sweeper()
    yield
    sweeper.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "healthy"}
