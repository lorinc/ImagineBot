from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int
    comment: str | None = None
