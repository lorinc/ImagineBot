from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    group_ids: list[str] | None = None  # stub — future access-control filter, ignored for now
    overview: bool = False


class Fact(BaseModel):
    fact: str
    source_id: str
    valid_at: str | None = None


class SearchResponse(BaseModel):
    answer: str
    facts: list[Fact]
    selected_nodes: list[dict] = []
    spans: list[dict] = []


class TopicsRequest(BaseModel):
    query: str
    group_ids: list[str] | None = None


class TopicNode(BaseModel):
    doc_id: str
    id: str
    title: str


class TopicsResponse(BaseModel):
    l1_topics: list[TopicNode]
