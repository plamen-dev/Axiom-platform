"""Tests for Configuration Batch Execution Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.config_batch_execution import (
    ConfigurationBatchExecutionEngine,
    ConfigurationBatchExecutionItem,
    ConfigurationBatchExecutionReport,
    ConfigurationBatchExecutionRequest,
    ConfigurationBatchExecutionResult,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_request_auto_id(self):
        r = ConfigurationBatchExecutionRequest(scenario_ids=["s1", "s2"])
        assert r.batch_id
        assert r.scenario_ids == ["s1", "s2"]
        assert r.created_at

    def test_item_auto_id(self):
        item = ConfigurationBatchExecutionItem(scenario_id="s1", status="succeeded")
        assert item.item_id
        assert item.scenario_id == "s1"

    def test_result_auto_id(self):
        r = ConfigurationBatchExecutionResult(batch_id="b1", total_count=3)
        assert r.result_id
        assert r.batch_id == "b1"
        assert r.total_count == 3

    def test_report_auto_id(self):
        r = ConfigurationBatchExecutionReport(batch_id="b1")
        assert r.report_id
        assert r.batch_id == "b1"

    def test_request_to_dict(self):
        r = ConfigurationBatchExecutionRequest(
            scenario_ids=["s1"], execution_mode="stop_on_failure"
        )
        d = r.to_dict()
        assert d["scenario_ids"] == ["s1"]
        assert d["execution_mode"] == "stop_on_failure"

    def test_item_to_dict(self):
        item = ConfigurationBatchExecutionItem(
            scenario_id="s1", status="failed", passed=False, warnings=["warn1"]
        )
        d = item.to_dict()
        assert d["scenario_id"] == "s1"
        assert d["passed"] is False
        assert d["warnings"] == ["warn1"]


# ---------------------------------------------------------------------------
# Engine - RUN_ALL mode
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_all_succeed(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": []},
            {"scenario_id": "s2", "expectations": []},
            {"scenario_id": "s3", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2", "s3"],
            execution_mode="run_all",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["total_count"] == 3
        assert result["succeeded_count"] == 3
        assert result["failed_count"] == 0
        assert result["skipped_count"] == 0

    def test_mixed_pass_fail(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": []},
            {"scenario_id": "s2", "expectations": [{"will_fail": True}]},
            {"scenario_id": "s3", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2", "s3"],
            execution_mode="run_all",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["succeeded_count"] == 2
        assert result["failed_count"] == 1
        assert result["skipped_count"] == 0

    def test_all_fail(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": [{"will_fail": True}]},
            {"scenario_id": "s2", "expectations": [{"will_fail": True}]},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2"],
            execution_mode="run_all",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["succeeded_count"] == 0
        assert result["failed_count"] == 2
        assert result["skipped_count"] == 0

    def test_empty_batch(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(scenario_ids=[], execution_mode="run_all", scenarios=[])
        result = report["result"]
        assert result["total_count"] == 0
        assert result["succeeded_count"] == 0


# ---------------------------------------------------------------------------
# Engine - STOP_ON_FAILURE mode
# ---------------------------------------------------------------------------


class TestStopOnFailure:
    def test_stops_after_first_failure(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": []},
            {"scenario_id": "s2", "expectations": [{"will_fail": True}]},
            {"scenario_id": "s3", "expectations": []},
            {"scenario_id": "s4", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2", "s3", "s4"],
            execution_mode="stop_on_failure",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["total_count"] == 4
        assert result["succeeded_count"] == 1
        assert result["failed_count"] == 1
        assert result["skipped_count"] == 2

        items = result["items"]
        assert items[0]["status"] == "succeeded"
        assert items[1]["status"] == "failed"
        assert items[2]["status"] == "skipped"
        assert items[3]["status"] == "skipped"

    def test_no_failure_runs_all(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": []},
            {"scenario_id": "s2", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2"],
            execution_mode="stop_on_failure",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["succeeded_count"] == 2
        assert result["skipped_count"] == 0


# ---------------------------------------------------------------------------
# Engine - VERIFY_ONLY mode
# ---------------------------------------------------------------------------


class TestVerifyOnly:
    def test_all_verified_not_executed(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "s1", "expectations": [{"will_fail": True}]},
            {"scenario_id": "s2", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["s1", "s2"],
            execution_mode="verify_only",
            scenarios=scenarios,
        )
        result = report["result"]
        assert result["succeeded_count"] == 2
        assert result["failed_count"] == 0
        assert result["warning_count"] == 2

        for item in result["items"]:
            assert item["status"] == "succeeded"
            assert item["passed"] is True
            assert "verify_only" in item["warnings"][0]


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_items_preserve_input_order(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        scenarios = [
            {"scenario_id": "zebra", "expectations": []},
            {"scenario_id": "alpha", "expectations": []},
            {"scenario_id": "middle", "expectations": []},
        ]
        report = engine.run(
            scenario_ids=["zebra", "alpha", "middle"],
            execution_mode="run_all",
            scenarios=scenarios,
        )
        result_ids = [i["scenario_id"] for i in report["result"]["items"]]
        assert result_ids == ["zebra", "alpha", "middle"]


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"],
            execution_mode="run_all",
            scenarios=[{"scenario_id": "s1", "expectations": []}],
        )
        report_id = report["report_id"]

        evidence_dir = tmp_path / "config_batch_execution" / report_id
        assert (evidence_dir / "config_batch_request.json").exists()
        assert (evidence_dir / "config_batch_result.json").exists()
        assert (evidence_dir / "config_batch_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_no_failures(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"],
            execution_mode="run_all",
            scenarios=[{"scenario_id": "s1", "expectations": []}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "config_batch_execution" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True

    def test_pass_fail_false_when_failures(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"],
            execution_mode="run_all",
            scenarios=[{"scenario_id": "s1", "expectations": [{"will_fail": True}]}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "config_batch_execution" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"],
            execution_mode="run_all",
            scenarios=[{"scenario_id": "s1", "expectations": []}],
        )
        report_id = report["report_id"]

        md = (
            tmp_path / "config_batch_execution" / report_id / "config_batch_summary.md"
        ).read_text()
        assert "# Configuration Batch Execution Report" in md


# ---------------------------------------------------------------------------
# Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"],
            execution_mode="run_all",
            scenarios=[{"scenario_id": "s1", "expectations": []}],
        )
        report_id = report["report_id"]

        loaded = engine.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id

    def test_list_reports(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        engine.run(scenario_ids=["s1"], scenarios=[{"scenario_id": "s1", "expectations": []}])
        engine.run(scenario_ids=["s2"], scenarios=[{"scenario_id": "s2", "expectations": []}])

        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        report = engine.run(
            scenario_ids=["s1"], scenarios=[{"scenario_id": "s1", "expectations": []}]
        )
        report_id = report["report_id"]

        md = engine.export_report(report_id)
        assert "# Configuration Batch Execution Report" in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        batch_dir = tmp_path / "config_batch_execution"
        batch_dir.mkdir(exist_ok=True)
        link_name = batch_dir / "evil-link"
        make_symlink_or_skip(link_name, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_batch_path("evil-link")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = ConfigurationBatchExecutionEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# CommandRegistry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "config-batch-run" in names
        assert "config-batch-show" in names
        assert "config-batch-export" in names


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_config_batch_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/config_batch_execution.py"]
            == "tests/test_config_batch_execution.py"
        )
