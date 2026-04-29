"""
Runtime configuration for the ingestion Cloud Run Job.

All values read from environment variables; defaults are project-specific constants.
Override via env vars when deploying to Cloud Run.
"""
import os

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3")
SOURCE_ID = os.getenv("SOURCE_ID", "tech_poc")
GCS_BUCKET = os.getenv("GCS_BUCKET", "img-dev-index")
TRIGGER = os.getenv("INGESTION_TRIGGER", "scheduler")
DEBUG_MODE = os.getenv("DEBUG_MODE", "").lower() == "true"
