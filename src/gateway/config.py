import os

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "img-dev-490919")
REGION = os.environ.get("VERTEX_AI_LOCATION", "europe-west1")
KNOWLEDGE_SERVICE_URL = os.environ.get("KNOWLEDGE_SERVICE_URL", "")
MODEL = "gemini-2.5-flash-lite"

OUT_OF_SCOPE_REPLY = (
    "I can only answer questions about school policies and procedures. "
    "Please ask me about school rules, staff responsibilities, student welfare, "
    "or administrative operations."
)
