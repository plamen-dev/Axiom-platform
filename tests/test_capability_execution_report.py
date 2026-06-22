"""Tests for Capability Execution Report Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_execution_report import (
    CapabilityExecutionEvent,
    CapabilityExecutionEvidence,
    CapabilityExecutionReport,
    CapabilityExecutionReportEngine,
    CapabilityExecutionStatus,
    CapabilityExecutionSummary,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_report_defaults(self):
        r = CapabilityExecutionReport()
        assert r.report_id
        assert r.execution_status == "created"
        assert r.events == []
        assert r.created_at

    def test_event_defaults(self):
        e = CapabilityExecutionEvent()
        assert e.event_id
        assert e.timestamp
        assert e.event_type == "started"

    def test_summary_defaults(self):
        s = CapabilityExecutionSummary()
        assert s.summary_id
        assert s.event_count == 0

    def test_evidence_defaults(self):
        ev = CapabilityExecutionEvidence()
        assert ev.evidence_id
        assert ev.report_id == ""


# ---------------------------------------------------------------------------
# Engine - create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_basic_create(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="succeeded",
            duration_ms=150,
        )
        assert result["capability_id"] == "cap-1"
        assert result["execution_status"] == "succeeded"
        assert result["duration_ms"] == 150
        assert result["report_id"]

    def test_create_with_events(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        events = [
            {"event_type": "started", "message": "Begin execution"},
            {"event_type": "input_validated", "message": "Inputs OK"},
            {"event_type": "output_generated", "message": "Output done"},
            {"event_type": "completed", "message": "Finished"},
        ]
        result = engine.create(
            capability_id="cap-2",
            execution_status="succeeded",
            duration_ms=200,
            events=events,
        )
        assert len(result["events"]) == 4
        assert result["summary"]["event_count"] == 4

    def test_create_with_warnings_and_errors(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        events = [
            {"event_type": "started", "message": "Begin"},
            {"event_type": "warning", "message": "Something odd"},
            {"event_type": "warning", "message": "Another warning"},
            {"event_type": "error", "message": "Failed step"},
            {"event_type": "completed", "message": "Done"},
        ]
        result = engine.create(
            capability_id="cap-3",
            execution_status="failed",
            duration_ms=500,
            events=events,
        )
        assert result["summary"]["warning_count"] == 2
        assert result["summary"]["error_count"] == 1
        assert result["summary"]["event_count"] == 5


# ---------------------------------------------------------------------------
# Engine - status validation
# ---------------------------------------------------------------------------


class TestStatusValidation:
    def test_valid_statuses(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        for status in CapabilityExecutionStatus:
            result = engine.create(
                capability_id="cap-x",
                execution_status=status.value,
            )
            assert result["execution_status"] == status.value

    def test_invalid_status_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid execution_status"):
            engine.create(
                capability_id="cap-x",
                execution_status="exploded",
            )

    def test_invalid_event_type_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid event_type"):
            engine.create(
                capability_id="cap-x",
                execution_status="succeeded",
                events=[{"event_type": "teleported", "message": "?"}],
            )


# ---------------------------------------------------------------------------
# Engine - pass/fail logic
# ---------------------------------------------------------------------------


class TestPassFail:
    def test_succeeded_passes(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="succeeded",
        )
        pf_path = tmp_path / "capability_execution_reports" / result["report_id"] / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is True

    def test_partial_success_passes(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="partial_success",
        )
        pf_path = tmp_path / "capability_execution_reports" / result["report_id"] / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is True

    def test_failed_fails(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="failed",
        )
        pf_path = tmp_path / "capability_execution_reports" / result["report_id"] / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is False

    def test_created_fails(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="created",
        )
        pf_path = tmp_path / "capability_execution_reports" / result["report_id"] / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is False

    def test_running_fails(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-1",
            execution_status="running",
        )
        pf_path = tmp_path / "capability_execution_reports" / result["report_id"] / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is False


# ---------------------------------------------------------------------------
# Engine - deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_events_sorted_by_timestamp(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        events = [
            {"event_type": "completed", "message": "last", "timestamp": "2026-01-01T03:00:00Z"},
            {"event_type": "started", "message": "first", "timestamp": "2026-01-01T01:00:00Z"},
            {"event_type": "warning", "message": "mid", "timestamp": "2026-01-01T02:00:00Z"},
        ]
        result = engine.create(
            capability_id="cap-sort",
            execution_status="succeeded",
            events=events,
        )
        messages = [e["message"] for e in result["events"]]
        assert messages == ["first", "mid", "last"]


# ---------------------------------------------------------------------------
# Engine - evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_evidence_files(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-ev",
            execution_status="succeeded",
        )
        evidence_dir = tmp_path / "capability_execution_reports" / result["report_id"]
        expected_files = {
            "capability_execution_request.json",
            "capability_execution_result.json",
            "capability_execution_summary.md",
            "pass_fail.json",
        }
        actual_files = {f.name for f in evidence_dir.iterdir()}
        assert expected_files.issubset(actual_files)

    def test_request_json_valid(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-ev",
            execution_status="succeeded",
            duration_ms=100,
        )
        evidence_dir = tmp_path / "capability_execution_reports" / result["report_id"]
        data = json.loads((evidence_dir / "capability_execution_request.json").read_text())
        assert data["capability_id"] == "cap-ev"
        assert data["duration_ms"] == 100

    def test_result_json_valid(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-ev",
            execution_status="succeeded",
        )
        evidence_dir = tmp_path / "capability_execution_reports" / result["report_id"]
        data = json.loads((evidence_dir / "capability_execution_result.json").read_text())
        assert data["report_id"] == result["report_id"]

    def test_summary_md_has_header(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-ev",
            execution_status="succeeded",
        )
        evidence_dir = tmp_path / "capability_execution_reports" / result["report_id"]
        md = (evidence_dir / "capability_execution_summary.md").read_text()
        assert "# Capability Execution Report" in md

    def test_duration_in_evidence(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-ev",
            execution_status="succeeded",
            duration_ms=1234,
        )
        evidence_dir = tmp_path / "capability_execution_reports" / result["report_id"]
        pf = json.loads((evidence_dir / "pass_fail.json").read_text())
        assert pf["duration_ms"] == 1234


# ---------------------------------------------------------------------------
# Engine - persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-p",
            execution_status="succeeded",
        )
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_list_reports(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        engine.create(capability_id="cap-a", execution_status="succeeded")
        engine.create(capability_id="cap-b", execution_status="failed")
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_list_reports_sorted_by_created_at(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        r1 = engine.create(capability_id="cap-1", execution_status="succeeded")
        r2 = engine.create(capability_id="cap-2", execution_status="failed")
        reports = engine.list_reports()
        assert reports[0]["report_id"] == r1["report_id"]
        assert reports[1]["report_id"] == r2["report_id"]


# ---------------------------------------------------------------------------
# Engine - export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.create(
            capability_id="cap-exp",
            execution_status="succeeded",
            duration_ms=750,
        )
        md = engine.export_report(result["report_id"])
        assert "# Capability Execution Report" in md
        assert "cap-exp" in md
        assert "750ms" in md

    def test_export_nonexistent_raises(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


# ---------------------------------------------------------------------------
# Engine - safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("foo/../../../etc/passwd")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = CapabilityExecutionReportEngine(artifacts_root=str(tmp_path))
        result = engine.get_report("valid-but-nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# Integration - CommandRegistry
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "capability-report-create" in names
        assert "capability-reports" in names
        assert "capability-report-show" in names
        assert "capability-report-export" in names


# ---------------------------------------------------------------------------
# Integration - test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_execution_report_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_execution_report.py"]
            == "tests/test_capability_execution_report.py"
        )
