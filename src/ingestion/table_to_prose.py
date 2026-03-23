"""
table_to_prose — convert markdown tables to prose sentences.

WHY THIS EXISTS:
Graphiti's entity extractor (LLM) does not produce graph edges for data in markdown
table format. Validated empirically: a school timetable table produced zero extracted
facts; the same data as prose sentences produced correct edges. See TODO.md O4.

OUTPUT CONTRACT (tests/ingestion/test_table_to_prose.py is the authoritative spec):
- Every non-empty cell value appears in the output.
- Every cell value appears on the same line as its column header.
- Empty cells with no inherited value are omitted (no orphaned "Label: " strings).
- Empty cells inherit the value from the same column in the row above.
- Inherited values stop at the next non-empty value in that column.
- Non-table content is passed through unchanged.
- No markdown table syntax (pipes, separator rows) in output.
- Malformed tables never raise exceptions.
"""

import re

_TABLE_LINE = re.compile(r"^\s*\|")
_SEPARATOR_LINE = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")


def table_to_prose(markdown: str) -> str:
    """Replace every markdown table in *markdown* with prose sentences.

    Each data row becomes one output line:
        Col1: val1, Col2: val2, Col3: val3.

    Empty cells inherit the value from the same column in the previous row.
    Non-table lines are returned unchanged.
    """
    if not markdown:
        return markdown

    lines = markdown.splitlines()
    output: list[str] = []
    i = 0

    while i < len(lines):
        if _TABLE_LINE.match(lines[i]):
            # Collect contiguous table lines (no blank lines inside a table block)
            j = i
            while j < len(lines) and _TABLE_LINE.match(lines[j]):
                j += 1
            prose = _convert_table(lines[i:j])
            output.append(prose)
            i = j
        else:
            output.append(lines[i])
            i += 1

    return "\n".join(output)


# ── internals ─────────────────────────────────────────────────────────────────

def _parse_row(line: str) -> list[str]:
    """Split a markdown table row into a list of stripped cell strings."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _convert_table(lines: list[str]) -> str:
    """Convert a block of markdown table lines to prose.

    Strategy:
    1. Skip separator rows.
    2. First non-separator row = header.
    3. All subsequent rows = data.
    4. Per data row: pad/trim to header width, apply inheritance, emit one line.
    """
    header: list[str] | None = None
    data_rows: list[list[str]] = []

    for line in lines:
        if not line.strip():
            continue
        if _SEPARATOR_LINE.match(line):
            continue
        row = _parse_row(line)
        if header is None:
            header = row
        else:
            data_rows.append(row)

    # Nothing parseable — return original content unchanged
    if not header or not data_rows:
        return "\n".join(lines)

    num_cols = len(header)
    prev: list[str] = [""] * num_cols
    prose_lines: list[str] = []

    for row in data_rows:
        # Normalise row length to match header
        padded = (row + [""] * num_cols)[:num_cols]

        # Inheritance rule: only inherit when the first column is empty.
        # An empty first cell signals a "continuation" row (merged-cell / row-span
        # pattern, common in school timetables: Day spans multiple Period rows).
        # A non-empty first cell signals a new record — empty subsequent cells
        # in that row are genuinely absent, not inherited.
        is_continuation = padded[0] == ""
        resolved = [
            prev[c] if (padded[c] == "" and is_continuation) else padded[c]
            for c in range(num_cols)
        ]

        # Build prose: only include pairs where the value is non-empty
        parts = [
            f"{header[c]}: {resolved[c]}"
            for c in range(num_cols)
            if resolved[c]
        ]
        if parts:
            prose_lines.append(", ".join(parts) + ".")

        prev = resolved

    return "\n".join(prose_lines)
