"""Tests for Configuration Repair Recommendation Framework v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from axiom_core.config_repair import (
    ConfigurationRepairAction,
    ConfigurationRepairEngine,
    ConfigurationRepairReason,
    ConfigurationRepairRecommendation,
    ConfigurationRepairReport,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Helper: build config dict from entries
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
    valid: bool = False,
    violations: list[dict[str, Any]] | None = None,
    config_id: str = "cfg-1",
    report_id: str = "val-1",
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "config_id": config_id,
        "valid": valid,
        "violations": violations or [],
        "error_count": len(violations) if violations else 0,
        "warning_count": 0,
        "info_count": 0,
    }


# ===========================================================================
# Model tests
# ===========================================================================


class TestConfigurationRepairRecommendation:
    def test_defaults(self) -> None:
        rec = ConfigurationRepairRecommendation()
        assert rec.recommendation_id != ""
        assert rec.action == ConfigurationRepairAction.NO_ACTION
        assert rec.reason == ConfigurationRepairReason.NO_REPAIR_NEEDED
        assert rec.created_at != ""

    def test_to_dict(self) -> None:
        rec = ConfigurationRepairRecommendation(
            recommendation_id="rec-1",
            config_id="cfg-1",
            action=ConfigurationRepairAction.ADD_MISSING_KEY,
            key="host",
            reason=ConfigurationRepairReason.REQUIRED_KEY_MISSING,
        )
        d = rec.to_dict()
        assert d["recommendation_id"] == "rec-1"
        assert d["action"] == "add_missing_key"
        assert d["reason"] == "required_key_missing"
        assert d["key"] == "host"


class TestConfigurationRepairReport:
    def test_defaults(self) -> None:
        report = ConfigurationRepairReport()
        assert report.report_id != ""
        assert report.recommendations == []
        assert report.repairable_count == 0
        assert report.unrepairable_count == 0
        assert report.no_action_count == 0

    def test_to_dict_with_recommendations(self) -> None:
        rec = ConfigurationRepairRecommendation(
            action=ConfigurationRepairAction.CHANGE_VALUE,
            key="env",
        )
        report = ConfigurationRepairReport(
            report_id="rpt-1",
            recommendations=[rec],
            repairable_count=1,
        )
        d = report.to_dict()
        assert d["report_id"] == "rpt-1"
        assert len(d["recommendations"]) == 1
        assert d["repairable_count"] == 1


# ===========================================================================
# Engine: recommendation generation
# ===========================================================================


class TestRequiredKeyMissing:
    def test_generates_add_missing_key(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "host",
            "message": "Required key missing: 'host'",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({})
        report = engine.recommend(vr, config)

        assert report["repairable_count"] == 1
        rec = report["recommendations"][0]
        assert rec["action"] == "add_missing_key"
        assert rec["reason"] == "required_key_missing"
        assert rec["key"] == "host"
        assert rec["recommended_value"] == "<must_be_set>"


class TestValueNotAllowed:
    def test_generates_change_value(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "env",
            "message": "Value 'staging' not in allowed values",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({"env": "staging"})
        report = engine.recommend(vr, config)

        assert report["repairable_count"] == 1
        rec = report["recommendations"][0]
        assert rec["action"] == "change_value"
        assert rec["reason"] == "value_not_allowed"
        assert rec["current_value"] == "staging"


class TestEmptyValue:
    def test_generates_set_non_empty(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "name",
            "message": "Key 'name' must not be empty",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({"name": ""})
        report = engine.recommend(vr, config)

        assert report["repairable_count"] == 1
        rec = report["recommendations"][0]
        assert rec["action"] == "set_non_empty_value"
        assert rec["reason"] == "empty_value"


class TestRegexMismatch:
    def test_generates_change_value(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "port",
            "message": "Value 'abc' does not match pattern",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({"port": "abc"})
        report = engine.recommend(vr, config)

        assert report["repairable_count"] == 1
        rec = report["recommendations"][0]
        assert rec["action"] == "change_value"
        assert rec["reason"] == "regex_mismatch"


class TestUnknownViolation:
    def test_generates_unrepairable(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "x",
            "message": "Custom validator failed",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({"x": "val"})
        report = engine.recommend(vr, config)

        assert report["unrepairable_count"] == 1
        rec = report["recommendations"][0]
        assert rec["action"] == "no_action"
        assert rec["reason"] == "unknown_or_unrepairable"


class TestNoAction:
    def test_no_violations(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True, violations=[])
        config = _make_config({"host": "localhost"})
        report = engine.recommend(vr, config)

        assert report["no_action_count"] == 1
        assert report["repairable_count"] == 0
        assert report["unrepairable_count"] == 0
        rec = report["recommendations"][0]
        assert rec["action"] == "no_action"
        assert rec["reason"] == "no_repair_needed"


class TestMultipleViolations:
    def test_mixed_recommendations(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violations = [
            {"key": "host", "message": "Required key missing: 'host'", "severity": "error"},
            {"key": "env", "message": "Value 'bad' not in allowed values", "severity": "error"},
            {"key": "x", "message": "Unknown issue", "severity": "error"},
        ]
        vr = _make_validation_report(violations=violations)
        config = _make_config({"env": "bad", "x": "val"})
        report = engine.recommend(vr, config)

        assert report["repairable_count"] == 2
        assert report["unrepairable_count"] == 1
        assert len(report["recommendations"]) == 3


# ===========================================================================
# Deterministic ordering
# ===========================================================================


class TestDeterministicOrdering:
    def test_same_order_on_repeated_calls(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violations = [
            {"key": "z", "message": "Required key missing: 'z'", "severity": "error"},
            {"key": "a", "message": "Required key missing: 'a'", "severity": "error"},
            {"key": "m", "message": "Required key missing: 'm'", "severity": "error"},
        ]
        vr = _make_validation_report(violations=violations)
        config = _make_config({})
        r1 = engine.recommend(vr, config)
        r2 = engine.recommend(vr, config)

        keys1 = [r["key"] for r in r1["recommendations"]]
        keys2 = [r["key"] for r in r2["recommendations"]]
        assert keys1 == keys2 == ["z", "a", "m"]


# ===========================================================================
# Evidence
# ===========================================================================


class TestEvidence:
    def test_evidence_files_written(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "host",
            "message": "Required key missing: 'host'",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({})
        report = engine.recommend(vr, config)

        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_repair_recommendations" / report_id

        assert (evidence_dir / "config_repair_request.json").exists()
        assert (evidence_dir / "config_repair_result.json").exists()
        assert (evidence_dir / "config_repair_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_contents(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True, violations=[])
        config = _make_config({"host": "localhost"})
        report = engine.recommend(vr, config)

        report_id = report["report_id"]
        pf_path = tmp_path / "config_repair_recommendations" / report_id / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is True
        assert pf["unrepairable_count"] == 0

    def test_pass_fail_unrepairable(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        violation = {
            "key": "x",
            "message": "Custom validator failed",
            "severity": "error",
        }
        vr = _make_validation_report(violations=[violation])
        config = _make_config({"x": "val"})
        report = engine.recommend(vr, config)

        report_id = report["report_id"]
        pf_path = tmp_path / "config_repair_recommendations" / report_id / "pass_fail.json"
        pf = json.loads(pf_path.read_text())
        assert pf["passed"] is False
        assert pf["unrepairable_count"] == 1


# ===========================================================================
# Persistence and retrieval
# ===========================================================================


class TestPersistence:
    def test_get_report(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True, violations=[])
        report = engine.recommend(vr)
        loaded = engine.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]

    def test_get_report_unknown(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        result = engine.get_report("nonexistent-id")
        assert result is None

    def test_list_reports(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        vr1 = _make_validation_report(valid=True, violations=[], report_id="vr-1")
        vr2 = _make_validation_report(valid=True, violations=[], report_id="vr-2")
        engine.recommend(vr1)
        engine.recommend(vr2)
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        vr = _make_validation_report(valid=True, violations=[])
        report = engine.recommend(vr)
        md = engine.export_report(report["report_id"])
        assert "Configuration Repair Report" in md

    def test_export_report_unknown(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


# ===========================================================================
# Safety / path traversal
# ===========================================================================


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        repairs_dir = tmp_path / "config_repair_recommendations"
        repairs_dir.mkdir(parents=True, exist_ok=True)
        link = repairs_dir / "evil-link"
        make_symlink_or_skip(link, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_repair_path("evil-link")

    def test_empty_id_rejected(self, tmp_path: Path) -> None:
        engine = ConfigurationRepairEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


# ===========================================================================
# Command registry integration
# ===========================================================================


class TestCommandRegistryIntegration:
    def test_config_repair_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        for name in [
            "config-repair-recommend",
            "config-repair-show",
            "config-repair-export",
        ]:
            assert name in names, f"Command '{name}' not registered"


class TestSelectionMapping:
    def test_config_repair_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_repair.py" in _FILE_TO_TEST
        assert (
            _FILE_TO_TEST["src/axiom_core/config_repair.py"]
            == "tests/test_config_repair.py"
        )
