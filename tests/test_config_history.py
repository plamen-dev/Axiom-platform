"""Tests for Configuration Change History Framework v1."""

import json

import pytest
from axiom_core.config_history import (
    ConfigurationChangeEvent,
    ConfigurationChangeEventType,
    ConfigurationChangeHistory,
    ConfigurationChangeHistoryEngine,
    ConfigurationChangeHistoryReport,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationChangeEvent:
    def test_defaults(self):
        event = ConfigurationChangeEvent()
        assert event.event_id
        assert event.created_at
        assert event.config_id == ""
        assert event.event_type == ""

    def test_to_dict(self):
        event = ConfigurationChangeEvent(
            config_id="cfg-1",
            event_type="config_loaded",
            source_id="src-1",
            summary="Loaded 5 entries",
        )
        d = event.to_dict()
        assert d["config_id"] == "cfg-1"
        assert d["event_type"] == "config_loaded"
        assert d["source_id"] == "src-1"


class TestConfigurationChangeHistory:
    def test_defaults(self):
        history = ConfigurationChangeHistory()
        assert history.history_id
        assert history.events == []
        assert history.event_count == 0

    def test_with_events(self):
        events = [ConfigurationChangeEvent(event_type="config_loaded")]
        history = ConfigurationChangeHistory(events=events)
        assert history.event_count == 1

    def test_to_dict(self):
        events = [ConfigurationChangeEvent(event_type="config_loaded")]
        history = ConfigurationChangeHistory(config_id="cfg-1", events=events)
        d = history.to_dict()
        assert d["config_id"] == "cfg-1"
        assert d["event_count"] == 1
        assert len(d["events"]) == 1


class TestConfigurationChangeHistoryReport:
    def test_defaults(self):
        report = ConfigurationChangeHistoryReport()
        assert report.report_id
        assert report.event_count == 0
        assert report.history is None

    def test_to_dict(self):
        report = ConfigurationChangeHistoryReport(
            config_id="cfg-1",
            timeline_summary="test summary",
            event_count=3,
        )
        d = report.to_dict()
        assert d["config_id"] == "cfg-1"
        assert d["timeline_summary"] == "test summary"
        assert d["event_count"] == 3


class TestConfigurationChangeEventType:
    def test_values(self):
        assert ConfigurationChangeEventType.CONFIG_LOADED.value == "config_loaded"
        assert ConfigurationChangeEventType.CONFIG_VALIDATED.value == "config_validated"
        assert ConfigurationChangeEventType.REPAIR_RECOMMENDED.value == "repair_recommended"
        assert ConfigurationChangeEventType.EXPLANATION_GENERATED.value == "explanation_generated"
        assert ConfigurationChangeEventType.EXECUTION_COMPLETED.value == "execution_completed"
        assert ConfigurationChangeEventType.ROLLBACK_COMPLETED.value == "rollback_completed"
        assert ConfigurationChangeEventType.NO_ACTION.value == "no_action"


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestCreateHistoryWithConfig:
    def test_config_only(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 3},
        )
        assert result["event_count"] == 1
        events = result["history"]["events"]
        assert events[0]["event_type"] == "config_loaded"
        assert "3 entries" in events[0]["summary"]


class TestCreateHistoryWithValidation:
    def test_config_and_validation(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            validation_report={"report_id": "v-1", "valid": True, "error_count": 0, "warning_count": 0},
        )
        assert result["event_count"] == 2
        types = [e["event_type"] for e in result["history"]["events"]]
        assert types == ["config_loaded", "config_validated"]


class TestCreateHistoryWithRepair:
    def test_full_pipeline(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            validation_report={"report_id": "v-1", "valid": False, "error_count": 1, "warning_count": 0},
            repair_report={"report_id": "r-1", "repairable_count": 1, "unrepairable_count": 0},
        )
        assert result["event_count"] == 3
        types = [e["event_type"] for e in result["history"]["events"]]
        assert "repair_recommended" in types


class TestCreateHistoryWithExecution:
    def test_with_execution(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            execution_result={"result_id": "e-1", "status": "succeeded"},
        )
        assert result["event_count"] == 2
        types = [e["event_type"] for e in result["history"]["events"]]
        assert "execution_completed" in types


class TestCreateHistoryWithRollback:
    def test_with_rollback(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            execution_result={"result_id": "e-1", "status": "succeeded"},
            rollback_result={"result_id": "rb-1", "status": "succeeded"},
        )
        assert result["event_count"] == 3
        types = [e["event_type"] for e in result["history"]["events"]]
        assert "rollback_completed" in types


class TestCreateHistoryNoAction:
    def test_no_inputs(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history()
        assert result["event_count"] == 1
        assert result["history"]["events"][0]["event_type"] == "no_action"


class TestEventOrdering:
    def test_deterministic_ordering(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        r1 = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            validation_report={"report_id": "v-1", "valid": True, "error_count": 0, "warning_count": 0},
            execution_result={"result_id": "e-1", "status": "succeeded"},
        )
        r2 = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            validation_report={"report_id": "v-1", "valid": True, "error_count": 0, "warning_count": 0},
            execution_result={"result_id": "e-1", "status": "succeeded"},
        )
        types1 = [e["event_type"] for e in r1["history"]["events"]]
        types2 = [e["event_type"] for e in r2["history"]["events"]]
        assert types1 == types2
        assert types1 == ["config_loaded", "config_validated", "execution_completed"]


class TestSourceReferences:
    def test_source_ids_preserved(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 2},
            validation_report={"report_id": "val-42", "valid": True, "error_count": 0, "warning_count": 0},
        )
        events = result["history"]["events"]
        assert events[0]["source_id"] == "cfg-1"
        assert events[1]["source_id"] == "val-42"


class TestEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 1},
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_history" / report_id
        assert (evidence_dir / "config_history_request.json").exists()
        assert (evidence_dir / "config_history_result.json").exists()
        assert (evidence_dir / "config_history_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_content(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 1},
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_history" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "succeeded"
        assert pf["event_count"] == 1


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 1},
        )
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        engine.create_history(config={"config_id": "c1", "entry_count": 1})
        engine.create_history(config={"config_id": "c2", "entry_count": 2})
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        result = engine.create_history(
            config={"config_id": "cfg-1", "entry_count": 1},
        )
        md = engine.export_report(result["report_id"])
        assert "Configuration Change History Report" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        hist_dir = tmp_path / "config_history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        link = hist_dir / "evil-link"
        link.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_history_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationChangeHistoryEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


class TestCommandRegistryIntegration:
    def test_config_history_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-history-create" in names
        assert "config-history-show" in names
        assert "config-history-export" in names


class TestSelectionMapping:
    def test_config_history_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_history.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_history.py"] == "tests/test_config_history.py"
