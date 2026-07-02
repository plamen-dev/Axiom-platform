"""Tests for ConfigurationValidator — Structured Configuration Validation v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.config_validation import (
    ConfigurationRule,
    ConfigurationRuleType,
    ConfigurationValidationReport,
    ConfigurationValidator,
    ConfigurationViolation,
    ViolationSeverity,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationRule:
    def test_defaults(self) -> None:
        rule = ConfigurationRule(key_pattern="host")
        assert rule.rule_id
        assert rule.key_pattern == "host"
        assert rule.rule_type == ConfigurationRuleType.REQUIRED_KEY
        assert rule.created_at

    def test_to_dict(self) -> None:
        rule = ConfigurationRule(
            key_pattern="env",
            rule_type=ConfigurationRuleType.ALLOWED_VALUES,
            expected_values=["dev", "prod"],
        )
        d = rule.to_dict()
        assert d["key_pattern"] == "env"
        assert d["rule_type"] == "allowed_values"
        assert d["expected_values"] == ["dev", "prod"]


class TestConfigurationViolation:
    def test_defaults(self) -> None:
        v = ConfigurationViolation(key="host", message="missing")
        assert v.violation_id
        assert v.severity == ViolationSeverity.ERROR

    def test_to_dict(self) -> None:
        v = ConfigurationViolation(
            key="port", message="bad value", severity=ViolationSeverity.WARNING,
        )
        d = v.to_dict()
        assert d["key"] == "port"
        assert d["severity"] == "warning"


class TestConfigurationValidationReport:
    def test_defaults(self) -> None:
        r = ConfigurationValidationReport()
        assert r.report_id
        assert r.valid is True
        assert r.violations == []
        assert r.created_at

    def test_to_dict(self) -> None:
        v = ConfigurationViolation(key="k", message="m")
        r = ConfigurationValidationReport(
            config_id="cfg-1",
            valid=False,
            violations=[v],
            error_count=1,
        )
        d = r.to_dict()
        assert d["config_id"] == "cfg-1"
        assert d["valid"] is False
        assert len(d["violations"]) == 1


# ---------------------------------------------------------------------------
# Validation engine tests
# ---------------------------------------------------------------------------


def _make_config(entries: dict[str, str]) -> dict:
    return {
        "config_id": "test-config",
        "entries": [{"key": k, "value": v} for k, v in entries.items()],
    }


class TestRequiredKey:
    def test_present(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"host": "localhost"})
        rules = [ConfigurationRule(key_pattern="host", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        assert report["valid"] is True
        assert report["error_count"] == 0

    def test_missing(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"port": "5432"})
        rules = [ConfigurationRule(key_pattern="host", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert report["error_count"] == 1
        assert "Required key missing" in report["violations"][0]["message"]


class TestAllowedValues:
    def test_valid_value(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"env": "prod"})
        rules = [
            ConfigurationRule(
                key_pattern="env",
                rule_type=ConfigurationRuleType.ALLOWED_VALUES,
                expected_values=["dev", "staging", "prod"],
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is True

    def test_invalid_value(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"env": "testing"})
        rules = [
            ConfigurationRule(
                key_pattern="env",
                rule_type=ConfigurationRuleType.ALLOWED_VALUES,
                expected_values=["dev", "staging", "prod"],
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert "not in allowed values" in report["violations"][0]["message"]


class TestNonEmpty:
    def test_non_empty_value(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"name": "Alice"})
        rules = [ConfigurationRule(key_pattern="name", rule_type=ConfigurationRuleType.NON_EMPTY)]
        report = validator.validate(config, rules)
        assert report["valid"] is True

    def test_empty_value(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"name": ""})
        rules = [ConfigurationRule(key_pattern="name", rule_type=ConfigurationRuleType.NON_EMPTY)]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert "must not be empty" in report["violations"][0]["message"]

    def test_missing_required(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"other": "val"})
        rules = [ConfigurationRule(key_pattern="name", rule_type=ConfigurationRuleType.NON_EMPTY, required=True)]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert "Required key missing" in report["violations"][0]["message"]


class TestRegexMatch:
    def test_matching(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"port": "5432"})
        rules = [
            ConfigurationRule(
                key_pattern="port",
                rule_type=ConfigurationRuleType.REGEX_MATCH,
                regex_pattern=r"\d+",
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is True

    def test_not_matching(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"port": "abc"})
        rules = [
            ConfigurationRule(
                key_pattern="port",
                rule_type=ConfigurationRuleType.REGEX_MATCH,
                regex_pattern=r"\d+",
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert "does not match pattern" in report["violations"][0]["message"]


class TestCustomRule:
    def test_passing(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"timeout": "30"})
        rules = [
            ConfigurationRule(
                key_pattern="timeout",
                rule_type=ConfigurationRuleType.CUSTOM,
                custom_validator=lambda k, v: None,
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is True

    def test_failing(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"timeout": "-1"})
        rules = [
            ConfigurationRule(
                key_pattern="timeout",
                rule_type=ConfigurationRuleType.CUSTOM,
                custom_validator=lambda k, v: "Timeout must be positive",
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert "must be positive" in report["violations"][0]["message"]


class TestMultipleRules:
    def test_all_pass(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"host": "db.local", "port": "5432", "env": "prod"})
        rules = [
            ConfigurationRule(key_pattern="host", rule_type=ConfigurationRuleType.REQUIRED_KEY),
            ConfigurationRule(key_pattern="port", rule_type=ConfigurationRuleType.REGEX_MATCH, regex_pattern=r"\d+"),
            ConfigurationRule(key_pattern="env", rule_type=ConfigurationRuleType.ALLOWED_VALUES, expected_values=["dev", "prod"]),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is True
        assert report["rules_checked"] == 3

    def test_mixed_failures(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"port": "abc"})
        rules = [
            ConfigurationRule(key_pattern="host", rule_type=ConfigurationRuleType.REQUIRED_KEY),
            ConfigurationRule(key_pattern="port", rule_type=ConfigurationRuleType.REGEX_MATCH, regex_pattern=r"\d+"),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert report["error_count"] == 2


class TestRegexMetacharacterSafety:
    def test_dot_in_key_not_wildcard(self, tmp_path: Path) -> None:
        """Ensure literal key 'db.host' does NOT match 'dbXhost'."""
        import re as re_mod

        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"dbXhost": "val"})
        rules = [
            ConfigurationRule(
                key_pattern=re_mod.escape("db.host"),
                rule_type=ConfigurationRuleType.REQUIRED_KEY,
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is False
        assert report["error_count"] == 1

    def test_escaped_key_exact_match(self, tmp_path: Path) -> None:
        """Ensure escaped 'db.host' matches literal 'db.host'."""
        import re as re_mod

        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"db.host": "localhost"})
        rules = [
            ConfigurationRule(
                key_pattern=re_mod.escape("db.host"),
                rule_type=ConfigurationRuleType.REQUIRED_KEY,
            ),
        ]
        report = validator.validate(config, rules)
        assert report["valid"] is True


class TestDeterministicOrdering:
    def test_violations_deterministic(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [
            ConfigurationRule(key_pattern="x", rule_type=ConfigurationRuleType.REQUIRED_KEY),
            ConfigurationRule(key_pattern="y", rule_type=ConfigurationRuleType.REQUIRED_KEY),
            ConfigurationRule(key_pattern="z", rule_type=ConfigurationRuleType.REQUIRED_KEY),
        ]
        for _ in range(10):
            report = validator.validate(config, rules)
            keys = [v["key"] for v in report["violations"]]
            assert keys == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_files_created(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"host": "localhost"})
        rules = [ConfigurationRule(key_pattern="host", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_validation" / report_id
        assert (evidence_dir / "config_validation_request.json").exists()
        assert (evidence_dir / "config_validation_result.json").exists()
        assert (evidence_dir / "config_validation_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_evidence_valid_json(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_validation" / report_id
        for fname in [
            "config_validation_request.json",
            "config_validation_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((evidence_dir / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_structure(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_validation" / report_id
        pf = json.loads((evidence_dir / "pass_fail.json").read_text(encoding="utf-8"))
        assert "passed" in pf
        assert "report_id" in pf
        assert "error_count" in pf
        assert "rules_checked" in pf

    def test_summary_markdown(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        report_id = report["report_id"]
        evidence_dir = tmp_path / "config_validation" / report_id
        md = (evidence_dir / "config_validation_summary.md").read_text(encoding="utf-8")
        assert "# Configuration Validation Report" in md
        assert "PASSED" in md


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_persist_and_load(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        loaded = validator.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]

    def test_unknown_id(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        assert validator.get_report("nonexistent-id") is None

    def test_list_reports_deterministic(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        r1 = validator.validate(config, rules)
        r2 = validator.validate(config, rules)
        reports = validator.list_reports()
        assert len(reports) == 2
        assert reports[0]["report_id"] == r1["report_id"]
        assert reports[1]["report_id"] == r2["report_id"]

    def test_export_report(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        config = _make_config({"a": "1"})
        rules = [ConfigurationRule(key_pattern="a", rule_type=ConfigurationRuleType.REQUIRED_KEY)]
        report = validator.validate(config, rules)
        md = validator.export_report(report["report_id"])
        assert "# Configuration Validation Report" in md

    def test_export_unknown_raises(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            validator.export_report("nonexistent-id")


# ---------------------------------------------------------------------------
# Safety tests
# ---------------------------------------------------------------------------


class TestSafety:
    def test_normal_path(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        path = validator._safe_validation_path("valid-id")
        assert path.is_relative_to(tmp_path)

    def test_symlink_blocked(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        validations_dir = tmp_path / "config_validation"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = validations_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            validator._safe_validation_path("evil-link")

    def test_empty_id_refused(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            validator.get_report("")

    def test_traversal_refused(self, tmp_path: Path) -> None:
        validator = ConfigurationValidator(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            validator.get_report("../../etc/passwd")


# ---------------------------------------------------------------------------
# Command registry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_config_validate_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-validate")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_config_validation_show_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-validation-show")
        assert cmd is not None

    def test_config_validation_export_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-validation-export")
        assert cmd is not None

    def test_config_validate_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("config-validate")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "config_validation_request.json" in locations
        assert "config_validation_result.json" in locations
        assert "config_validation_summary.md" in locations
        assert "pass_fail.json" in locations

    def test_show_export_use_ev_console(self) -> None:
        from axiom_core.runner.command_registry import get_command

        for name in ("config-validation-show", "config-validation-export"):
            cmd = get_command(name)
            assert cmd is not None
            locations = {eo.location for eo in cmd.evidence_outputs}
            assert "EV_CONSOLE" in locations


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/config_validation.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_config_validation.py"
