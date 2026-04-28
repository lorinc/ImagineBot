import json
from dataclasses import dataclass, field

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL


@dataclass
class ClassifyResult:
    in_scope: bool
    query_type: str  # "answerable" | "underspecified" | "overspecified" | "multiple"
    sub_questions: list[str] = field(default_factory=list)
    missing_variable: str | None = None


_PROMPT = """\
You are a classifier for a school information assistant.

The assistant has access to school documents covering:
{corpus_summary}

Given the question below, output JSON with these fields:
- "in_scope": true if the question is about this school — its policies, procedures, rules, \
staff, students, events, or any topic referenced in the document outline above; false for \
unrelated topics (recipes, stock prices, general trivia, etc.)
- "query_type": one of:
  - "answerable" — the question has a clear topic anchor that can be searched \
(e.g. "dress code", "fire drill", "fees", "pick-up time", "what happens if my child is sick")
  - "underspecified" — the question is too vague to retrieve a meaningful answer because a \
required parameter is missing (e.g. "What are the rules?", "What do I need to know?", \
"How does it work?", "Tell me about the school"). Only use this when no topic is identified.
  - "overspecified" — the question has overly specific constraints unlikely to appear in \
policy documents (e.g. "sick leave policy for primary teachers hired before 2020 on probation"). \
The core topic is clear but the constraints are too narrow.
  - "multiple" — the message contains two or more distinct questions that require separate \
lookups (e.g. "My son lost his hoodie. Who should I contact?")
- "sub_questions": list of standalone questions when query_type is "multiple"; empty list otherwise
- "missing_variable": short phrase naming the missing parameter when query_type is \
"underspecified" (e.g. "the specific topic or area", "the school level"); null otherwise

{prior_exchange}Question: {query}"""


def _prior_exchange_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["Prior exchange:"]
    for turn in history:
        lines.append(f"User: {turn['q']}")
        lines.append(f"Assistant: {turn['a']}")
    lines.append("")
    return "\n".join(lines) + "\n"


_SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "query_type": {
            "type": "string",
            "enum": ["answerable", "underspecified", "overspecified", "multiple"],
        },
        "sub_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_variable": {"type": "string", "nullable": True},
    },
    "required": ["in_scope", "query_type", "sub_questions"],
}

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        vertexai.init(project=GCP_PROJECT, location=REGION)
        _model = GenerativeModel(MODEL)
    return _model


async def classify(query: str, corpus_summary: str, history: list[dict] | None = None) -> ClassifyResult:
    """Return ClassifyResult. Fails open (answerable) on error."""
    config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=_SCHEMA,
        temperature=0.0,
    )
    response = await _get_model().generate_content_async(
        _PROMPT.format(
            corpus_summary=corpus_summary,
            prior_exchange=_prior_exchange_block(history or []),
            query=query,
        ),
        generation_config=config,
    )
    raw = json.loads(response.text)
    return ClassifyResult(
        in_scope=raw.get("in_scope", True),
        query_type=raw.get("query_type", "answerable"),
        sub_questions=raw.get("sub_questions") or [],
        missing_variable=raw.get("missing_variable") or None,
    )
