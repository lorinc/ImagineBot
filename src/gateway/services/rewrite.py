import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL

_PROMPT = """\
Rewrite the follow-up question as a fully self-contained question using the \
conversation history below. Output ONLY the rewritten question, nothing else.

History:
{history}

Follow-up: {query}"""

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        vertexai.init(project=GCP_PROJECT, location=REGION)
        _model = GenerativeModel(MODEL)
    return _model


def _format_history(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        lines.append(f"Q: {t['q']}")
        lines.append(f"A: {t['a'][:200]}")  # truncate long answers
    return "\n".join(lines)


async def rewrite_standalone(query: str, history: list[dict]) -> str:
    config = GenerationConfig(temperature=0.0)
    response = await _get_model().generate_content_async(
        _PROMPT.format(history=_format_history(history), query=query),
        generation_config=config,
    )
    rewritten = response.text.strip()
    return rewritten if rewritten else query
