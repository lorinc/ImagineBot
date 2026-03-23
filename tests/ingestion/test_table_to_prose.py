"""
Unit tests for table_to_prose conversion.

CRITICAL: this step is the only thing standing between markdown tables and silent
data loss in the knowledge graph. Graphiti entity extraction produces zero edges
for tabular data (validated empirically — see TODO.md O4). If this function
malfunctions, operational facts (timetables, schedules, contact info) are silently
dropped with no error and no warning.

Each test targets a distinct failure mode. Adding a new table shape? Add a test.

Output contract (implementation must satisfy all of these):
  - Every non-empty cell value appears in the output string.
  - Every cell value appears on the same line as its column header.
  - Empty cells that have no inherited value are omitted entirely (no orphaned label).
  - Empty cells that CAN inherit (cell above is non-empty) DO inherit.
  - Inherited values do not bleed past the next non-empty anchor in that column.
  - Non-table content (prose, headings) is passed through unchanged.
  - Markdown table syntax (pipes, separator rows) does not appear in output.
  - Malformed tables do not raise exceptions.
"""

import pytest
from src.ingestion.table_to_prose import table_to_prose


# ── assertion helper ──────────────────────────────────────────────────────────

def assert_cell_present(output: str, header: str, value: str) -> None:
    """Assert that header and value both appear on the same output line.

    The implementation emits one line per data row. A cell is correctly converted
    when its column header and its value are co-located on that line — otherwise
    the LLM has no context to attach the value to a concept.
    """
    assert value in output, f"Cell value {value!r} missing from output entirely.\nOutput:\n{output}"
    assert header in output, f"Column header {header!r} missing from output entirely.\nOutput:\n{output}"
    for line in output.splitlines():
        if value in line and header in line:
            return
    pytest.fail(
        f"Value {value!r} and header {header!r} never appear on the same line.\n"
        f"Output:\n{output}"
    )


# ── fixtures ──────────────────────────────────────────────────────────────────

SIMPLE_TABLE = """\
| Day | Start | End |
|-----|-------|-----|
| Monday | 9:00 | 16:40 |
| Tuesday | 8:30 | 15:00 |
"""

# Real school timetable pattern: Time × Day matrix (wide table, no empty cells)
KILIMANJARO_TIMETABLE = """\
| Time | Monday | Tuesday | Wednesday |
|------|--------|---------|-----------|
| 09:00 - 10:00 | ENGLISH | MATHS | HISTORY |
| 10:00 - 10:15 | BREAK | BREAK | BREAK |
| 10:15 - 11:15 | PRODUCT & EXCHANGE | FRENCH | ICT |
"""

# Empty cells, no inheritance (truly missing values)
SPARSE_TABLE = """\
| Day | Room | Teacher |
|-----|------|---------|
| Monday | 101 |  |
| Tuesday |  | Smith |
"""

# Empty cells that inherit from the row above (merged-cell / span pattern).
# Common in school timetables where a day spans multiple period rows.
INHERITED_TABLE = """\
| Day | Period | Activity |
|-----|--------|----------|
| Monday | Morning | Maths |
|  | Afternoon | PE |
| Tuesday | Morning | Science |
|  | Afternoon | Art |
"""

# Table embedded in a document with prose above and below
MIXED_DOCUMENT = """\
# School Schedule

Introductory paragraph about the school day.

| Day | Start |
|-----|-------|
| Monday | 9:00 |

Footer note about exceptions.
"""

MULTIPLE_TABLES = """\
| Subject | Teacher |
|---------|---------|
| Maths | Jones |

| Room | Capacity |
|------|----------|
| 101 | 30 |
"""


# ── happy path: well-formed table ─────────────────────────────────────────────

def test_simple_table_all_values_present():
    output = table_to_prose(SIMPLE_TABLE)
    assert_cell_present(output, "Day", "Monday")
    assert_cell_present(output, "Day", "Tuesday")
    assert_cell_present(output, "Start", "9:00")
    assert_cell_present(output, "Start", "8:30")
    assert_cell_present(output, "End", "16:40")
    assert_cell_present(output, "End", "15:00")


def test_simple_table_no_pipe_syntax_in_output():
    output = table_to_prose(SIMPLE_TABLE)
    assert "|" not in output, "Pipe characters must not appear in prose output"


def test_simple_table_no_separator_row_in_output():
    output = table_to_prose(SIMPLE_TABLE)
    assert "---" not in output, "Separator row must not appear in prose output"


# ── wide timetable (Time × Day matrix) ───────────────────────────────────────

def test_wide_timetable_time_column_present():
    output = table_to_prose(KILIMANJARO_TIMETABLE)
    assert_cell_present(output, "Time", "09:00 - 10:00")
    assert_cell_present(output, "Time", "10:00 - 10:15")


def test_wide_timetable_day_columns_present():
    output = table_to_prose(KILIMANJARO_TIMETABLE)
    assert_cell_present(output, "Monday", "ENGLISH")
    assert_cell_present(output, "Tuesday", "MATHS")
    assert_cell_present(output, "Wednesday", "HISTORY")
    assert_cell_present(output, "Monday", "BREAK")
    assert_cell_present(output, "Monday", "PRODUCT & EXCHANGE")


# ── empty cells (no inheritance) ─────────────────────────────────────────────

