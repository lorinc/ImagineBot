import os

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
SERVICE_VERSION = os.getenv("MODULE_GIT_REV", "unknown")
REGION = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")
KNOWLEDGE_SERVICE_URL = os.environ.get("KNOWLEDGE_SERVICE_URL", "")
if not KNOWLEDGE_SERVICE_URL:
    raise RuntimeError("KNOWLEDGE_SERVICE_URL is not set")
MODEL = "gemini-2.5-flash-lite"

# Breadth detection: how many distinct L1 topic groups trigger overview mode.
# Sibling consolidation: if a doc contributes >= this many L1 sections, collapse to doc-level.
# Both are empirically tunable — see src/knowledge/TODO.md.
MAX_TOPIC_PATHS = 5
SIBLING_COLLAPSE_THRESHOLD = 3

# Gate 1 override: phrases that signal "retry my previous OOS question" rather than a new query.
# All lowercase — matched against query.lower(). Message must also be < 15 words.
OVERRIDE_TRIGGER_PHRASES = [
    "look it up",
    "look that up",
    "check",
    "search",
    "check anyway",
    "try anyway",
    "just search",
    "check the docs",
    "in the documentation",
    "that is about the school",
    "please check",
    "please search",
    "please look",
]
