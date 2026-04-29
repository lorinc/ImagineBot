"""
Unit tests for ingestion job helpers (no I/O, no network).
"""
import time

import pytest

from src.ingestion.errors import (
    ExportEmpty,
    ExportServerError,
    IngestionError,
    NoHeadings,
    PermissionDenied,
    PipelineFailure,
    UnsupportedFormat,
    ValidationError,
    retry,
)
from src.ingestion.job.gcs_io import has_changes
from src.ingestion.job.run_report import build_report, file_failed, file_ok


# ---------------------------------------------------------------------------
# has_changes — fingerprint-based change detection
# ---------------------------------------------------------------------------

def _files(*name_fp_pairs):
    return [{"name": n, "md5Checksum": fp, "version": None, "mimeType": "docx"} for n, fp in name_fp_pairs]


def _manifest(*name_fp_pairs):
    return {"files": [{"name": n, "fingerprint": fp} for n, fp in name_fp_pairs]}


class TestHasChanges:
    def test_no_changes_empty(self):
        assert not has_changes([], {})

    def test_no_changes_matching(self):
        files = _files(("a.docx", "abc123"))
        manifest = _manifest(("a.docx", "abc123"))
        assert not has_changes(files, manifest)

    def test_new_file(self):
        files = _files(("a.docx", "abc123"), ("b.docx", "def456"))
        manifest = _manifest(("a.docx", "abc123"))
        assert has_changes(files, manifest)

    def test_removed_file(self):
        files = _files(("a.docx", "abc123"))
        manifest = _manifest(("a.docx", "abc123"), ("b.docx", "def456"))
        assert has_changes(files, manifest)

    def test_modified_file(self):
        files = _files(("a.docx", "newfingerprint"))
        manifest = _manifest(("a.docx", "oldfingerprint"))
        assert has_changes(files, manifest)

    def test_first_run_empty_manifest(self):
        files = _files(("a.docx", "abc123"))
        assert has_changes(files, {})

    def test_multiple_files_no_changes(self):
        pairs = [("a.docx", "fp1"), ("b.docx", "fp2"), ("c.docx", "fp3")]
        assert not has_changes(_files(*pairs), _manifest(*pairs))


# ---------------------------------------------------------------------------
# ValidationError hierarchy
# ---------------------------------------------------------------------------

class TestValidationErrorHierarchy:
    def test_all_subclasses_are_validation_error(self):
        for cls in (UnsupportedFormat, PermissionDenied, ExportEmpty, NoHeadings,
                    ExportServerError, PipelineFailure):
            assert issubclass(cls, ValidationError)
            assert issubclass(cls, IngestionError)

    def test_class_attributes_populated(self):
        for cls in (UnsupportedFormat, PermissionDenied, ExportEmpty, NoHeadings, ExportServerError):
            assert cls.error_type, f"{cls.__name__}.error_type is empty"
            assert cls.error_detail, f"{cls.__name__}.error_detail is empty"
            assert cls.actionable, f"{cls.__name__}.actionable is empty"

    def test_constructor_sets_name_and_drive_url(self):
        e = PermissionDenied("My Doc", "https://drive.google.com/x")
        assert e.name == "My Doc"
        assert e.drive_url == "https://drive.google.com/x"
        assert e.error_type == "PERMISSION_DENIED"

    def test_pipeline_failure_sets_step_and_cause(self):
        cause = ValueError("timeout")
        e = PipelineFailure("Doc", "https://drive.google.com/x", step=3, cause=cause)
        assert e.step == 3
        assert e.cause is cause
        assert e.error_type == "PIPELINE_FAILURE"
        assert "Step 3" in e.error_detail

    def test_error_detail_override(self):
        e = ExportServerError("Doc", "https://x", error_detail="Custom detail")
        assert e.error_detail == "Custom detail"


# ---------------------------------------------------------------------------
# retry()
# ---------------------------------------------------------------------------

class TestRetry:
    def test_succeeds_on_first_attempt(self):
        calls = []
        def fn():
            calls.append(1)
            return 42
        result = retry(fn, name="doc", drive_url="https://x", step=3, backoff=0.0)
        assert result == 42
        assert len(calls) == 1

    def test_retries_and_succeeds(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("transient")
            return "ok"
        result = retry(fn, name="doc", drive_url="https://x", step=3, backoff=0.0)
        assert result == "ok"
        assert len(calls) == 2

    def test_raises_pipeline_failure_on_exhaustion(self):
        def fn():
            raise RuntimeError("always fails")
        with pytest.raises(PipelineFailure) as exc_info:
            retry(fn, name="doc", drive_url="https://x", step=4, max_attempts=3, backoff=0.0)
        e = exc_info.value
        assert e.step == 4
        assert e.name == "doc"
        assert isinstance(e.cause, RuntimeError)

    def test_max_attempts_respected(self):
        calls = []
        def fn():
            calls.append(1)
            raise RuntimeError("fail")
        with pytest.raises(PipelineFailure):
            retry(fn, name="doc", drive_url="https://x", step=3, max_attempts=2, backoff=0.0)
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# run_report helpers
# ---------------------------------------------------------------------------

class TestRunReport:
    def test_file_ok_shape(self):
        r = file_ok("EN_Admissions.docx", steps_completed=[1, 2, 3, 4, 5], chunks=12)
        assert r["name"] == "EN_Admissions.docx"
        assert r["status"] == "ok"
        assert r["steps_completed"] == [1, 2, 3, 4, 5]
        assert r["chunks"] == 12
        assert r["cost_usd"] == 0.0

    def test_file_failed_from_validation_error(self):
        e = NoHeadings("EN_Policies.docx", "https://docs.google.com/x")
        r = file_failed(e)
        assert r["name"] == "EN_Policies.docx"
        assert r["status"] == "failed"
        assert r["error_type"] == "NO_HEADINGS"
        assert r["drive_url"] == "https://docs.google.com/x"
        assert "failed_at_step" not in r

    def test_file_failed_from_pipeline_failure_has_step(self):
        e = PipelineFailure("doc", "https://x", step=3, cause=RuntimeError("x"))
        r = file_failed(e)
        assert r["failed_at_step"] == 3

    def test_build_report_structure(self):
        files = [file_ok("a.docx", [1, 2, 3, 4, 5])]
        report = build_report(
            run_id="2026-04-29T14:30:00+00:00",
            status="ok",
            started_at="2026-04-29T14:30:00+00:00",
            trigger="scheduler",
            files=files,
            index_updated=True,
        )
        assert report["status"] == "ok"
        assert report["index_updated"] is True
        assert report["cost_total_usd"] == 0.0
        assert "finished_at" in report
        assert len(report["files"]) == 1

    def test_build_report_cost_sum(self):
        files = [
            {"name": "a", "status": "ok", "cost_usd": 0.001},
            {"name": "b", "status": "ok", "cost_usd": 0.002},
        ]
        report = build_report(
            run_id="x", status="ok", started_at="x", trigger="manual",
            files=files,
        )
        assert abs(report["cost_total_usd"] - 0.003) < 1e-9
