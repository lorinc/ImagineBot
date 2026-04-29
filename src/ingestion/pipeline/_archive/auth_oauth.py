"""
OAuth authentication for the ingestion pipeline.

Credentials file: credentials/credentials.json (Desktop OAuth client)
Token file:       credentials/token.pickle

Run directly to (re)authorize:
    python3 -m src.ingestion.pipeline.auth_oauth
"""

import os
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]

OAUTH_DIR = Path(__file__).parents[3] / "oauth"
CREDENTIALS_FILE = OAUTH_DIR / "credentials.json"
TOKEN_FILE = Path(os.getenv("OAUTH_TOKEN_PATH", str(OAUTH_DIR / "token.pickle")))


def get_credentials():
    """Return valid OAuth credentials, refreshing or re-authorizing as needed."""
    creds = None

    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing OAuth credentials...")
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Refresh failed: {e}")
        else:
            try:
                _save(creds)
            except Exception as e:
                print(f"Warning: could not persist refreshed token: {e}")
            print("Credentials refreshed.")
            return creds

    # Full browser flow — blocked in headless environments (Cloud Run sets CLOUD_RUN_JOB)
    if os.getenv("CLOUD_RUN_JOB") or os.getenv("K_SERVICE"):
        raise RuntimeError(
            "OAuth token is invalid and cannot be renewed in a headless environment.\n"
            "Operator runbook:\n"
            "  python3 -m src.ingestion.pipeline.auth_oauth   # re-authorize locally\n"
            "  gsutil cp oauth/token.pickle gs://img-dev-index/_auth/token.pickle"
        )

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_FILE}\n"
            "Copy it from REFERENCE_REPOS/DOCX2MD/credentials.json"
        )

    print("Starting OAuth browser flow...")
    print("(A URL will be printed — open it in your browser and sign in as lorinc@gmail.com)")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=False)
    _save(creds)
    print(f"Token saved to {TOKEN_FILE}")
    return creds


def _save(creds):
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)


def get_drive_service():
    return build("drive", "v3", credentials=get_credentials())


def get_docs_service():
    return build("docs", "v1", credentials=get_credentials())


if __name__ == "__main__":
    creds = get_credentials()
    print(f"Valid: {creds.valid}  Expiry: {creds.expiry}")
