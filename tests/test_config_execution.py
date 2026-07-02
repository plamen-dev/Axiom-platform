"""Tests for Configuration Execution Framework v1."""

import json

import pytest
from axiom_core.config_execution import (
    ConfigurationExecutionAction,
    ConfigurationExecutionEngine,
    ConfigurationExecutionReport,
    ConfigurationExecutionRequest,
    ConfigurationExecutionResult,
    ConfigurationExecutionStatus,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationExecutionRequest:
    def test_defaults(self):
        req = ConfigurationExecutionRequest()
        assert req.request_id
        assert req.created_at
        assert req.config_id == ""
        assert req.requested_actions == []

    def test_to_dict(self):
        req = ConfigurationExecutionRequest(
            config_id="cfg-1",
            requested_actions=["verify_only"],
        )
        d = req.to_dict()
        assert d["config_id"] == "cfg-1"
        assert d["requested_actions"] == ["verify_only"]


class TestConfigurationExecutionResult:
    def test_defaults(self):
        result = ConfigurationExecutionResult()
        assert result.result_id
        assert result.status == ConfigurationExecutionStatus.PENDING
        assert result.applied_actions == []
        assert result.failed_actions == []
        assert result.warnings == []

    def test_to_dict(self):
        result = ConfigurationExecutionResult(
            request_id="req-1",
            status=ConfigurationExecutionStatus.SUCCEEDED,
            applied_actions=["verify_only"],
        )
        d = result.to_dict()
        assert d["status"] == "succeeded"
        assert d["applied_actions"] == ["verify_only"]


class TestConfigurationExecutionReport:
    def test_defaults(self):
        report = ConfigurationExecutionReport()
        assert report.report_id
        assert report.status == ConfigurationExecutionStatus.PENDING
        assert report.request is None
        assert report.result is None

    def test_to_dict(self):
        report = ConfigurationExecutionReport(
            request_id="req-1",
            execution_summary="test summary",
            status=ConfigurationExecutionStatus.SUCCEEDED,
        )
        d = report.to_dict()
        assert d["execution_summary"] == "test summary"
        assert d["status"] == "succeeded"


class TestConfigurationExecutionAction:
    def test_values(self):
        assert ConfigurationExecutionAction.APPLY_VALID_CONFIGURATION.value == "apply_valid_configuration"
        assert ConfigurationExecutionAction.APPLY_REPAIR_RECOMMENDATIONS.value == "apply_repair_recommendations"
        assert ConfigurationExecutionAction.VERIFY_ONLY.value == "verify_only"
        assert ConfigurationExecutionAction.NO_ACTION.value == "no_action"


class TestConfigurationExecutionStatus:
    def test_values(self):
        assert ConfigurationExecutionStatus.PENDING.value == "pending"
        assert ConfigurationExecutionStatus.EXECUTING.value == "executing"
        assert ConfigurationExecutionStatus.SUCCEEDED.value == "succeeded"
        assert ConfigurationExecutionStatus.FAILED.value == "failed"
        assert ConfigurationExecutionStatus.PARTIAL_SUCCESS.value == "partial_success"


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestVerifyOnly:
    def test_verify_valid_config(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1", "entry_count": 1, "entries": [{"key": "x", "value": "1"}]},
            validation_report={"config_id": "cfg-1", "valid": True, "violations": [], "error_count": 0, "warning_count": 0},
            actions=["verify_only"],
        )
        assert result["status"] == "succeeded"
        assert result["result"]["applied_actions"] == ["verify_only"]

    def test_verify_invalid_config(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": False, "violations": [{"key": "x", "message": "missing"}], "error_count": 1, "warning_count": 0},
            actions=["verify_only"],
        )
        assert result["status"] == "failed"
        assert result["result"]["failed_actions"] == ["verify_only"]


class TestApplyValidConfiguration:
    def test_apply_valid(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": True},
            actions=["apply_valid_configuration"],
        )
        assert result["status"] == "succeeded"

    def test_apply_invalid_fails(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": False},
            actions=["apply_valid_configuration"],
        )
        assert result["status"] == "failed"

    def test_apply_no_validation_report_fails(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            actions=["apply_valid_configuration"],
        )
        assert result["status"] == "failed"


class TestApplyRepairRecommendations:
    def test_apply_with_repairable(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            repair_report={"config_id": "cfg-1", "repairable_count": 2, "unrepairable_count": 0, "recommendations": [{"action": "add_missing_key", "key": "host"}]},
            actions=["apply_repair_recommendations"],
        )
        assert result["status"] == "succeeded"

    def test_apply_without_repairable(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            repair_report={"config_id": "cfg-1", "repairable_count": 0, "unrepairable_count": 1},
            actions=["apply_repair_recommendations"],
        )
        assert result["status"] == "failed"

    def test_apply_no_repair_report(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            actions=["apply_repair_recommendations"],
        )
        assert result["status"] == "failed"


class TestNoAction:
    def test_no_action_succeeds(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            actions=["no_action"],
        )
        assert result["status"] == "succeeded"
        assert result["result"]["applied_actions"] == ["no_action"]


class TestPartialSuccess:
    def test_mixed_actions(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": True},
            actions=["verify_only", "apply_repair_recommendations"],
        )
        assert result["status"] == "partial_success"
        assert "verify_only" in result["result"]["applied_actions"]
        assert "apply_repair_recommendations" in result["result"]["failed_actions"]


class TestUnknownAction:
    def test_unknown_action_fails(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            actions=["bogus_action"],
        )
        assert result["status"] == "failed"
        assert "bogus_action" in result["result"]["failed_actions"]
        assert any("Unknown action" in w for w in result["result"]["warnings"])


class TestDeterministicOrdering:
    def test_same_order_on_repeated_calls(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        actions = ["no_action", "verify_only"]
        r1 = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": True},
            actions=actions,
        )
        r2 = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": True},
            actions=actions,
        )
        assert r1["result"]["applied_actions"] == r2["result"]["applied_actions"]


class TestEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            actions=["verify_only"],
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_execution" / report_id
        assert (evidence_dir / "config_execution_request.json").exists()
        assert (evidence_dir / "config_execution_result.json").exists()
        assert (evidence_dir / "config_execution_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_contents(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": True},
            actions=["verify_only"],
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_execution" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "succeeded"

    def test_pass_fail_failed(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(
            config={"config_id": "cfg-1"},
            validation_report={"config_id": "cfg-1", "valid": False},
            actions=["apply_valid_configuration"],
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_execution" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False
        assert pf["status"] == "failed"


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(config={"config_id": "cfg-1"}, actions=["no_action"])
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        engine.execute(config={"config_id": "cfg-1"}, actions=["no_action"])
        engine.execute(config={"config_id": "cfg-2"}, actions=["no_action"])
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        result = engine.execute(config={"config_id": "cfg-1"}, actions=["no_action"])
        md = engine.export_report(result["report_id"])
        assert "Configuration Execution Report" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        exec_dir = tmp_path / "config_execution"
        exec_dir.mkdir(parents=True, exist_ok=True)
        link = exec_dir / "evil-link"
        make_symlink_or_skip(link, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_execution_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


class TestCommandRegistryIntegration:
    def test_config_execution_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-execute" in names
        assert "config-execution-show" in names
        assert "config-execution-export" in names


class TestSelectionMapping:
    def test_config_execution_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_execution.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_execution.py"] == "tests/test_config_execution.py"
