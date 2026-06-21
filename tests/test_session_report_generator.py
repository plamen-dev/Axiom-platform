"""Tests for Session Report Generator v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_report_generator import (
    RecommendationPriority,
    ReportSection,
    ReportStatus,
    ReportSummary,
    SectionType,
    SessionReport,
    SessionReportGenerator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def generator(tmp_path: Path) -> SessionReportGenerator:
    return SessionReportGenerator(artifacts_root=str(tmp_path))


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_report_status_values(self):
        assert ReportStatus.DRAFT.value == "draft"
        assert ReportStatus.FINAL.value == "final"
        assert ReportStatus.SUPERSEDED.value == "superseded"

    def test_section_type_values(self):
        assert SectionType.SUMMARY.value == "summary"
        assert SectionType.PLANS.value == "plans"
        assert SectionType.QUESTIONS.value == "questions"
        assert SectionType.ASSERTIONS.value == "assertions"
        assert SectionType.FINDINGS.value == "findings"
        assert SectionType.VALIDATION.value == "validation"
        assert SectionType.RECOMMENDATIONS.value == "recommendations"
        assert SectionType.RATIONALE.value == "rationale"
        assert SectionType.CUSTOM.value == "custom"

    def test_recommendation_priority_values(self):
        assert RecommendationPriority.CRITICAL.value == "critical"
        assert RecommendationPriority.HIGH.value == "high"
        assert RecommendationPriority.MEDIUM.value == "medium"
        assert RecommendationPriority.LOW.value == "low"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_report_section_defaults(self):
        s = ReportSection(title="Test Section")
        assert s.section_id
        assert s.section_type == "custom"
        assert s.title == "Test Section"
        assert s.content == ""
        assert s.order == 0

    def test_report_section_to_dict(self):
        s = ReportSection(title="T", content="C", section_type="summary", order=1)
        d = s.to_dict()
        assert d["title"] == "T"
        assert d["content"] == "C"
        assert d["section_type"] == "summary"
        assert d["order"] == 1

    def test_report_summary_defaults(self):
        rs = ReportSummary()
        assert rs.total_sections == 0
        assert rs.total_recommendations == 0
        assert rs.critical_recommendations == 0
        assert rs.plans_referenced == 0

    def test_report_summary_to_dict(self):
        rs = ReportSummary(total_sections=3, total_recommendations=2)
        d = rs.to_dict()
        assert d["total_sections"] == 3
        assert d["total_recommendations"] == 2

    def test_session_report_defaults(self):
        r = SessionReport(title="Report A")
        assert r.report_id
        assert r.title == "Report A"
        assert r.status == "draft"
        assert r.sections == []
        assert r.recommendations == []
        assert r.created_at

    def test_session_report_to_dict(self):
        r = SessionReport(title="Report B", rationale="testing")
        d = r.to_dict()
        assert d["title"] == "Report B"
        assert d["rationale"] == "testing"
        assert d["status"] == "draft"
        assert "report_summary" in d

    def test_session_report_summary_computed(self):
        r = SessionReport(title="R")
        d = r.to_dict()
        assert d["report_summary"]["total_sections"] == 0
        assert d["report_summary"]["total_recommendations"] == 0


# ---------------------------------------------------------------------------
# Create report tests
# ---------------------------------------------------------------------------


class TestCreateReport:
    def test_create_minimal_report(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Minimal Report")
        assert report["title"] == "Minimal Report"
        assert report["status"] == "draft"
        assert report["report_id"]

    def test_create_report_with_all_fields(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Full Report",
            session_id="sess-1",
            plan_id="plan-1",
            work_item_id="wi-1",
            rationale="Full test",
            sections=[
                {"section_type": "summary", "title": "Overview", "content": "Content"},
            ],
            recommendations=[
                {"description": "Fix X", "priority": "critical", "rationale": "Why"},
            ],
            linked_plan_ids=["plan-1", "plan-2"],
            linked_question_ids=["q-1"],
            linked_assertion_ids=["a-1", "a-2"],
        )
        assert report["session_id"] == "sess-1"
        assert report["plan_id"] == "plan-1"
        assert report["work_item_id"] == "wi-1"
        assert report["rationale"] == "Full test"
        assert len(report["sections"]) == 1
        assert report["sections"][0]["section_type"] == "summary"
        assert len(report["recommendations"]) == 1
        assert report["recommendations"][0]["priority"] == "critical"
        assert report["linked_plan_ids"] == ["plan-1", "plan-2"]
        assert report["linked_question_ids"] == ["q-1"]
        assert report["linked_assertion_ids"] == ["a-1", "a-2"]
        assert report["report_summary"]["total_sections"] == 1
        assert report["report_summary"]["total_recommendations"] == 1
        assert report["report_summary"]["critical_recommendations"] == 1
        assert report["report_summary"]["plans_referenced"] == 2

    def test_create_report_persists(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Persist Test")
        loaded = generator.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["title"] == "Persist Test"


# ---------------------------------------------------------------------------
# Get report tests
# ---------------------------------------------------------------------------


class TestGetReport:
    def test_get_existing(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Get Test")
        loaded = generator.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]

    def test_get_nonexistent(self, generator: SessionReportGenerator):
        result = generator.get_report("nonexistent-id")
        assert result is None

    def test_get_empty_id_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not be empty"):
            generator.get_report("")

    def test_get_path_traversal_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_report("../etc/passwd")


# ---------------------------------------------------------------------------
# List reports tests
# ---------------------------------------------------------------------------


class TestListReports:
    def test_list_empty(self, generator: SessionReportGenerator):
        reports = generator.list_reports()
        assert reports == []

    def test_list_all(self, generator: SessionReportGenerator):
        generator.create_report(title="A")
        generator.create_report(title="B")
        reports = generator.list_reports()
        assert len(reports) == 2

    def test_list_filter_by_status(self, generator: SessionReportGenerator):
        r1 = generator.create_report(title="Draft")
        generator.update_status(r1["report_id"], "final")
        generator.create_report(title="Still Draft")
        drafts = generator.list_reports(status="draft")
        assert len(drafts) == 1
        assert drafts[0]["title"] == "Still Draft"
        finals = generator.list_reports(status="final")
        assert len(finals) == 1
        assert finals[0]["title"] == "Draft"

    def test_list_deterministic_ordering(self, generator: SessionReportGenerator):
        import time

        generator.create_report(title="First")
        time.sleep(0.01)
        second = generator.create_report(title="Second")
        generator.update_status(second["report_id"], "final")
        reports = generator.list_reports()
        assert reports[0]["title"] == "First"
        assert reports[1]["title"] == "Second"


# ---------------------------------------------------------------------------
# Update status tests
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_to_final(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Status Test")
        updated = generator.update_status(report["report_id"], "final")
        assert updated is not None
        assert updated["status"] == "final"

    def test_update_to_superseded(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Status Test 2")
        updated = generator.update_status(report["report_id"], "superseded")
        assert updated is not None
        assert updated["status"] == "superseded"

    def test_update_nonexistent(self, generator: SessionReportGenerator):
        result = generator.update_status("nonexistent-id", "final")
        assert result is None

    def test_update_invalid_status(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Invalid Status")
        with pytest.raises(ValueError, match="Invalid status"):
            generator.update_status(report["report_id"], "bogus")


# ---------------------------------------------------------------------------
# Add section tests
# ---------------------------------------------------------------------------


class TestAddSection:
    def test_add_section(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Section Test")
        updated = generator.add_section(
            report["report_id"],
            section_type="summary",
            title="Overview",
            content="Test content",
        )
        assert updated is not None
        assert len(updated["sections"]) == 1
        assert updated["sections"][0]["section_type"] == "summary"
        assert updated["sections"][0]["order"] == 1

    def test_add_multiple_sections(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Multi Section")
        generator.add_section(report["report_id"], title="A")
        updated = generator.add_section(report["report_id"], title="B")
        assert updated is not None
        assert len(updated["sections"]) == 2
        assert updated["sections"][1]["order"] == 2

    def test_add_section_nonexistent(self, generator: SessionReportGenerator):
        result = generator.add_section("nonexistent", title="X")
        assert result is None

    def test_add_section_recomputes_summary(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Summary Recompute")
        updated = generator.add_section(report["report_id"], title="S1")
        assert updated is not None
        assert updated["report_summary"]["total_sections"] == 1


# ---------------------------------------------------------------------------
# Add recommendation tests
# ---------------------------------------------------------------------------


class TestAddRecommendation:
    def test_add_recommendation(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Rec Test")
        updated = generator.add_recommendation(
            report["report_id"],
            description="Fix X",
            priority="critical",
            rationale="Because Y",
        )
        assert updated is not None
        assert len(updated["recommendations"]) == 1
        assert updated["recommendations"][0]["priority"] == "critical"

    def test_add_recommendation_nonexistent(self, generator: SessionReportGenerator):
        result = generator.add_recommendation("nonexistent", description="X")
        assert result is None

    def test_add_recommendation_recomputes_summary(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Rec Summary")
        updated = generator.add_recommendation(
            report["report_id"],
            description="Critical Fix",
            priority="critical",
        )
        assert updated is not None
        assert updated["report_summary"]["total_recommendations"] == 1
        assert updated["report_summary"]["critical_recommendations"] == 1

    def test_add_recommendation_with_links(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Linked Rec")
        updated = generator.add_recommendation(
            report["report_id"],
            description="Linked Fix",
            linked_assertion_id="a-1",
            linked_finding_id="f-1",
        )
        assert updated is not None
        assert updated["recommendations"][0]["linked_assertion_id"] == "a-1"
        assert updated["recommendations"][0]["linked_finding_id"] == "f-1"


# ---------------------------------------------------------------------------
# Export report tests
# ---------------------------------------------------------------------------


class TestExportReport:
    def test_export_basic(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Export Test",
            rationale="Test rationale",
        )
        md = generator.export_report(report["report_id"])
        assert "# Session Report: Export Test" in md
        assert "Test rationale" in md
        assert report["report_id"] in md

    def test_export_with_sections(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Section Export",
            sections=[
                {"section_type": "summary", "title": "Overview", "content": "Summary here"},
                {"section_type": "findings", "title": "Findings", "content": "Found stuff"},
            ],
        )
        md = generator.export_report(report["report_id"])
        assert "## Overview" in md
        assert "Summary here" in md
        assert "## Findings" in md

    def test_export_with_recommendations(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Rec Export",
            recommendations=[
                {"description": "Fix A", "priority": "critical", "rationale": "R1"},
                {"description": "Fix B", "priority": "low"},
            ],
        )
        md = generator.export_report(report["report_id"])
        assert "[critical] Fix A" in md
        assert "[low] Fix B" in md
        assert "Rationale: R1" in md

    def test_export_with_references(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Ref Export",
            linked_plan_ids=["p-1"],
            linked_question_ids=["q-1", "q-2"],
            linked_assertion_ids=["a-1"],
        )
        md = generator.export_report(report["report_id"])
        assert "Plans: p-1" in md
        assert "Questions: q-1, q-2" in md
        assert "Assertions: a-1" in md

    def test_export_nonexistent_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="Report not found"):
            generator.export_report("nonexistent-id")

    def test_export_deterministic_section_order(self, generator: SessionReportGenerator):
        report = generator.create_report(
            title="Section Order",
            sections=[
                {"section_type": "recommendations", "title": "Recs", "content": "C1"},
                {"section_type": "summary", "title": "Sum", "content": "C2"},
            ],
        )
        md = generator.export_report(report["report_id"])
        sum_pos = md.index("## Sum")
        rec_pos = md.index("## Recs")
        assert sum_pos < rec_pos


# ---------------------------------------------------------------------------
# Evidence writing tests
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_evidence_bundle_created(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Evidence Test")
        evidence_dir = generator.write_evidence(report["report_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "report_request.json").exists()
        assert (ev_path / "report_result.json").exists()
        assert (ev_path / "session_report.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_request_valid_json(self, generator: SessionReportGenerator):
        report = generator.create_report(title="JSON Request Test")
        evidence_dir = generator.write_evidence(report["report_id"])
        data = json.loads((Path(evidence_dir) / "report_request.json").read_text())
        assert data["report_id"] == report["report_id"]
        assert data["title"] == "JSON Request Test"

    def test_evidence_result_valid_json(self, generator: SessionReportGenerator):
        report = generator.create_report(title="JSON Result Test")
        evidence_dir = generator.write_evidence(report["report_id"])
        data = json.loads((Path(evidence_dir) / "report_result.json").read_text())
        assert data["report_id"] == report["report_id"]
        assert data["title"] == "JSON Result Test"

    def test_evidence_pass_fail_valid(self, generator: SessionReportGenerator):
        report = generator.create_report(title="Pass Fail Test")
        evidence_dir = generator.write_evidence(report["report_id"])
        data = json.loads((Path(evidence_dir) / "pass_fail.json").read_text())
        assert data["passed"] is True
        assert data["report_id"] == report["report_id"]
        assert "timestamp" in data

    def test_evidence_markdown_valid(self, generator: SessionReportGenerator):
        report = generator.create_report(title="MD Test", rationale="R")
        evidence_dir = generator.write_evidence(report["report_id"])
        md = (Path(evidence_dir) / "session_report.md").read_text()
        assert "# Session Report: MD Test" in md

    def test_evidence_nonexistent_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="Report not found"):
            generator.write_evidence("nonexistent-id")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not be empty"):
            generator.get_report("")

    def test_whitespace_id_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not be empty"):
            generator.get_report("   ")

    def test_dotdot_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_report("../etc/passwd")

    def test_slash_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_report("foo/bar")

    def test_backslash_raises(self, generator: SessionReportGenerator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_report("foo\\bar")


# ---------------------------------------------------------------------------
# Command registry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistrySpecs:
    def test_session_report_registered(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-report")
        assert cmd is not None
        assert cmd.classification.value == "read_only"
        assert cmd.safety_level.value == "safe"

    def test_session_report_has_evidence_outputs(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-report")
        assert cmd is not None
        evidence_names = [e.location for e in cmd.evidence_outputs]
        assert "report_request.json" in evidence_names
        assert "report_result.json" in evidence_names
        assert "session_report.md" in evidence_names
        assert "pass_fail.json" in evidence_names

    def test_session_reports_registered(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-reports")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_session_report_show_registered(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-report-show")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_session_report_export_registered(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-report-export")
        assert cmd is not None
        assert cmd.classification.value == "read_only"


# ---------------------------------------------------------------------------
# Test selection mapping test
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/session_report_generator.py"]
            == "tests/test_session_report_generator.py"
        )
