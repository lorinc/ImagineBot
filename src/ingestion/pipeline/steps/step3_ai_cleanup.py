"""
Step 3 — AI header cleanup using Gemini Flash Lite.

Input:  data/pipeline/<run_id>/01_baseline_md/<stem>.md  +  <stem>_styles.json
Output: data/pipeline/<run_id>/02_ai_cleaned/<stem>.md

IMPORTANT: The prompt explicitly preserves tables — table_to_prose (Step 4)
runs after this step, not before.
"""

import json
import re
import requests
from pathlib import Path
from ..config import GEMINI_MODEL, GEMINI_API_KEY_FILE, MAX_DOCUMENT_SIZE_FOR_AI


_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{1000,}={0,2}")
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=]+\)")


def _load_api_key() -> str:
    if GEMINI_API_KEY_FILE.exists():
        for line in GEMINI_API_KEY_FILE.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    import os
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            f"GEMINI_API_KEY not found in {GEMINI_API_KEY_FILE} or environment"
        )
    return key


def _strip_images(text: str) -> str:
    text = _IMAGE_PATTERN.sub("", text)
    text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "", text)
    return text


def _has_image_data(text: str) -> bool:
    return "data:image/" in text or ";base64," in text or bool(_BASE64_PATTERN.search(text))


def _call_gemini(api_key: str, markdown: str, styles: list[dict]) -> str:
    style_block = ""
    if styles:
        style_block = f"\nFont-size metadata:\n```json\n{json.dumps(styles, indent=2)}\n```\n"

    prompt = f"""You are an expert document formatter optimizing documents for RAG systems.

Your task:
1. Fix header hierarchy based on font sizes (larger = higher level)
2. Ensure consistent header formatting throughout
3. Fix obvious typos or formatting inconsistencies
4. Maintain all original content and meaning
5. Preserve tables, lists, and all other formatting exactly as-is
6. Ensure headers are descriptive and searchable

Raw Markdown:
```markdown
{markdown}
```
{style_block}
Output only the cleaned Markdown. Do not add explanations or comments."""

    if len(prompt) > 500_000:
        raise ValueError(f"Prompt too large ({len(prompt):,} chars) — aborting")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models"
        f"/{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=120)
    resp.raise_for_status()

    result = resp.json()
    candidate = result["candidates"][0]
    if candidate.get("finishReason") not in ("STOP", "UNKNOWN", None):
        print(f"  WARNING: Gemini finish_reason={candidate.get('finishReason')} — output may be truncated")

    return candidate["content"]["parts"][0]["text"]


def run(run_dir: Path, stems: list[str]) -> list[str]:
    """
    Apply AI header cleanup to each stem in 01_baseline_md/.
    Returns list of stems successfully cleaned.
    """
    print("=== Step 3: AI Header Cleanup ===")

    in_dir = run_dir / "01_baseline_md"
    out_dir = run_dir / "02_ai_cleaned"
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = _load_api_key()

    cleaned = []
    for stem in stems:
        out_path = out_dir / f"{stem}.md"
        if out_path.exists():
            print(f"  Skipping (already cleaned): {stem}")
            cleaned.append(stem)
            continue

        md_path = in_dir / f"{stem}.md"
        if not md_path.exists():
            print(f"  MISSING baseline: {stem}.md — skipping")
            continue

        styles_path = in_dir / f"{stem}_styles.json"
        styles = json.loads(styles_path.read_text()) if styles_path.exists() else []

        raw = md_path.read_text(encoding="utf-8")
        md_clean = _strip_images(raw)

        if _has_image_data(md_clean):
            raise RuntimeError(
                f"SAFETY GATE: image data still present in '{stem}' after stripping. "
                f"File requires manual investigation before pipeline can continue. "
                f"Source: {md_path}"
            )

        if len(md_clean) > MAX_DOCUMENT_SIZE_FOR_AI:
            print(f"  {stem}: too large ({len(md_clean):,} chars) — skipping AI, copying as-is")
            out_path.write_text(md_clean, encoding="utf-8")
            cleaned.append(stem)
            continue

        print(f"  Cleaning: {stem} ({len(md_clean):,} chars) ...", end=" ", flush=True)
        try:
            result = _call_gemini(api_key, md_clean, styles)
            out_path.write_text(result, encoding="utf-8")
            print(f"done ({len(result):,} chars)")
            cleaned.append(stem)
        except Exception as e:
            print(f"FAILED: {e}")

    print(f"  Step 3 complete: {len(cleaned)} file(s) in {out_dir}\n")
    return cleaned
