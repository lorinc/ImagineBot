"""
Unit tests for ingestion job helpers (no I/O, no network).
"""
import time
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from src.ingestion.job.drive_comments import _file_id_from_url, post_validation_comment
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


# ---------------------------------------------------------------------------
# drive_comments — Drive comment posting with dedup
# ---------------------------------------------------------------------------

def _mock_drive(existing_comments=None):
    """Return a mock drive_svc whose comments() chain behaves as specified."""
    drive_svc = MagicMock()
    cm = drive_svc.comments.return_value  # comments() always returns this mock
    cm.list.return_value.execute.return_value = {"comments": existing_comments or []}
    cm.create.return_value.execute.return_value = {"id": "new-comment-id"}
    return drive_svc


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b"error")


class TestFileIdFromUrl:
    def test_drive_viewer_url(self):
        url = "https://drive.google.com/file/d/abc123XYZ/view"
        assert _file_id_from_url(url) == "abc123XYZ"

    def test_docs_editor_url(self):
        url = "https://docs.google.com/document/d/def456/edit"
        assert _file_id_from_url(url) == "def456"

    def test_no_id_returns_none(self):
        assert _file_id_from_url("https://example.com/no-id") is None

    def test_empty_string_returns_none(self):
        assert _file_id_from_url("") is None


class TestPostValidationComment:
    def test_posts_comment_when_no_duplicate(self):
        drive_svc = _mock_drive(existing_comments=[])
        err = ExportEmpty("my_doc", "https://docs.google.com/document/d/FILE123/edit")

        post_validation_comment(drive_svc, err)

        cm = drive_svc.comments.return_value
        cm.create.assert_called_once()
        call_kwargs = cm.create.call_args
        assert call_kwargs.kwargs["fileId"] == "FILE123"
        body = call_kwargs.kwargs["body"]["content"]
        assert "[ImagineBot:EXPORT_EMPTY]" in body
        assert err.actionable in body

    def test_skips_when_duplicate_exists(self):
        existing = [{"content": "[ImagineBot:EXPORT_EMPTY] some old comment", "resolved": False}]
        drive_svc = _mock_drive(existing_comments=existing)
        err = ExportEmpty("my_doc", "https://docs.google.com/document/d/FILE123/edit")

        post_validation_comment(drive_svc, err)

        drive_svc.comments.return_value.create.assert_not_called()

    def test_posts_when_different_error_type_exists(self):
        existing = [{"content": "[ImagineBot:NO_HEADINGS] different error", "resolved": False}]
        drive_svc = _mock_drive(existing_comments=existing)
        err = ExportEmpty("my_doc", "https://docs.google.com/document/d/FILE123/edit")

        post_validation_comment(drive_svc, err)

        drive_svc.comments.return_value.create.assert_called_once()

    def test_no_op_when_drive_url_has_no_file_id(self):
        drive_svc = _mock_drive()
        err = ExportEmpty("my_doc", "https://example.com/no-id-here")

        post_validation_comment(drive_svc, err)  # must not raise

        drive_svc.comments.return_value.list.assert_not_called()
        drive_svc.comments.return_value.create.assert_not_called()

    def test_no_op_on_list_http_error(self):
        drive_svc = MagicMock()
        drive_svc.comments.return_value.list.return_value.execute.side_effect = _http_error(403)
        err = ExportEmpty("my_doc", "https://docs.google.com/document/d/FILE123/edit")

        post_validation_comment(drive_svc, err)  # must not raise

        drive_svc.comments.return_value.create.assert_not_called()

    def test_no_op_on_create_http_error(self):
        drive_svc = _mock_drive(existing_comments=[])
        drive_svc.comments.return_value.create.return_value.execute.side_effect = _http_error(403)
        err = ExportEmpty("my_doc", "https://docs.google.com/document/d/FILE123/edit")

        post_validation_comment(drive_svc, err)  # must not raise
