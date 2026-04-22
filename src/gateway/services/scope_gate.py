import json

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL

_PROMPT = """\
You are a classifier for a school policy assistant.
Output JSON only: {{"in_scope": true}} or {{"in_scope": false}}.

Is the following question about school policies, procedures, rules, staff \
responsibilities, student welfare, or administrative operations at a school?

Question: {query}"""

_SCHEMA = {
    "type": "object",
    "properties": {"in_scope": {"type": "boolean"}},
    "required": ["in_scope"],
}

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        vertexai.init(project=GCP_PROJECT, location=REGION)
        _model = GenerativeModel(MODEL)
    return _model


async def is_in_scope(query: str) -> bool:
    config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        temperature=0.0,
    )
    response = await _get_model().generate_content_async(
        _PROMPT.format(query=query),
        generation_config=config,
    )
    return json.loads(response.text).get("in_scope", True)
