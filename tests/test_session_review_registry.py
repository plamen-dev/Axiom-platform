"""Tests for SessionReviewRegistry v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_review_registry import (
    FindingSeverity,
    FindingStatus,
    ReviewEvidenceLink,
    ReviewFinding,
    ReviewResolution,
    ReviewSource,
    ReviewStatus,
    ReviewSummary,
    SessionReview,
    SessionReviewRegistry,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_review_status_values(self):
        assert ReviewStatus.OPEN.value == "open"
        assert ReviewStatus.IN_PROGRESS.value == "in_progress"
        assert ReviewStatus.RESOLVED.value == "resolved"
        assert ReviewStatus.CLOSED.value == "closed"

    def test_finding_severity_values(self):
        assert FindingSeverity.CRITICAL.value == "critical"
        assert FindingSeverity.HIGH.value == "high"
        assert FindingSeverity.MEDIUM.value == "medium"
        assert FindingSeverity.LOW.value == "low"
        assert FindingSeverity.INFO.value == "info"

    def test_finding_status_values(self):
        assert FindingStatus.OPEN.value == "open"
        assert FindingStatus.FIXED.value == "fixed"
        assert FindingStatus.ACKNOWLEDGED.value == "acknowledged"
        assert FindingStatus.REJECTED.value == "rejected"
        assert FindingStatus.DEFERRED.value == "deferred"

    def test_review_source_values(self):
        assert ReviewSource.DEVIN_REVIEW.value == "devin_review"
        assert ReviewSource.HUMAN_REVIEW.value == "human_review"
        assert ReviewSource.CI_FAILURE.value == "ci_failure"
        assert ReviewSource.CLI_TESTING.value == "cli_testing"
        assert ReviewSource.AUTOMATED_AGENT.value == "automated_agent"
        assert ReviewSource.OTHER.value == "other"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_review_finding_defaults(self):
        f = ReviewFinding(summary="test finding")
        assert f.finding_id  # auto-generated
        assert f.summary == "test finding"
        assert f.severity == "medium"
        assert f.source == "other"
        assert f.status == "open"
        assert f.linked_evidence_ids == []

    def test_review_finding_to_dict(self):
        f = ReviewFinding(summary="bug", severity="high", file_path="foo.py", line_number=42)
        d = f.to_dict()
        assert d["summary"] == "bug"
        assert d["severity"] == "high"
        assert d["file_path"] == "foo.py"
        assert d["line_number"] == 42
        assert d["status"] == "open"

    def test_review_resolution_defaults(self):
        r = ReviewResolution(finding_id="f1", resolution_note="fixed in abc123")
        assert r.resolution_id  # auto-generated
        assert r.finding_id == "f1"
        assert r.resolution_note == "fixed in abc123"
        assert r.resolved_at  # auto-generated

    def test_review_resolution_to_dict(self):
        r = ReviewResolution(finding_id="f1", commit_id="abc123")
        d = r.to_dict()
        assert d["finding_id"] == "f1"
        assert d["commit_id"] == "abc123"

    def test_review_evidence_link_defaults(self):
        e = ReviewEvidenceLink(evidence_type="validation", evidence_path="/path")
        assert e.link_id  # auto-generated
        assert e.evidence_type == "validation"
        assert e.evidence_path == "/path"

    def test_review_summary_to_dict(self):
        s = ReviewSummary(total_findings=5, open_findings=2, fixed_findings=3)
        d = s.to_dict()
        assert d["total_findings"] == 5
        assert d["open_findings"] == 2
        assert d["fixed_findings"] == 3

    def test_session_review_defaults(self):
        r = SessionReview(title="Test Review")
        assert r.review_id  # auto-generated
        assert r.title == "Test Review"
        assert r.source == "other"
        assert r.status == "open"
        assert r.severity == "medium"
        assert r.created_at  # auto-generated
        assert r.updated_at == r.created_at

    def test_session_review_to_dict(self):
        r = SessionReview(title="Test", pr_id="PR-1", source="devin_review")
        d = r.to_dict()
        assert d["title"] == "Test"
        assert d["pr_id"] == "PR-1"
        assert d["source"] == "devin_review"
        assert "review_summary" in d
        assert d["review_summary"]["total_findings"] == 0

    def test_session_review_summary_computation(self):
        r = SessionReview(title="Test")
        r.findings = [
            ReviewFinding(summary="f1", severity="critical", status="open"),
            ReviewFinding(summary="f2", severity="high", status="fixed"),
            ReviewFinding(summary="f3", severity="medium", status="acknowledged"),
        ]
        d = r.to_dict()
        summary = d["review_summary"]
        assert summary["total_findings"] == 3
        assert summary["open_findings"] == 1
        assert summary["fixed_findings"] == 1
        assert summary["acknowledged_findings"] == 1
        assert summary["critical_findings"] == 1
        assert summary["high_findings"] == 1


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    return SessionReviewRegistry(artifacts_root=str(tmp_path))


class TestCreateReview:
    def test_create_minimal(self, registry):
        review = registry.create_review(title="Test Review")
        assert review["review_id"]
        assert review["title"] == "Test Review"
        assert review["status"] == "open"
        assert review["source"] == "other"
        assert review["severity"] == "medium"

    def test_create_full(self, registry):
        review = registry.create_review(
            title="Full Review",
            source="devin_review",
            severity="high",
            pr_id="PR-75",
            coding_session_id="cs-1",
            session_report_id="sr-1",
            rationale="Testing review creation",
        )
        assert review["title"] == "Full Review"
        assert review["source"] == "devin_review"
        assert review["severity"] == "high"
        assert review["pr_id"] == "PR-75"
        assert review["coding_session_id"] == "cs-1"
        assert review["session_report_id"] == "sr-1"
        assert review["rationale"] == "Testing review creation"

    def test_create_persists(self, registry):
        review = registry.create_review(title="Persist Test")
        loaded = registry.get_review(review["review_id"])
        assert loaded is not None
        assert loaded["title"] == "Persist Test"


class TestGetReview:
    def test_get_existing(self, registry):
        review = registry.create_review(title="Get Test")
        got = registry.get_review(review["review_id"])
        assert got["review_id"] == review["review_id"]

    def test_get_nonexistent(self, registry):
        assert registry.get_review("nonexistent-id") is None

    def test_get_validates_id(self, registry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_review("")
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("../etc/passwd")
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("foo/bar")
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("foo\\bar")


class TestListReviews:
    def test_list_empty(self, registry):
        assert registry.list_reviews() == []

    def test_list_all(self, registry):
        registry.create_review(title="R1")
        registry.create_review(title="R2")
        reviews = registry.list_reviews()
        assert len(reviews) == 2

    def test_list_filter_status(self, registry):
        r1 = registry.create_review(title="R1")
        registry.create_review(title="R2")
        registry.update_status(r1["review_id"], "resolved")
        open_reviews = registry.list_reviews(status="open")
        assert len(open_reviews) == 1
        assert open_reviews[0]["title"] == "R2"

    def test_list_filter_source(self, registry):
        registry.create_review(title="R1", source="devin_review")
        registry.create_review(title="R2", source="human_review")
        devin = registry.list_reviews(source="devin_review")
        assert len(devin) == 1
        assert devin[0]["title"] == "R1"

    def test_list_deterministic_ordering(self, registry):
        registry.create_review(title="Low", severity="low")
        registry.create_review(title="Critical", severity="critical")
        reviews = registry.list_reviews()
        assert reviews[0]["title"] == "Critical"
        assert reviews[1]["title"] == "Low"


class TestAddFinding:
    def test_add_single(self, registry):
        review = registry.create_review(title="R1")
        finding = registry.add_finding(
            review_id=review["review_id"],
            summary="Missing None check",
            severity="high",
            file_path="src/foo.py",
            line_number=42,
        )
        assert finding["finding_id"]
        assert finding["summary"] == "Missing None check"
        assert finding["severity"] == "high"
        assert finding["file_path"] == "src/foo.py"
        assert finding["line_number"] == 42
        assert finding["status"] == "open"

    def test_add_updates_summary(self, registry):
        review = registry.create_review(title="R1")
        registry.add_finding(
            review_id=review["review_id"],
            summary="Bug 1",
            severity="critical",
        )
        updated = registry.get_review(review["review_id"])
        summary = updated["review_summary"]
        assert summary["total_findings"] == 1
        assert summary["open_findings"] == 1
        assert summary["critical_findings"] == 1

    def test_add_nonexistent_review(self, registry):
        with pytest.raises(ValueError, match="Review not found"):
            registry.add_finding(
                review_id="nonexistent-id",
                summary="Bug",
            )

    def test_add_multiple(self, registry):
        review = registry.create_review(title="R1")
        registry.add_finding(review_id=review["review_id"], summary="F1")
        registry.add_finding(review_id=review["review_id"], summary="F2")
        updated = registry.get_review(review["review_id"])
        assert updated["review_summary"]["total_findings"] == 2


class TestResolveFinding:
    def test_resolve_valid(self, registry):
        review = registry.create_review(title="R1")
        finding = registry.add_finding(
            review_id=review["review_id"], summary="Bug"
        )
        resolution = registry.resolve_finding(
            review_id=review["review_id"],
            finding_id=finding["finding_id"],
            status="fixed",
            resolution_note="Fixed in abc123",
            commit_id="abc123",
        )
        assert resolution["finding_id"] == finding["finding_id"]
        assert resolution["resolution_note"] == "Fixed in abc123"
        assert resolution["commit_id"] == "abc123"

        updated = registry.get_review(review["review_id"])
        assert updated["review_summary"]["open_findings"] == 0
        assert updated["review_summary"]["fixed_findings"] == 1

    def test_resolve_acknowledged(self, registry):
        review = registry.create_review(title="R1")
        finding = registry.add_finding(
            review_id=review["review_id"], summary="Info"
        )
        registry.resolve_finding(
            review_id=review["review_id"],
            finding_id=finding["finding_id"],
            status="acknowledged",
            resolution_note="Intentional design",
        )
        updated = registry.get_review(review["review_id"])
        assert updated["review_summary"]["acknowledged_findings"] == 1

    def test_resolve_invalid_status(self, registry):
        review = registry.create_review(title="R1")
        finding = registry.add_finding(
            review_id=review["review_id"], summary="Bug"
        )
        with pytest.raises(ValueError, match="Invalid resolution status"):
            registry.resolve_finding(
                review_id=review["review_id"],
                finding_id=finding["finding_id"],
                status="invalid_status",
            )

    def test_resolve_nonexistent_review(self, registry):
        with pytest.raises(ValueError, match="Review not found"):
            registry.resolve_finding(
                review_id="nonexistent-id",
                finding_id="f1",
                status="fixed",
            )

    def test_resolve_nonexistent_finding(self, registry):
        review = registry.create_review(title="R1")
        with pytest.raises(ValueError, match="Finding not found"):
            registry.resolve_finding(
                review_id=review["review_id"],
                finding_id="nonexistent-finding",
                status="fixed",
            )

    def test_resolve_open_not_allowed(self, registry):
        review = registry.create_review(title="R1")
        finding = registry.add_finding(
            review_id=review["review_id"], summary="Bug"
        )
        with pytest.raises(ValueError, match="Invalid resolution status"):
            registry.resolve_finding(
                review_id=review["review_id"],
                finding_id=finding["finding_id"],
                status="open",
            )


class TestUpdateStatus:
    def test_update_valid(self, registry):
        review = registry.create_review(title="R1")
        updated = registry.update_status(review["review_id"], "resolved")
        assert updated["status"] == "resolved"

    def test_update_invalid_status(self, registry):
        review = registry.create_review(title="R1")
        with pytest.raises(ValueError, match="Invalid status"):
            registry.update_status(review["review_id"], "invalid")

    def test_update_nonexistent(self, registry):
        with pytest.raises(ValueError, match="Review not found"):
            registry.update_status("nonexistent-id", "resolved")


class TestExportReview:
    def test_export_basic(self, registry):
        review = registry.create_review(
            title="Export Test",
            source="devin_review",
            rationale="Testing export",
        )
        md = registry.export_review(review["review_id"])
        assert "# Session Review: Export Test" in md
        assert "devin_review" in md
        assert "Testing export" in md

    def test_export_with_findings(self, registry):
        review = registry.create_review(title="Review With Findings")
        registry.add_finding(
            review_id=review["review_id"],
            summary="Critical bug",
            severity="critical",
            file_path="src/main.py",
            line_number=100,
        )
        md = registry.export_review(review["review_id"])
        assert "## Findings" in md
        assert "Critical bug" in md
        assert "`src/main.py:100`" in md
        assert "[CRITICAL]" in md

    def test_export_with_resolutions(self, registry):
        review = registry.create_review(title="Resolved Review")
        finding = registry.add_finding(
            review_id=review["review_id"], summary="Bug"
        )
        registry.resolve_finding(
            review_id=review["review_id"],
            finding_id=finding["finding_id"],
            status="fixed",
            resolution_note="Fixed it",
            commit_id="abc123",
        )
        md = registry.export_review(review["review_id"])
        assert "## Resolutions" in md
        assert "Fixed it" in md
        assert "`abc123`" in md

    def test_export_with_linked_ids(self, registry):
        review = registry.create_review(
            title="Linked Review",
            pr_id="PR-75",
            coding_session_id="cs-abc",
        )
        md = registry.export_review(review["review_id"])
        assert "PR-75" in md
        assert "cs-abc" in md

    def test_export_nonexistent(self, registry):
        with pytest.raises(ValueError, match="Review not found"):
            registry.export_review("nonexistent-id")

    def test_export_deterministic_finding_order(self, registry):
        review = registry.create_review(title="Order Test")
        registry.add_finding(
            review_id=review["review_id"],
            summary="Low priority",
            severity="low",
        )
        registry.add_finding(
            review_id=review["review_id"],
            summary="Critical priority",
            severity="critical",
        )
        md = registry.export_review(review["review_id"])
        critical_pos = md.index("Critical priority")
        low_pos = md.index("Low priority")
        assert critical_pos < low_pos


class TestWriteEvidence:
    def test_evidence_files_created(self, registry, tmp_path):
        review = registry.create_review(title="Evidence Test")
        evidence_dir = registry.write_evidence(review["review_id"])
        evidence_path = Path(evidence_dir)
        assert (evidence_path / "review_request.json").exists()
        assert (evidence_path / "review_result.json").exists()
        assert (evidence_path / "session_review.md").exists()
        assert (evidence_path / "pass_fail.json").exists()

    def test_evidence_json_valid(self, registry, tmp_path):
        review = registry.create_review(title="JSON Test")
        evidence_dir = Path(registry.write_evidence(review["review_id"]))
        # All JSON files should be valid
        for f in ["review_request.json", "review_result.json", "pass_fail.json"]:
            data = json.loads((evidence_dir / f).read_text())
            assert isinstance(data, dict)

    def test_evidence_pass_fail(self, registry, tmp_path):
        review = registry.create_review(title="Pass Fail Test")
        evidence_dir = Path(registry.write_evidence(review["review_id"]))
        pf = json.loads((evidence_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True  # No open findings
        assert pf["review_id"] == review["review_id"]
        assert pf["total_findings"] == 0
        assert "timestamp" in pf

    def test_evidence_pass_fail_with_open_findings(self, registry, tmp_path):
        review = registry.create_review(title="Open Findings")
        registry.add_finding(
            review_id=review["review_id"], summary="Bug"
        )
        evidence_dir = Path(registry.write_evidence(review["review_id"]))
        pf = json.loads((evidence_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False  # Has open findings
        assert pf["open_findings"] == 1

    def test_evidence_markdown_valid(self, registry, tmp_path):
        review = registry.create_review(title="MD Test")
        evidence_dir = Path(registry.write_evidence(review["review_id"]))
        md = (evidence_dir / "session_review.md").read_text()
        assert "# Session Review: MD Test" in md

    def test_evidence_nonexistent(self, registry):
        with pytest.raises(ValueError, match="Review not found"):
            registry.write_evidence("nonexistent-id")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, registry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_review("")

    def test_whitespace_id(self, registry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_review("   ")

    def test_path_traversal_dotdot(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("../etc/passwd")

    def test_path_traversal_slash(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("foo/bar")

    def test_path_traversal_backslash(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_review("foo\\bar")


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistry:
    def test_review_commands_registered(self):
        from axiom_core.runner.command_registry import get_command

        expected = [
            "review-create",
            "review-add-finding",
            "review-resolve",
            "reviews",
            "review-show",
            "review-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"Command {name!r} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_review_create_evidence_outputs(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("review-create")
        assert cmd is not None
        evs = [e.location for e in cmd.evidence_outputs]
        assert "review_request.json" in evs
        assert "review_result.json" in evs
        assert "session_review.md" in evs
        assert "pass_fail.json" in evs
        assert len(evs) == 4


# ---------------------------------------------------------------------------
# Test selection mapping tests
# ---------------------------------------------------------------------------


class TestTestSelectionMapping:
    def test_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/session_review_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_session_review_registry.py"
