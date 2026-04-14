"""PageIndex indexer package."""

from .config import MODEL_QUALITY, MODEL_STRUCTURAL, PRICING_PER_1M_USD
from .llm import get_model

__all__ = ["get_model", "MODEL_QUALITY", "MODEL_STRUCTURAL", "PRICING_PER_1M_USD"]
