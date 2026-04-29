"""
Pipeline configuration.

Drive folder names, model selection, local path roots.
"""

from pathlib import Path

# ── Google Drive folder names ──────────────────────────────────────────────────
DRIVE_GDOCS_FOLDER = "1-native-gdocs"   # where Step 1 writes converted Google Docs

# ── Local paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parents[3]
DOCX_DIR = PROJECT_ROOT / "data" / "docx"
PIPELINE_DIR = PROJECT_ROOT / "data" / "pipeline"

# ── AI model ───────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_API_KEY_FILE = PROJECT_ROOT / "REFERENCE_REPOS" / "DOCX2MD" / ".config"

# ── Step 3 limits ──────────────────────────────────────────────────────────────
MAX_DOCUMENT_SIZE_FOR_AI = 80_000    # characters; skip AI above this (larger docs cause Gemini hangs)

# ── Step 5 chunking ────────────────────────────────────────────────────────────
CHUNK_HEADER_LEVEL = "##"            # split on ## headings
