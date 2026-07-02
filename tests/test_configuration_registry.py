"""Tests for ConfigurationRegistry — Structured Configuration Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.configuration_registry import (
    ConfigurationEntry,
    ConfigurationFile,
    ConfigurationRegistry,
    ConfigurationValidationResult,
)

from tests.conftest import make_symlink_or_skip


class TestConfigurationEntry:
    def test_to_dict(self) -> None:
        entry = ConfigurationEntry(key="name", value="Alice")
        assert entry.to_dict() == {"key": "name", "value": "Alice"}

    def test_defaults(self) -> None:
        entry = ConfigurationEntry()
        assert entry.key == ""
        assert entry.value == ""


class TestConfigurationValidationResult:
    def test_defaults(self) -> None:
        vr = ConfigurationValidationResult()
        assert vr.valid is True
        assert vr.errors == []
        assert vr.warnings == []

    def test_to_dict(self) -> None:
        vr = ConfigurationValidationResult(
            valid=False,
            errors=["err1"],
            warnings=["warn1"],
        )
        d = vr.to_dict()
        assert d["valid"] is False
        assert d["errors"] == ["err1"]
        assert d["warnings"] == ["warn1"]


class TestConfigurationFile:
    def test_defaults(self) -> None:
        cf = ConfigurationFile()
        assert cf.config_id
        assert cf.created_at
        assert cf.entries == []
        assert cf.entry_count == 0

    def test_to_dict(self) -> None:
        entry = ConfigurationEntry(key="a", value="1")
        cf = ConfigurationFile(
            file_name="test.cfg",
            entries=[entry],
            entry_count=1,
        )
        d = cf.to_dict()
        assert d["file_name"] == "test.cfg"
        assert len(d["entries"]) == 1
        assert d["entry_count"] == 1


class TestLoadConfig:
    def test_normal_input(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("name=Alice\nage=30")
        assert result["entry_count"] == 2
        assert result["validation"]["valid"] is True
        keys = [e["key"] for e in result["entries"]]
        assert "name" in keys
        assert "age" in keys

    def test_empty_input(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("")
        assert result["entry_count"] == 0
        assert result["validation"]["warnings"]

    def test_whitespace_only(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("   \n  \n  ")
        assert result["entry_count"] == 0

    def test_comments_ignored(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("# comment\nfoo=bar\n# another")
        assert result["entry_count"] == 1
        assert result["entries"][0]["key"] == "foo"

    def test_malformed_line(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("good=ok\nbad line")
        assert result["validation"]["valid"] is False
        assert any("Malformed" in e for e in result["validation"]["errors"])

    def test_duplicate_key(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("x=1\nx=2")
        assert result["validation"]["valid"] is False
        assert any("Duplicate" in e for e in result["validation"]["errors"])

    def test_whitespace_trimmed(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("  key  =  value  ")
        assert result["entries"][0]["key"] == "key"
        assert result["entries"][0]["value"] == "value"

    def test_file_name_persisted(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("a=1", file_name="test.cfg")
        assert result["file_name"] == "test.cfg"


class TestPersistence:
    def test_persist_and_load(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("db_host=localhost\ndb_port=5432")
        config_id = result["config_id"]
        loaded = registry.get_config(config_id)
        assert loaded is not None
        assert loaded["config_id"] == config_id
        assert loaded["entry_count"] == 2

    def test_unknown_id(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.get_config("nonexistent-id")
        assert result is None


class TestListConfigs:
    def test_empty_list(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        assert registry.list_configs() == []

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        r1 = registry.load_config("a=1", file_name="first")
        r2 = registry.load_config("b=2", file_name="second")
        configs = registry.list_configs()
        assert len(configs) == 2
        assert configs[0]["config_id"] == r1["config_id"]
        assert configs[1]["config_id"] == r2["config_id"]

    def test_symlink_skipped(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        registry.load_config("a=1")
        configs_dir = tmp_path / "configurations"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = configs_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        configs = registry.list_configs()
        assert all(c.get("config_id") != "evil-link" for c in configs)


class TestExportConfig:
    def test_export_markdown(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("host=db.local\nport=5432", file_name="db.cfg")
        md = registry.export_config(result["config_id"])
        assert "# Configuration: db.cfg" in md
        assert "`host`" in md
        assert "`port`" in md

    def test_export_no_file_name_falls_back_to_id(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("a=1")
        md = registry.export_config(result["config_id"])
        assert f"# Configuration: {result['config_id']}" in md

    def test_export_unknown_raises(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            registry.export_config("nonexistent-id")


class TestEvidence:
    def test_evidence_files_created(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("a=1\nb=2")
        config_id = result["config_id"]
        evidence_dir = registry.write_evidence(config_id)
        ed = Path(evidence_dir)
        assert (ed / "configuration_request.json").exists()
        assert (ed / "configuration_result.json").exists()
        assert (ed / "configuration_summary.md").exists()
        assert (ed / "pass_fail.json").exists()

    def test_evidence_valid_json(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("x=1")
        config_id = result["config_id"]
        evidence_dir = Path(registry.write_evidence(config_id))
        for fname in [
            "configuration_request.json",
            "configuration_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((evidence_dir / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_structure(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        result = registry.load_config("a=1")
        config_id = result["config_id"]
        evidence_dir = Path(registry.write_evidence(config_id))
        pf = json.loads(
            (evidence_dir / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert "passed" in pf
        assert "config_id" in pf
        assert "entry_count" in pf
        assert "error_count" in pf

    def test_evidence_unknown_raises(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            registry.write_evidence("nonexistent-id")


class TestSafeConfigPath:
    def test_normal_path(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        path = registry._safe_config_path("valid-id")
        assert path.is_relative_to(tmp_path)

    def test_symlink_blocked(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        configs_dir = tmp_path / "configurations"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = configs_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            registry._safe_config_path("evil-link")


class TestIdValidation:
    def test_empty_id_refused(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_config("")

    def test_traversal_refused(self, tmp_path: Path) -> None:
        registry = ConfigurationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_config("../../etc/passwd")


class TestCommandRegistryIntegration:
    def test_config_load_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-load")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_config_show_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-show")
        assert cmd is not None

    def test_config_export_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-export")
        assert cmd is not None

    def test_config_load_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-load")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "configuration_request.json" in locations
        assert "configuration_result.json" in locations
        assert "configuration_summary.md" in locations
        assert "pass_fail.json" in locations

    def test_config_show_console_output(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-show")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "EV_CONSOLE" in locations

    def test_config_export_console_output(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-export")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "EV_CONSOLE" in locations


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/configuration_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_configuration_registry.py"
