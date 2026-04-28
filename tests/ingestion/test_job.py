"""
Unit tests for ingestion job helpers (no I/O, no mocks needed).
"""
from src.ingestion.job.gcs_io import has_changes


def _files(*name_mtime_pairs):
    return [{"name": n, "modified_time": m} for n, m in name_mtime_pairs]


def _manifest(*name_mtime_pairs):
    return {"files": [{"name": n, "modified_time": m} for n, m in name_mtime_pairs]}


class TestHasChanges:
    def test_no_changes_empty(self):
        assert not has_changes([], {})

    def test_no_changes_matching(self):
        files = _files(("a.docx", "2026-01-01T00:00:00Z"))
        manifest = _manifest(("a.docx", "2026-01-01T00:00:00Z"))
        assert not has_changes(files, manifest)

    def test_new_file(self):
        files = _files(("a.docx", "2026-01-01T00:00:00Z"), ("b.docx", "2026-01-02T00:00:00Z"))
        manifest = _manifest(("a.docx", "2026-01-01T00:00:00Z"))
        assert has_changes(files, manifest)

    def test_removed_file(self):
        files = _files(("a.docx", "2026-01-01T00:00:00Z"))
        manifest = _manifest(("a.docx", "2026-01-01T00:00:00Z"), ("b.docx", "2026-01-02T00:00:00Z"))
        assert has_changes(files, manifest)

    def test_modified_file(self):
        files = _files(("a.docx", "2026-01-02T00:00:00Z"))
        manifest = _manifest(("a.docx", "2026-01-01T00:00:00Z"))
        assert has_changes(files, manifest)

    def test_first_run_empty_manifest(self):
        files = _files(("a.docx", "2026-01-01T00:00:00Z"))
        assert has_changes(files, {})

    def test_multiple_files_no_changes(self):
        pairs = [("a.docx", "T1"), ("b.docx", "T2"), ("c.docx", "T3")]
        assert not has_changes(_files(*pairs), _manifest(*pairs))
