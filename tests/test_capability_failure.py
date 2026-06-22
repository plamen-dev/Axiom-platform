"""Tests for the Capability Failure Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_failure import (
    CapabilityFailure,
    CapabilityFailureEngine,
    CapabilityFailureEvidence,
    CapabilityFailureReport,
    CapabilityFailureType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilityFailureEngine:
    return CapabilityFailureEngine(artifacts_root=str(tmp_path))


def _sample_failures() -> list[dict]:
    return [
        {
            "failure_type": "execution_failure",
            "severity": "error",
            "message": "Command timed out",
            "details": "Exceeded 60s timeout",
        },
        {
            "failure_type": "input_failure",
            "severity": "warning",
            "message": "Optional input missing",
            "details": "",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_failure_defaults(self) -> None:
        f = CapabilityFailure()
        assert f.failure_id
        assert f.created_at
        assert f.failure_type == "execution_failure"
        assert f.severity == "error"

    def test_failure_report_defaults(self) -> None:
        r = CapabilityFailureReport()
        assert r.report_id
        assert r.created_at
        assert r.failure_count == 0

    def test_failure_evidence_defaults(self) -> None:
        e = CapabilityFailureEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=[])
        assert result["failure_count"] == 0
        assert result["blocker_count"] == 0
        assert result["error_count"] == 0
        assert result["warning_count"] == 0
        assert result["info_count"] == 0

    def test_create_with_failures(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        assert result["failure_count"] == 2
        assert result["error_count"] == 1
        assert result["warning_count"] == 1

    def test_create_with_all_severities(self, engine: CapabilityFailureEngine) -> None:
        failures = [
            {"failure_type": "timeout", "severity": "blocker", "message": "a"},
            {"failure_type": "execution_failure", "severity": "error", "message": "b"},
            {"failure_type": "input_failure", "severity": "warning", "message": "c"},
            {"failure_type": "output_failure", "severity": "info", "message": "d"},
        ]
        result = engine.create(failures=failures)
        assert result["failure_count"] == 4
        assert result["blocker_count"] == 1
        assert result["error_count"] == 1
        assert result["warning_count"] == 1
        assert result["info_count"] == 1


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_failure_types(self, engine: CapabilityFailureEngine) -> None:
        for ft in CapabilityFailureType:
            result = engine.create(
                failures=[{"failure_type": ft.value, "severity": "error", "message": "x"}]
            )
            assert result["failure_count"] == 1

    def test_invalid_failure_type_rejected(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError, match="Invalid failure_type"):
            engine.create(
                failures=[{"failure_type": "unknown_type", "severity": "error", "message": "x"}]
            )

    def test_invalid_severity_rejected(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError, match="Invalid severity"):
            engine.create(
                failures=[{"failure_type": "timeout", "severity": "critical", "message": "x"}]
            )


# ---------------------------------------------------------------------------
# TestPassFail
# ---------------------------------------------------------------------------


class TestPassFail:
    def test_no_failures_passes(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=[])
        report_id = result["report_id"]
        report_dir = Path(engine._report_dir) / report_id
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_only_warnings_passes(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(
            failures=[{"failure_type": "input_failure", "severity": "warning", "message": "w"}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_only_info_passes(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(
            failures=[{"failure_type": "input_failure", "severity": "info", "message": "i"}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_error_fails(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(
            failures=[{"failure_type": "timeout", "severity": "error", "message": "e"}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"

    def test_blocker_fails(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(
            failures=[{"failure_type": "internal_error", "severity": "blocker", "message": "b"}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_failures_ordered_by_severity_then_message(
        self, engine: CapabilityFailureEngine
    ) -> None:
        failures = [
            {"failure_type": "timeout", "severity": "info", "message": "z"},
            {"failure_type": "timeout", "severity": "blocker", "message": "a"},
            {"failure_type": "timeout", "severity": "error", "message": "b"},
            {"failure_type": "timeout", "severity": "warning", "message": "c"},
        ]
        result = engine.create(failures=failures)
        severities = [f["severity"] for f in result["failures"]]
        assert severities == ["blocker", "error", "warning", "info"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_failure_request.json",
            "capability_failure_result.json",
            "capability_failure_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_failure_request.json").read_text())
        assert "failures" in data

    def test_result_valid_json(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_failure_result.json").read_text())
        assert data["failure_count"] == 2

    def test_summary_has_header(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_failure_summary.md").read_text()
        assert "# Capability Failure Report" in md

    def test_severity_in_evidence(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(
            failures=[{"failure_type": "timeout", "severity": "blocker", "message": "x"}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["blocker_count"] == 1


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["failure_count"] == 2

    def test_list_reports_deterministic(self, engine: CapabilityFailureEngine) -> None:
        engine.create(failures=_sample_failures())
        engine.create(failures=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        # sorted by created_at
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: CapabilityFailureEngine) -> None:
        result = engine.create(failures=_sample_failures())
        md = engine.export_report(result["report_id"])
        assert "# Capability Failure Report" in md
        assert "ERROR" in md

    def test_export_nonexistent_raises(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: CapabilityFailureEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, engine: CapabilityFailureEngine, tmp_path: Path) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: CapabilityFailureEngine) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {
            "capability-failure-create",
            "capability-failures",
            "capability-failure-show",
            "capability-failure-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_failure_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_failure.py"]
            == "tests/test_capability_failure.py"
        )
