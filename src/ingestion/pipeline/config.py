"""
Pipeline configuration.
"""

from pathlib import Path

# ── Google Drive folder names ──────────────────────────────────────────────────
DRIVE_GDOCS_FOLDER = "1-native-gdocs"   # where Step 1 writes converted Google Docs

# ── AI model ───────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_API_KEY_FILE = Path(__file__).parents[3] / "REFERENCE_REPOS" / "DOCX2MD" / ".config"

# ── Step 3 limits ──────────────────────────────────────────────────────────────
MAX_DOCUMENT_SIZE_FOR_AI = 80_000    # characters; skip AI above this (replaced by chunking in Phase 1 item 19)

# ── Step 5 chunking ────────────────────────────────────────────────────────────
CHUNK_HEADER_LEVEL = "##"            # split on ## headings
