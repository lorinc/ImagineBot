"""
Runtime configuration for the ingestion Cloud Run Job.

All values read from environment variables; defaults are project-specific constants.
Override via env vars when deploying to Cloud Run (see job/Dockerfile and R-8 deploy commands).
"""
import os

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "1Fdq41yQyDlXgKUSyDBpGqCxo686ieXg3")
SOURCE_ID = os.getenv("SOURCE_ID", "tech_poc")
GCS_BUCKET = os.getenv("GCS_BUCKET", "img-dev-index")
OAUTH_TOKEN_PATH = os.getenv("OAUTH_TOKEN_PATH", "oauth/token.pickle")
