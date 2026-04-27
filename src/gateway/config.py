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

OUT_OF_SCOPE_REPLY = (
    "I can only answer questions about school policies and procedures. "
    "Please ask me about school rules, staff responsibilities, student welfare, "
    "or administrative operations."
)

ORIENTATION_RESPONSE = (
    "I'd be happy to help with school information! "
    "Could you be a bit more specific about what you'd like to know? "
    "For example, you could ask about:\n\n"
    "- Daily logistics — drop-off times, attendance, late pick-up\n"
    "- Health & wellbeing — illness rules, allergies, meals\n"
    "- Behaviour & values — expectations, dress code, conflict resolution\n"
    "- Curriculum & learning — how lessons work, assessments, progress reports\n"
    "- Technology — device policies, online safety\n"
    "- Fees & enrolment — payment schedules, what's included\n\n"
    "What would you like to know about?"
)

BROAD_QUERY_PREFIX = (
    "Your question covers several school policy areas. "
    "Here's a high-level overview:\n\n"
)

NO_EVIDENCE_REPLY = (
    "Your question is about a school topic, but I don't have specific "
    "documentation to answer it from the knowledge base. "
    "Please contact the school office directly for this information."
)
