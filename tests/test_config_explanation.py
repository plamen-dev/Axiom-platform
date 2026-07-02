"""Tests for Configuration Explanation Framework v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from axiom_core.config_explanation import (
    ConfigurationExplanation,
    ConfigurationExplanationEngine,
    ConfigurationExplanationReport,
    ConfigurationExplanationSection,
    ConfigurationExplanationType,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(entries: dict[str, str], config_id: str = "cfg-1") -> dict[str, Any]:
    return {
        "config_id": config_id,
        "file_name": "test.cfg",
        "entries": [{"key": k, "value": v} for k, v in entries.items()],
        "entry_count": len(entries),
    }


def _make_validation_report(
    *,
    valid: bool = True,
    violations: list[dict[str, Any]] | None = None,
    config_id: str = "cfg-1",
    report_id: str = "val-1",
    error_count: int = 0,
    warning_count: int = 0,
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "config_id": config_id,
        "valid": valid,
        "violations": violations or [],
        "error_count": error_count,
        "warning_count": warning_count,
    }


def _make_repair_report(
    *,
    recommendations: list[dict[str, Any]] | None = None,
    config_id: str = "cfg-1",
    report_id: str = "rep-1",
    repairable_count: int = 0,
    unrepairable_count: int = 0,
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "config_id": config_id,
        "recommendations": recommendations or [],
        "repairable_count": repairable_count,
        "unrepairable_count": unrepairable_count,
        "no_action_count": 0,
    }


# ===========================================================================
# Model tests
# ===========================================================================


class TestConfigurationExplanation:
    def test_defaults(self) -> None:
        exp = ConfigurationExplanation()
        assert exp.explanation_id != ""
        assert exp.explanation_type == ConfigurationExplanationType.CONFIGURATION_SUMMARY
        assert exp.created_at != ""

    def test_to_dict(self) -> None:
        exp = ConfigurationExplanation(
            explanation_id="exp-1",
            config_id="cfg-1",
            explanation_type=ConfigurationExplanationType.VALIDATION_EXPLANATION,
            summary="Test summary",
            rationale="Test rationale",
        )
        d = exp.to_dict()
        assert d["explanation_id"] == "exp-1"
        assert d["explanation_type"] == "validation_explanation"
        assert d["summary"] == "Test summary"


class TestConfigurationExplanationSection:
    def test_to_dict(self) -> None:
        sec = ConfigurationExplanationSection(
            title="Test Section",
            content="Some content",
            references=["ref-1", "ref-2"],
        )
        d = sec.to_dict()
        assert d["title"] == "Test Section"
        assert d["content"] == "Some content"
        assert d["references"] == ["ref-1", "ref-2"]


class TestConfigurationExplanationReport:
    def test_defaults(self) -> None:
        report = ConfigurationExplanationReport()
        assert report.report_id != ""
        assert report.explanation_count == 0
        assert report.sections == []
        assert report.explanations == []

    def test_to_dict(self) -> None:
        report = ConfigurationExplanationReport(
            report_id="rpt-1",
            config_id="cfg-1",
            explanation_count=2,
        )
        d = report.to_dict()
        assert d["report_id"] == "rpt-1"
        assert d["explanation_count"] == 2


# ===========================================================================
# Engine: explanation generation
# ===========================================================================


class TestConfigurationSummary:
    def test_config_only(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        config = _make_config({"host": "localhost", "port": "8080"})
        report = engine.explain(config=config)

        assert report["explanation_count"] >= 1
        types = [e["explanation_type"] for e in report["explanations"]]
        assert "configuration_summary" in types
        sections = report["sections"]
        assert any("Configuration Summary" in s["title"] for s in sections)


class TestValidationExplanation:
    def test_passing_validation(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True)
        report = engine.explain(validation_report=vr)

        types = [e["explanation_type"] for e in report["explanations"]]
        assert "validation_explanation" in types
        summaries = [e["summary"] for e in report["explanations"]]
        assert any("passed" in s for s in summaries)

    def test_failing_validation_with_errors(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        violations = [
            {"key": "host", "message": "Required key missing", "severity": "error"},
            {"key": "port", "message": "Value too large", "severity": "warning"},
        ]
        vr = _make_validation_report(
            valid=False,
            violations=violations,
            error_count=1,
            warning_count=1,
        )
        report = engine.explain(validation_report=vr)

        types = [e["explanation_type"] for e in report["explanations"]]
        assert "validation_explanation" in types
        assert "error_explanation" in types
        assert "warning_explanation" in types

    def test_error_explanation_content(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        violations = [
            {"key": "db_host", "message": "Required key missing", "severity": "error"},
        ]
        vr = _make_validation_report(valid=False, violations=violations, error_count=1)
        report = engine.explain(validation_report=vr)

        error_exps = [
            e for e in report["explanations"]
            if e["explanation_type"] == "error_explanation"
        ]
        assert len(error_exps) == 1
        assert "db_host" in error_exps[0]["summary"]


class TestRepairExplanation:
    def test_with_recommendations(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        recs = [
            {
                "action": "add_missing_key",
                "key": "host",
                "rationale": "Key 'host' is required.",
            },
        ]
        rr = _make_repair_report(recommendations=recs, repairable_count=1)
        report = engine.explain(repair_report=rr)

        types = [e["explanation_type"] for e in report["explanations"]]
        assert "repair_explanation" in types
        sections = report["sections"]
        assert any("Repair" in s["title"] for s in sections)

    def test_no_recommendations(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        rr = _make_repair_report(recommendations=[])
        report = engine.explain(repair_report=rr)

        repair_exps = [
            e for e in report["explanations"]
            if e["explanation_type"] == "repair_explanation"
        ]
        assert len(repair_exps) == 1
        assert "No repair" in repair_exps[0]["summary"]


class TestWarningExplanation:
    def test_warning_violation(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        violations = [
            {"key": "timeout", "message": "Unusually high value", "severity": "warning"},
        ]
        vr = _make_validation_report(
            valid=False, violations=violations, warning_count=1,
        )
        report = engine.explain(validation_report=vr)

        warning_exps = [
            e for e in report["explanations"]
            if e["explanation_type"] == "warning_explanation"
        ]
        assert len(warning_exps) == 1
        assert "timeout" in warning_exps[0]["summary"]


class TestCombinedExplanation:
    def test_all_inputs(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        config = _make_config({"env": "prod"})
        violations = [
            {"key": "host", "message": "Required key missing", "severity": "error"},
        ]
        vr = _make_validation_report(valid=False, violations=violations, error_count=1)
        recs = [
            {"action": "add_missing_key", "key": "host", "rationale": "Missing key."},
        ]
        rr = _make_repair_report(recommendations=recs, repairable_count=1)

        report = engine.explain(
            validation_report=vr, repair_report=rr, config=config,
        )

        types = [e["explanation_type"] for e in report["explanations"]]
        assert "configuration_summary" in types
        assert "validation_explanation" in types
        assert "error_explanation" in types
        assert "repair_explanation" in types
        assert report["explanation_count"] >= 4


# ===========================================================================
# Deterministic ordering
# ===========================================================================


class TestDeterministicOrdering:
    def test_same_order_on_repeated_calls(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1", "b": "2"})
        violations = [
            {"key": "x", "message": "Required key missing: 'x'", "severity": "error"},
            {"key": "y", "message": "Required key missing: 'y'", "severity": "error"},
        ]
        vr = _make_validation_report(valid=False, violations=violations, error_count=2)

        r1 = engine.explain(validation_report=vr, config=config)
        r2 = engine.explain(validation_report=vr, config=config)

        types1 = [e["explanation_type"] for e in r1["explanations"]]
        types2 = [e["explanation_type"] for e in r2["explanations"]]
        assert types1 == types2

        summaries1 = [e["summary"] for e in r1["explanations"]]
        summaries2 = [e["summary"] for e in r2["explanations"]]
        assert summaries1 == summaries2


# ===========================================================================
# Evidence
# ===========================================================================


class TestEvidence:
    def test_evidence_files_written(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True)
        report = engine.explain(validation_report=vr)

        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_explanations" / report_id

        assert (evidence_dir / "config_explanation_request.json").exists()
        assert (evidence_dir / "config_explanation_result.json").exists()
        assert (evidence_dir / "config_explanation_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_contents(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True)
        report = engine.explain(validation_report=vr)

        report_id = report["report_id"]
        pf_path = tmp_path / "config_explanations" / report_id / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is True
        assert pf["explanation_count"] >= 1


# ===========================================================================
# Persistence and retrieval
# ===========================================================================


class TestPersistence:
    def test_get_report(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True)
        report = engine.explain(validation_report=vr)
        loaded = engine.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]

    def test_get_report_unknown(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        result = engine.get_report("nonexistent-id")
        assert result is None

    def test_list_reports(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr1 = _make_validation_report(valid=True, report_id="vr-1")
        vr2 = _make_validation_report(valid=True, report_id="vr-2")
        engine.explain(validation_report=vr1)
        engine.explain(validation_report=vr2)
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True)
        report = engine.explain(validation_report=vr)
        md = engine.export_report(report["report_id"])
        assert "Configuration Explanation Report" in md

    def test_export_report_unknown(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


# ===========================================================================
# Safety / path traversal
# ===========================================================================


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        explanations_dir = tmp_path / "config_explanations"
        explanations_dir.mkdir(parents=True, exist_ok=True)
        link = explanations_dir / "evil-link"
        make_symlink_or_skip(link, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_explanation_path("evil-link")

    def test_empty_id_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationExplanationEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


# ===========================================================================
# Command registry integration
# ===========================================================================


class TestCommandRegistryIntegration:
    def test_config_explanation_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        for name in [
            "config-explain",
            "config-explanation-show",
            "config-explanation-export",
        ]:
            assert name in names, f"Command '{name}' not registered"


class TestSelectionMapping:
    def test_config_explanation_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_explanation.py" in _FILE_TO_TEST
        assert (
            _FILE_TO_TEST["src/axiom_core/config_explanation.py"]
            == "tests/test_config_explanation.py"
        )
