import json

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL

_PROMPT = """\
You are a classifier for a school information assistant.

The assistant has access to school documents covering:
{corpus_summary}

Given the question below, output JSON with two fields:
- "in_scope": true if the question is about this school — its policies, procedures, rules, \
staff, students, events, or any topic referenced in the document outline above; false for \
unrelated topics (recipes, stock prices, general trivia, etc.)
- "specific_enough": true if the question has a clear topic anchor that can be searched \
(e.g. "dress code", "fire drill", "balls", "fees", "pick-up time", "what happens if my child \
is sick"); false if the question is too vague to retrieve a meaningful answer \
(e.g. "What are the rules?", "What do I need to know?", "How does it work?", \
"Tell me about the school", "What is important?")

Question: {query}"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "specific_enough": {"type": "boolean"},
    },
    "required": ["in_scope", "specific_enough"],
}

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        vertexai.init(project=GCP_PROJECT, location=REGION)
        _model = GenerativeModel(MODEL)
    return _model


async def classify(query: str, corpus_summary: str) -> tuple[bool, bool]:
    """Return (in_scope, specific_enough). Fails open on error."""
    config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        temperature=0.0,
    )
    response = await _get_model().generate_content_async(
        _PROMPT.format(corpus_summary=corpus_summary, query=query),
        generation_config=config,
    )
    result = json.loads(response.text)
    return result.get("in_scope", True), result.get("specific_enough", True)