def test_empty_cell_present_values_kept():
    output = table_to_prose(SPARSE_TABLE)
    assert_cell_present(output, "Day", "Monday")
    assert_cell_present(output, "Room", "101")
    assert_cell_present(output, "Day", "Tuesday")
    assert_cell_present(output, "Teacher", "Smith")


def test_empty_cell_omitted_from_its_row():
    """An empty cell must not produce an orphaned label with no value."""
    output = table_to_prose(SPARSE_TABLE)
    monday_line = next((l for l in output.splitlines() if "Monday" in l), None)
    assert monday_line is not None, "No output line contains 'Monday'"
    # Teacher is empty for Monday — its label must not appear on the Monday line
    assert "Teacher" not in monday_line, (
        f"'Teacher' label appeared on Monday line despite empty cell:\n{monday_line}"
    )

    tuesday_line = next((l for l in output.splitlines() if "Tuesday" in l), None)
    assert tuesday_line is not None, "No output line contains 'Tuesday'"
    # Room is empty for Tuesday
    assert "Room" not in tuesday_line, (
        f"'Room' label appeared on Tuesday line despite empty cell:\n{tuesday_line}"
    )


# ── empty cells with inheritance (merged-cell pattern) ───────────────────────

def test_inherited_cell_value_in_child_row():
    """'Monday' must appear on the same line as 'Afternoon' and 'PE'."""
    output = table_to_prose(INHERITED_TABLE)
    assert_cell_present(output, "Period", "Afternoon")
    assert_cell_present(output, "Activity", "PE")

    afternoon_pe_lines = [
        l for l in output.splitlines()
        if "Afternoon" in l and "PE" in l
    ]
    assert afternoon_pe_lines, "No line contains both 'Afternoon' and 'PE'"
    assert any("Monday" in l for l in afternoon_pe_lines), (
        f"Inherited 'Monday' not found on the Afternoon/PE line(s):\n"
        + "\n".join(afternoon_pe_lines)
    )


def test_inherited_cell_does_not_bleed_into_next_anchor():
    """Tuesday rows must not carry 'Monday' from the inherited column."""
    output = table_to_prose(INHERITED_TABLE)
    science_lines = [l for l in output.splitlines() if "Science" in l]
    assert science_lines, "No line contains 'Science'"
    assert not any("Monday" in l for l in science_lines), (
        f"'Monday' leaked into Tuesday's Science line(s):\n"
        + "\n".join(science_lines)
    )


def test_all_inherited_rows_produce_output():
    output = table_to_prose(INHERITED_TABLE)
    for activity in ["Maths", "PE", "Science", "Art"]:
        assert activity in output, f"Activity {activity!r} missing from output"


def test_second_anchor_inherits_correctly():
    """Tuesday's Afternoon row must carry 'Tuesday', not 'Monday'."""
    output = table_to_prose(INHERITED_TABLE)
    art_lines = [l for l in output.splitlines() if "Art" in l]
    assert art_lines, "No line contains 'Art'"
    assert any("Tuesday" in l for l in art_lines), (
        f"'Tuesday' not found on Art line(s):\n" + "\n".join(art_lines)
    )


# ── malformed tables ──────────────────────────────────────────────────────────

def test_malformed_missing_separator_does_not_crash():
    """No separator row: first row is treated as header, rest as data."""
    malformed = """\
| Day | Time |
| Monday | 9:00 |
| Tuesday | 10:00 |
"""
    output = table_to_prose(malformed)
    assert "Monday" in output
    assert "9:00" in output
    assert "Tuesday" in output


def test_malformed_ragged_extra_columns_does_not_crash():
    """Extra columns beyond the header are silently ignored; known columns kept."""
    ragged = """\
| Day | Time |
|-----|------|
| Monday | 9:00 | extra | columns |
| Tuesday | 10:00 |
"""
    output = table_to_prose(ragged)
    assert "Monday" in output
    assert "9:00" in output
    assert "Tuesday" in output


def test_malformed_ragged_fewer_columns_does_not_crash():
    """A row shorter than the header: missing columns treated as empty."""
    short_row = """\
| Day | Time | Room |
|-----|------|------|
| Monday |
| Tuesday | 10:00 | 101 |
"""
    output = table_to_prose(short_row)
    assert "Monday" in output
    assert "Tuesday" in output
    assert "10:00" in output


def test_malformed_header_only_does_not_crash():
    """Table with header + separator but no data rows: returns without error."""
    header_only = """\
| Day | Time |
|-----|------|
"""
    output = table_to_prose(header_only)
    assert isinstance(output, str)


def test_malformed_empty_string_does_not_crash():
    assert table_to_prose("") == ""


# ── prose passthrough ─────────────────────────────────────────────────────────

def test_prose_sections_preserved_in_mixed_document():
    output = table_to_prose(MIXED_DOCUMENT)
    assert "School Schedule" in output
    assert "Introductory paragraph" in output
    assert "Footer note" in output


def test_table_converted_in_mixed_document():
    output = table_to_prose(MIXED_DOCUMENT)
    assert_cell_present(output, "Start", "9:00")
    assert "|" not in output


def test_multiple_tables_both_converted():
    output = table_to_prose(MULTIPLE_TABLES)
    assert_cell_present(output, "Subject", "Maths")
    assert_cell_present(output, "Teacher", "Jones")
    assert_cell_present(output, "Room", "101")
    assert_cell_present(output, "Capacity", "30")
    assert "|" not in output
