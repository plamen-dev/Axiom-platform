"""Tests for Configuration Merge Framework v1."""

import json

import pytest
from axiom_core.config_merge import (
    ConfigurationMergeEngine,
    ConfigurationMergeEntry,
    ConfigurationMergeReport,
    ConfigurationMergeRequest,
    ConfigurationMergeResult,
    ConfigurationMergeStatus,
    ConfigurationMergeStrategy,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationMergeStrategy:
    def test_values(self):
        assert ConfigurationMergeStrategy.LEFT_WINS.value == "left_wins"
        assert ConfigurationMergeStrategy.RIGHT_WINS.value == "right_wins"
        assert ConfigurationMergeStrategy.KEEP_IDENTICAL_ONLY.value == "keep_identical_only"
        assert ConfigurationMergeStrategy.FAIL_ON_CONFLICT.value == "fail_on_conflict"


class TestConfigurationMergeStatus:
    def test_values(self):
        assert ConfigurationMergeStatus.SUCCEEDED.value == "succeeded"
        assert ConfigurationMergeStatus.FAILED.value == "failed"
        assert ConfigurationMergeStatus.PARTIAL_SUCCESS.value == "partial_success"


class TestConfigurationMergeRequest:
    def test_defaults(self):
        req = ConfigurationMergeRequest()
        assert req.request_id
        assert req.created_at
        assert req.left_config_id == ""
        assert req.right_config_id == ""
        assert req.merge_strategy == ""

    def test_to_dict(self):
        req = ConfigurationMergeRequest(
            left_config_id="L", right_config_id="R", merge_strategy="left_wins"
        )
        d = req.to_dict()
        assert d["left_config_id"] == "L"
        assert d["right_config_id"] == "R"
        assert d["merge_strategy"] == "left_wins"


class TestConfigurationMergeEntry:
    def test_to_dict(self):
        entry = ConfigurationMergeEntry(
            key="host",
            left_value="localhost",
            right_value="prod",
            merged_value="localhost",
            conflict_detected=True,
        )
        d = entry.to_dict()
        assert d["key"] == "host"
        assert d["merged_value"] == "localhost"
        assert d["conflict_detected"] is True


class TestConfigurationMergeResult:
    def test_defaults(self):
        result = ConfigurationMergeResult()
        assert result.result_id
        assert result.merged_entries == []
        assert result.conflict_count == 0
        assert result.merged_count == 0

    def test_to_dict(self):
        result = ConfigurationMergeResult(
            request_id="req-1",
            conflict_count=2,
            merged_count=5,
            status="succeeded",
        )
        d = result.to_dict()
        assert d["conflict_count"] == 2
        assert d["merged_count"] == 5


class TestConfigurationMergeReport:
    def test_defaults(self):
        report = ConfigurationMergeReport()
        assert report.report_id
        assert report.merge_summary == ""

    def test_to_dict(self):
        report = ConfigurationMergeReport(
            request_id="req-1",
            merge_summary="test summary",
        )
        d = report.to_dict()
        assert d["merge_summary"] == "test summary"


# ---------------------------------------------------------------------------
# Engine: LEFT_WINS strategy
# ---------------------------------------------------------------------------


class TestMergeLeftWins:
    def test_conflict_uses_left(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "host", "value": "left-host"},
            {"key": "port", "value": "8080"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "host", "value": "right-host"},
            {"key": "port", "value": "443"},
        ]}
        result = engine.merge(left_config=left, right_config=right, strategy="left_wins")
        assert result["result"]["conflict_count"] == 2
        assert result["result"]["status"] == "succeeded"
        entries = result["result"]["merged_entries"]
        host = next(e for e in entries if e["key"] == "host")
        assert host["merged_value"] == "left-host"
        assert host["conflict_detected"] is True

    def test_no_conflict_identical(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "a", "value": "1"}]}
        right = {"config_id": "R", "entries": [{"key": "a", "value": "1"}]}
        result = engine.merge(left_config=left, right_config=right, strategy="left_wins")
        assert result["result"]["conflict_count"] == 0
        entries = result["result"]["merged_entries"]
        assert entries[0]["merged_value"] == "1"
        assert entries[0]["conflict_detected"] is False


# ---------------------------------------------------------------------------
# Engine: RIGHT_WINS strategy
# ---------------------------------------------------------------------------


class TestMergeRightWins:
    def test_conflict_uses_right(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "host", "value": "left-host"}]}
        right = {"config_id": "R", "entries": [{"key": "host", "value": "right-host"}]}
        result = engine.merge(left_config=left, right_config=right, strategy="right_wins")
        entries = result["result"]["merged_entries"]
        host = next(e for e in entries if e["key"] == "host")
        assert host["merged_value"] == "right-host"
        assert host["conflict_detected"] is True

    def test_unique_keys_preserved(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "a", "value": "1"}]}
        right = {"config_id": "R", "entries": [{"key": "b", "value": "2"}]}
        result = engine.merge(left_config=left, right_config=right, strategy="right_wins")
        assert result["result"]["merged_count"] == 2
        assert result["result"]["conflict_count"] == 0


