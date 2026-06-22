"""Tests for Configuration Diff Framework v1."""

import json

import pytest
from axiom_core.config_diff import (
    ConfigurationDiffEngine,
    ConfigurationDiffEntry,
    ConfigurationDiffReport,
    ConfigurationDiffRequest,
    ConfigurationDiffResult,
    ConfigurationDiffType,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationDiffType:
    def test_values(self):
        assert ConfigurationDiffType.ADDED.value == "added"
        assert ConfigurationDiffType.REMOVED.value == "removed"
        assert ConfigurationDiffType.CHANGED.value == "changed"
        assert ConfigurationDiffType.UNCHANGED.value == "unchanged"


class TestConfigurationDiffRequest:
    def test_defaults(self):
        req = ConfigurationDiffRequest()
        assert req.request_id
        assert req.created_at
        assert req.left_config_id == ""
        assert req.right_config_id == ""

    def test_to_dict(self):
        req = ConfigurationDiffRequest(left_config_id="L", right_config_id="R")
        d = req.to_dict()
        assert d["left_config_id"] == "L"
        assert d["right_config_id"] == "R"


class TestConfigurationDiffEntry:
    def test_to_dict(self):
        entry = ConfigurationDiffEntry(
            key="host",
            diff_type="added",
            left_value="",
            right_value="localhost",
            summary="Key 'host' added",
        )
        d = entry.to_dict()
        assert d["key"] == "host"
        assert d["diff_type"] == "added"
        assert d["right_value"] == "localhost"


class TestConfigurationDiffResult:
    def test_defaults(self):
        result = ConfigurationDiffResult()
        assert result.result_id
        assert result.entries == []
        assert result.added_count == 0

    def test_to_dict(self):
        result = ConfigurationDiffResult(
            request_id="req-1",
            added_count=2,
            removed_count=1,
            changed_count=1,
            unchanged_count=3,
        )
        d = result.to_dict()
        assert d["added_count"] == 2
        assert d["removed_count"] == 1


class TestConfigurationDiffReport:
    def test_defaults(self):
        report = ConfigurationDiffReport()
        assert report.report_id
        assert report.diff_summary == ""

    def test_to_dict(self):
        report = ConfigurationDiffReport(
            request_id="req-1",
            diff_summary="test summary",
        )
        d = report.to_dict()
        assert d["diff_summary"] == "test summary"


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestDiffAddedKeys:
    def test_added_detection(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": []}
        right = {"config_id": "R", "entries": [
            {"key": "host", "value": "localhost"},
            {"key": "port", "value": "8080"},
        ]}
        result = engine.diff(left_config=left, right_config=right)
        assert result["result"]["added_count"] == 2
        assert result["result"]["removed_count"] == 0
        assert result["result"]["changed_count"] == 0
        entries = result["result"]["entries"]
        assert all(e["diff_type"] == "added" for e in entries)


class TestDiffRemovedKeys:
    def test_removed_detection(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "host", "value": "localhost"},
            {"key": "port", "value": "8080"},
        ]}
        right = {"config_id": "R", "entries": []}
        result = engine.diff(left_config=left, right_config=right)
        assert result["result"]["removed_count"] == 2
        assert result["result"]["added_count"] == 0


class TestDiffChangedKeys:
    def test_changed_detection(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "host", "value": "localhost"},
            {"key": "port", "value": "8080"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "host", "value": "prod.example.com"},
            {"key": "port", "value": "443"},
        ]}
        result = engine.diff(left_config=left, right_config=right)
        assert result["result"]["changed_count"] == 2
        assert result["result"]["unchanged_count"] == 0
        entries = result["result"]["entries"]
        host_entry = next(e for e in entries if e["key"] == "host")
        assert host_entry["left_value"] == "localhost"
        assert host_entry["right_value"] == "prod.example.com"


class TestDiffUnchangedKeys:
    def test_unchanged_detection(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "host", "value": "localhost"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "host", "value": "localhost"},
        ]}
        result = engine.diff(left_config=left, right_config=right)
        assert result["result"]["unchanged_count"] == 1
        assert result["result"]["added_count"] == 0
        assert result["result"]["removed_count"] == 0
        assert result["result"]["changed_count"] == 0


class TestDiffMixed:
    def test_mixed_changes(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [
            {"key": "a", "value": "1"},
            {"key": "b", "value": "2"},
            {"key": "c", "value": "3"},
        ]}
        right = {"config_id": "R", "entries": [
            {"key": "a", "value": "1"},
            {"key": "b", "value": "99"},
            {"key": "d", "value": "4"},
        ]}
        result = engine.diff(left_config=left, right_config=right)
        assert result["result"]["unchanged_count"] == 1
        assert result["result"]["changed_count"] == 1
        assert result["result"]["removed_count"] == 1
        assert result["result"]["added_count"] == 1


class TestDiffDeterministicOrdering:
    def test_ordered_by_key(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
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
        result = engine.diff(left_config=left, right_config=right)
        keys = [e["key"] for e in result["result"]["entries"]]
        assert keys == sorted(keys)

    def test_repeated_runs_same_output(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        left = {"config_id": "L", "entries": [{"key": "x", "value": "1"}]}
        right = {"config_id": "R", "entries": [{"key": "x", "value": "2"}]}
        r1 = engine.diff(left_config=left, right_config=right)
        r2 = engine.diff(left_config=left, right_config=right)
        assert r1["result"]["entries"][0]["diff_type"] == r2["result"]["entries"][0]["diff_type"]


class TestDiffEmptyConfigs:
    def test_both_empty(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        result = engine.diff(left_config={}, right_config={})
        assert result["result"]["added_count"] == 0
        assert result["result"]["removed_count"] == 0
        assert result["result"]["changed_count"] == 0
        assert result["result"]["unchanged_count"] == 0


class TestDiffEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        result = engine.diff(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "a", "value": "2"}]},
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_diff" / report_id
        assert (evidence_dir / "config_diff_request.json").exists()
        assert (evidence_dir / "config_diff_result.json").exists()
        assert (evidence_dir / "config_diff_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_content(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        result = engine.diff(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": [{"key": "b", "value": "2"}]},
        )
        report_id = result["report_id"]
        pf = json.loads(
            (tmp_path / "config_diff" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "succeeded"
        assert pf["has_differences"] is True


class TestDiffPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        result = engine.diff(
            left_config={"config_id": "L", "entries": []},
            right_config={"config_id": "R", "entries": []},
        )
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        engine.diff(left_config={}, right_config={})
        engine.diff(left_config={}, right_config={})
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        result = engine.diff(
            left_config={"config_id": "L", "entries": [{"key": "a", "value": "1"}]},
            right_config={"config_id": "R", "entries": []},
        )
        md = engine.export_report(result["report_id"])
        assert "Configuration Diff Report" in md
        assert "REMOVED" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


class TestDiffSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        diff_dir = tmp_path / "config_diff"
        diff_dir.mkdir(parents=True, exist_ok=True)
        link = diff_dir / "evil-link"
        link.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_diff_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationDiffEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


class TestCommandRegistryIntegration:
    def test_config_diff_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-diff" in names
        assert "config-diff-show" in names
        assert "config-diff-export" in names


class TestSelectionMapping:
    def test_config_diff_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_diff.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_diff.py"] == "tests/test_config_diff.py"
