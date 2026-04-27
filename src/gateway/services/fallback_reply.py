import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config import GCP_PROJECT, REGION, MODEL
from services.prompts import gate3_fallback_prompt

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    global _model
    if _model is None:
        vertexai.init(project=GCP_PROJECT, location=REGION)
        _model = GenerativeModel(MODEL)
    return _model


async def fallback_reply(query: str, override_context: bool) -> str:
    prompt = gate3_fallback_prompt(query)
    config = GenerationConfig(temperature=0.7)
    response = await _get_model().generate_content_async(prompt, generation_config=config)
    return response.text.strip()