# ---------------------------------------------------------------------------
# Engine: KEEP_IDENTICAL_ONLY strategy
# ---------------------------------------------------------------------------


class TestMergeKeepIdenticalOnly:
    def test_keeps_identical_drops_conflict(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "a", "value": "1"},
            {"key": "b", "value": "2"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "a", "value": "1"},
            {"key": "b", "value": "99"},
        ]}
        result = engine.merge(
            left_config=left, right_config=right, strategy="keep_identical_only"
        )
        assert result["result"]["conflict_count"] == 1
        assert result["result"]["status"] == "partial_success"
        entries = result["result"]["merged_entries"]
        a_entry = next(e for e in entries if e["key"] == "a")
        assert a_entry["merged_value"] == "1"
        assert a_entry["conflict_detected"] is False
        b_entry = next(e for e in entries if e["key"] == "b")
        assert b_entry["merged_value"] == ""
        assert b_entry["conflict_detected"] is True

    def test_unique_left_key_is_conflict(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "only_left", "value": "x"}]}
        right = {"config_id": "R", "entries": []}
        result = engine.merge(
            left_config=left, right_config=right, strategy="keep_identical_only"
        )
        assert result["result"]["conflict_count"] == 1
        entries = result["result"]["merged_entries"]
        assert entries[0]["conflict_detected"] is True
        assert entries[0]["merged_value"] == ""


# ---------------------------------------------------------------------------
# Engine: FAIL_ON_CONFLICT strategy
# ---------------------------------------------------------------------------


class TestMergeFailOnConflict:
    def test_fails_on_conflict(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "host", "value": "a"}]}
        right = {"config_id": "R", "entries": [{"key": "host", "value": "b"}]}
        result = engine.merge(
            left_config=left, right_config=right, strategy="fail_on_conflict"
        )
        assert result["result"]["status"] == "failed"
        assert result["result"]["conflict_count"] == 1

    def test_succeeds_without_conflict(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "a", "value": "1"}]}
        right = {"config_id": "R", "entries": [{"key": "a", "value": "1"}]}
        result = engine.merge(
            left_config=left, right_config=right, strategy="fail_on_conflict"
        )
        assert result["result"]["status"] == "succeeded"
        assert result["result"]["conflict_count"] == 0


# ---------------------------------------------------------------------------
# Engine: Deterministic ordering
# ---------------------------------------------------------------------------


class TestMergeDeterministicOrdering:
    def test_ordered_by_key(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "z", "value": "1"},
            {"key": "a", "value": "2"},
            {"key": "m", "value": "3"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "z", "value": "1"},
            {"key": "a", "value": "2"},
            {"key": "m", "value": "3"},
        ]}
        result = engine.merge(left_config=left, right_config=right, strategy="left_wins")
        keys = [e["key"] for e in result["result"]["merged_entries"]]
        assert keys == sorted(keys)

    def test_repeated_runs_same_output(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "x", "value": "1"}]}
        right = {"config_id": "R", "entries": [{"key": "x", "value": "2"}]}
        r1 = engine.merge(left_config=left, right_config=right, strategy="left_wins")
        r2 = engine.merge(left_config=left, right_config=right, strategy="left_wins")
        assert r1["result"]["merged_entries"][0]["merged_value"] == r2["result"]["merged_entries"][0]["merged_value"]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestMergeEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        result = engine.merge(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "a", "value": "2"}]},
            strategy="left_wins",
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_merge" / report_id
        assert (evidence_dir / "config_merge_request.json").exists()
        assert (evidence_dir / "config_merge_result.json").exists()
        assert (evidence_dir / "config_merge_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_succeeded(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        result = engine.merge(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "a", "value": "1"}]},
            strategy="left_wins",
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_merge" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "succeeded"

    def test_pass_fail_failed(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        result = engine.merge(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "a", "value": "2"}]},
            strategy="fail_on_conflict",
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_merge" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False
        assert pf["status"] == "failed"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestMergePersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        result = engine.merge(left_config={}, right_config={}, strategy="left_wins")
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        engine.merge(left_config={}, right_config={}, strategy="left_wins")
        engine.merge(left_config={}, right_config={}, strategy="right_wins")
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        result = engine.merge(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "a", "value": "2"}]},
            strategy="left_wins",
        )
        md = engine.export_report(result["report_id"])
        assert "Configuration Merge Report" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestMergeSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        merge_dir = tmp_path / "config_merge"
        merge_dir.mkdir(parents=True, exist_ok=True)
        link = merge_dir / "evil-link"
        link.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_merge_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationMergeEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_config_merge_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-merge" in names
        assert "config-merge-show" in names
        assert "config-merge-export" in names


class TestSelectionMapping:
    def test_config_merge_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_merge.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_merge.py"] == "tests/test_config_merge.py"
