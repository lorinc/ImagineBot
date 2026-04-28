import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL

_PROMPT = """\
Rewrite the user message into an ideal search question for a school information assistant.

The assistant's knowledge base covers:
{corpus_summary}

Use the vocabulary from the outline above when it accurately reflects what the user asked \
— precise terminology improves retrieval.

Rules for the ideal question:
1. Self-contained: resolve all pronouns and implicit references using the conversation history. \
("What about teachers?" with prior context about homework → "What is the homework correction \
policy for classroom teachers?")
2. Interrogative form: output a proper question ("What is...", "How does...", "Who is \
responsible for..."). Convert confirmations ("yes, go ahead" after a clarification question \
→ the full question the user confirmed) and commands ("Tell me about fees" → "What are the \
school fees?").
3. Single topic: if the follow-up shifts to a new topic, cover only the new topic.
4. Explicit qualifiers only: include constraints the user stated; do not add constraints \
they did not mention.

Output ONLY the rewritten question, nothing else.

Conversation history:
{history}

User message: {query}"""

_GENERALIZE_PROMPT = """\
The following question contains overly specific constraints that are unlikely to appear \
verbatim in a school policy document. Rewrite it as a more general question that covers \
the core topic, removing constraints like employment dates, contract types, or edge-case \
conditions. Output ONLY the rewritten question, nothing else.

Question: {query}"""

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


async def rewrite_standalone(query: str, history: list[dict], corpus_summary: str = "") -> str:
    config = GenerationConfig(temperature=0.0)
    response = await _get_model().generate_content_async(
        _PROMPT.format(
            corpus_summary=corpus_summary or "School policies and procedures.",
            history=_format_history(history),
            query=query,
        ),
        generation_config=config,
    )
    rewritten = response.text.strip()
    return rewritten if rewritten else query


async def generalize_overspecified(query: str) -> str:
    """Strip over-specific constraints from a query, returning a more general form."""
    config = GenerationConfig(temperature=0.0)
    response = await _get_model().generate_content_async(
        _GENERALIZE_PROMPT.format(query=query),
        generation_config=config,
    )
    generalized = response.text.strip()
    return generalized if generalized else query
