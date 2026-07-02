"""Tests for Configuration Rollback Framework v1."""

import json

import pytest
from axiom_core.config_rollback import (
    ConfigurationRollbackAction,
    ConfigurationRollbackEngine,
    ConfigurationRollbackReport,
    ConfigurationRollbackRequest,
    ConfigurationRollbackResult,
    ConfigurationRollbackStatus,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationRollbackRequest:
    def test_defaults(self):
        req = ConfigurationRollbackRequest()
        assert req.rollback_id
        assert req.created_at
        assert req.execution_result_id == ""
        assert req.requested_actions == []

    def test_to_dict(self):
        req = ConfigurationRollbackRequest(
            execution_result_id="exec-1",
            requested_actions=["verify_only"],
        )
        d = req.to_dict()
        assert d["execution_result_id"] == "exec-1"
        assert d["requested_actions"] == ["verify_only"]


class TestConfigurationRollbackResult:
    def test_defaults(self):
        result = ConfigurationRollbackResult()
        assert result.result_id
        assert result.status == ConfigurationRollbackStatus.PENDING
        assert result.reverted_actions == []
        assert result.failed_actions == []
        assert result.warnings == []

    def test_to_dict(self):
        result = ConfigurationRollbackResult(
            rollback_id="rb-1",
            status=ConfigurationRollbackStatus.SUCCEEDED,
            reverted_actions=["verify_only"],
        )
        d = result.to_dict()
        assert d["status"] == "succeeded"
        assert d["reverted_actions"] == ["verify_only"]


class TestConfigurationRollbackReport:
    def test_defaults(self):
        report = ConfigurationRollbackReport()
        assert report.report_id
        assert report.status == ConfigurationRollbackStatus.PENDING
        assert report.request is None
        assert report.result is None

    def test_to_dict(self):
        report = ConfigurationRollbackReport(
            rollback_id="rb-1",
            rollback_summary="test summary",
            status=ConfigurationRollbackStatus.SUCCEEDED,
        )
        d = report.to_dict()
        assert d["rollback_summary"] == "test summary"
        assert d["status"] == "succeeded"


class TestConfigurationRollbackAction:
    def test_values(self):
        assert ConfigurationRollbackAction.REVERT_APPLIED_CONFIGURATION.value == "revert_applied_configuration"
        assert ConfigurationRollbackAction.REVERT_REPAIR_APPLICATION.value == "revert_repair_application"
        assert ConfigurationRollbackAction.VERIFY_ONLY.value == "verify_only"
        assert ConfigurationRollbackAction.NO_ACTION.value == "no_action"


class TestConfigurationRollbackStatus:
    def test_values(self):
        assert ConfigurationRollbackStatus.PENDING.value == "pending"
        assert ConfigurationRollbackStatus.EXECUTING.value == "executing"
        assert ConfigurationRollbackStatus.SUCCEEDED.value == "succeeded"
        assert ConfigurationRollbackStatus.FAILED.value == "failed"
        assert ConfigurationRollbackStatus.PARTIAL_SUCCESS.value == "partial_success"


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestVerifyOnly:
    def test_verify_with_execution_result(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["verify_only"]},
            actions=["verify_only"],
        )
        assert result["status"] == "succeeded"
        assert result["result"]["reverted_actions"] == ["verify_only"]

    def test_verify_without_execution_result(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result=None,
            actions=["verify_only"],
        )
        assert result["status"] == "failed"
        assert result["result"]["failed_actions"] == ["verify_only"]


class TestRevertAppliedConfiguration:
    def test_revert_when_applied(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["apply_valid_configuration"]},
            actions=["revert_applied_configuration"],
        )
        assert result["status"] == "succeeded"
        assert result["result"]["reverted_actions"] == ["revert_applied_configuration"]

    def test_revert_when_not_applied(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["verify_only"]},
            actions=["revert_applied_configuration"],
        )
        assert result["status"] == "failed"
        assert result["result"]["failed_actions"] == ["revert_applied_configuration"]
        assert any("was not in applied actions" in w for w in result["result"]["warnings"])


class TestRevertRepairApplication:
    def test_revert_when_repair_applied(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["apply_repair_recommendations"]},
            actions=["revert_repair_application"],
        )
        assert result["status"] == "succeeded"

    def test_revert_when_repair_not_applied(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["revert_repair_application"],
        )
        assert result["status"] == "failed"


class TestNoAction:
    def test_no_action_succeeds(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["no_action"],
        )
        assert result["status"] == "succeeded"
        assert result["result"]["reverted_actions"] == ["no_action"]


class TestPartialSuccess:
    def test_mixed_actions(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["apply_valid_configuration"]},
            actions=["revert_applied_configuration", "revert_repair_application"],
        )
        assert result["status"] == "partial_success"
        assert "revert_applied_configuration" in result["result"]["reverted_actions"]
        assert "revert_repair_application" in result["result"]["failed_actions"]


class TestUnknownAction:
    def test_unknown_action_fails(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["bogus_action"],
        )
        assert result["status"] == "failed"
        assert "bogus_action" in result["result"]["failed_actions"]
        assert any("Unknown rollback action" in w for w in result["result"]["warnings"])


class TestDeterministicOrdering:
    def test_same_order_on_repeated_calls(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        actions = ["no_action", "verify_only"]
        r1 = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=actions,
        )
        r2 = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=actions,
        )
        assert r1["result"]["reverted_actions"] == r2["result"]["reverted_actions"]


class TestEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["no_action"],
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_rollback" / report_id
        assert (evidence_dir / "config_rollback_request.json").exists()
        assert (evidence_dir / "config_rollback_result.json").exists()
        assert (evidence_dir / "config_rollback_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_succeeded(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": ["apply_valid_configuration"]},
            actions=["revert_applied_configuration"],
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_rollback" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "succeeded"

    def test_pass_fail_failed(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["revert_applied_configuration"],
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_rollback" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False
        assert pf["status"] == "failed"


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["no_action"],
        )
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        engine.rollback(execution_result={"result_id": "e1", "applied_actions": []}, actions=["no_action"])
        engine.rollback(execution_result={"result_id": "e2", "applied_actions": []}, actions=["no_action"])
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        result = engine.rollback(
            execution_result={"result_id": "exec-1", "applied_actions": []},
            actions=["no_action"],
        )
        md = engine.export_report(result["report_id"])
        assert "Configuration Rollback Report" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        rb_dir = tmp_path / "config_rollback"
        rb_dir.mkdir(parents=True, exist_ok=True)
        link = rb_dir / "evil-link"
        make_symlink_or_skip(link, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_rollback_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationRollbackEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


class TestCommandRegistryIntegration:
    def test_config_rollback_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-rollback" in names
        assert "config-rollback-show" in names
        assert "config-rollback-export" in names


class TestSelectionMapping:
    def test_config_rollback_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_rollback.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_rollback.py"] == "tests/test_config_rollback.py"
