"""config.py — centralised constants for the PageIndex indexer."""

import os

# ── GCP ──────────────────────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
REGION      = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")

# ── Models ───────────────────────────────────────────────────────────────────

# Structural tasks (split boundaries, merge check) — cheaper, faster
MODEL_STRUCTURAL = "gemini-2.5-flash-lite"
# Quality tasks (summaries, query synthesis) — better reasoning
MODEL_QUALITY    = "gemini-2.5-flash"

# ── Concurrency ───────────────────────────────────────────────────────────────

# Max concurrent LLM calls during build
_SUMMARISE_CONCURRENCY = 12

# ── Node size thresholds ──────────────────────────────────────────────────────

# Characters of full text (all content in leaf nodes)
MAX_NODE_CHARS = 5000
MIN_NODE_CHARS = 1500

# ── Pricing ───────────────────────────────────────────────────────────────────

# Estimated Vertex AI pricing (USD per 1M tokens).
# Verify against https://cloud.google.com/vertex-ai/generative-ai/pricing before use.
PRICING_PER_1M_USD: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash":      {"input": 0.15,  "output": 0.60},
}
