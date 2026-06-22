"""Tests for Configuration Scenario Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.config_scenario import (
    ConfigurationScenario,
    ConfigurationScenarioEngine,
    ConfigurationScenarioExpectation,
    ConfigurationScenarioReport,
    ConfigurationScenarioResult,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_expectation_auto_id(self):
        exp = ConfigurationScenarioExpectation(
            expectation_type="policy_pass",
            severity="error",
        )
        assert exp.expectation_id
        assert exp.expectation_type == "policy_pass"

    def test_scenario_auto_id(self):
        s = ConfigurationScenario(name="test-scenario")
        assert s.scenario_id
        assert s.name == "test-scenario"
        assert s.created_at

    def test_result_auto_id(self):
        r = ConfigurationScenarioResult(scenario_id="s1", passed=True)
        assert r.result_id
        assert r.scenario_id == "s1"
        assert r.passed is True

    def test_report_auto_id(self):
        r = ConfigurationScenarioReport(scenario_id="s1")
        assert r.report_id
        assert r.scenario_id == "s1"
        assert r.created_at

    def test_scenario_to_dict(self):
        exp = ConfigurationScenarioExpectation(
            expectation_type="policy_pass",
            severity="blocker",
            rationale="must pass policy",
        )
        s = ConfigurationScenario(
            name="prod-deploy",
            description="Production deployment scenario",
            config_id="C1",
            policy_id="P1",
            expectations=[exp],
        )
        d = s.to_dict()
        assert d["name"] == "prod-deploy"
        assert d["config_id"] == "C1"
        assert len(d["expectations"]) == 1
        assert d["expectations"][0]["severity"] == "blocker"


# ---------------------------------------------------------------------------
# Engine tests - expectation types
# ---------------------------------------------------------------------------


class TestExpectationTypes:
    def test_policy_pass_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "policy-pass-scenario",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": True})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_policy_pass_not_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "policy-pass-scenario",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": False})
        assert report["result"]["passed"] is False
        assert report["result"]["expectation_results"][0]["met"] is False

    def test_policy_fail_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "negative-test",
            "expectations": [
                {"expectation_type": "policy_fail", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": False})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_policy_fail_not_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "negative-test",
            "expectations": [
                {"expectation_type": "policy_fail", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": True})
        assert report["result"]["passed"] is False

    def test_validation_pass_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "val-pass",
            "expectations": [
                {"expectation_type": "validation_pass", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, validation_result={"passed": True})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_validation_fail_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "val-fail",
            "expectations": [
                {"expectation_type": "validation_fail", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, validation_result={"passed": False})
        assert report["result"]["passed"] is True

    def test_execution_succeeds_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "exec-pass",
            "expectations": [
                {"expectation_type": "execution_succeeds", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, execution_result={"status": "succeeded"})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_execution_succeeds_not_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "exec-pass",
            "expectations": [
                {"expectation_type": "execution_succeeds", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, execution_result={"status": "failed"})
        assert report["result"]["passed"] is False

    def test_execution_fails_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "exec-fail",
            "expectations": [
                {"expectation_type": "execution_fails", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, execution_result={"status": "failed"})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_no_blockers_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "no-blockers",
            "expectations": [
                {"expectation_type": "no_blockers", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"blocker_count": 0})
        assert report["result"]["passed"] is True
        assert report["result"]["expectation_results"][0]["met"] is True

    def test_no_blockers_not_met(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "no-blockers",
            "expectations": [
                {"expectation_type": "no_blockers", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"blocker_count": 2})
        assert report["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Severity and pass semantics
# ---------------------------------------------------------------------------


class TestSeveritySemantics:
    def test_warning_unmet_does_not_fail(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "warning-only",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "warning"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": False})
        assert report["result"]["passed"] is True
        assert report["result"]["warning_count"] == 1

    def test_blocker_unmet_fails(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "blocker-fail",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "blocker"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": False})
        assert report["result"]["passed"] is False
        assert report["result"]["blocker_count"] == 1

    def test_mixed_severities(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "mixed",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "blocker"},
                {"expectation_type": "validation_pass", "severity": "warning"},
                {"expectation_type": "execution_succeeds", "severity": "error"},
            ],
        }
        report = engine.run(
            scenario=scenario,
            policy_result={"passed": False},
            validation_result={"passed": False},
            execution_result={"status": "failed"},
        )
        assert report["result"]["passed"] is False
        assert report["result"]["blocker_count"] == 1
        assert report["result"]["warning_count"] == 1


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_expectations_sorted_by_type(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "ordering",
            "expectations": [
                {"expectation_type": "validation_pass", "severity": "error"},
                {"expectation_type": "execution_succeeds", "severity": "error"},
                {"expectation_type": "no_blockers", "severity": "error"},
                {"expectation_type": "policy_pass", "severity": "error"},
            ],
        }
        report = engine.run(
            scenario=scenario,
            policy_result={"passed": True, "blocker_count": 0},
            validation_result={"passed": True},
            execution_result={"status": "succeeded"},
        )
        types = [er["expectation_type"] for er in report["result"]["expectation_results"]]
        assert types == sorted(types)


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {"name": "evidence-test"}
        report = engine.run(scenario=scenario)
        report_id = report["report_id"]

        evidence_dir = tmp_path / "config_scenarios" / report_id
        assert (evidence_dir / "config_scenario_request.json").exists()
        assert (evidence_dir / "config_scenario_result.json").exists()
        assert (evidence_dir / "config_scenario_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_passed(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "pass-test",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": True})
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "config_scenarios" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_false_when_failed(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {
            "name": "fail-test",
            "expectations": [
                {"expectation_type": "policy_pass", "severity": "error"},
            ],
        }
        report = engine.run(scenario=scenario, policy_result={"passed": False})
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "config_scenarios" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {"name": "md-test"}
        report = engine.run(scenario=scenario)
        report_id = report["report_id"]

        md = (tmp_path / "config_scenarios" / report_id / "config_scenario_summary.md").read_text()
        assert "# Configuration Scenario Report" in md


# ---------------------------------------------------------------------------
# Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenario = {"name": "persist-test"}
        report = engine.run(scenario=scenario)
        report_id = report["report_id"]

        loaded = engine.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id

    def test_list_reports(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        engine.run(scenario={"name": "s1"})
        engine.run(scenario={"name": "s2"})

        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        report = engine.run(scenario={"name": "export-test"})
        report_id = report["report_id"]

        md = engine.export_report(report_id)
        assert "# Configuration Scenario Report" in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        scenarios_dir = tmp_path / "config_scenarios"
        scenarios_dir.mkdir(exist_ok=True)
        link_name = scenarios_dir / "evil-link"
        link_name.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_scenario_path("evil-link")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = ConfigurationScenarioEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# CommandRegistry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "config-scenario-run" in names
        assert "config-scenario-show" in names
        assert "config-scenario-export" in names


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_config_scenario_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert _FILE_TO_TEST["src/axiom_core/config_scenario.py"] == "tests/test_config_scenario.py"
