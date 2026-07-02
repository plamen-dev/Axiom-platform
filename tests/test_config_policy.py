"""Tests for Configuration Policy Framework v1."""

import json

import pytest
from axiom_core.config_policy import (
    ConfigurationPolicy,
    ConfigurationPolicyEngine,
    ConfigurationPolicyReport,
    ConfigurationPolicyResult,
    ConfigurationPolicyRule,
    ConfigurationPolicyRuleType,
    ConfigurationPolicySeverity,
    ConfigurationPolicyViolation,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConfigurationPolicyRuleType:
    def test_values(self):
        assert ConfigurationPolicyRuleType.REQUIRED_KEY.value == "required_key"
        assert ConfigurationPolicyRuleType.FORBIDDEN_KEY.value == "forbidden_key"
        assert ConfigurationPolicyRuleType.ALLOWED_VALUES.value == "allowed_values"
        assert ConfigurationPolicyRuleType.DENIED_VALUES.value == "denied_values"
        assert ConfigurationPolicyRuleType.NON_EMPTY.value == "non_empty"
        assert ConfigurationPolicyRuleType.REGEX_MATCH.value == "regex_match"


class TestConfigurationPolicySeverity:
    def test_values(self):
        assert ConfigurationPolicySeverity.INFO.value == "info"
        assert ConfigurationPolicySeverity.WARNING.value == "warning"
        assert ConfigurationPolicySeverity.ERROR.value == "error"
        assert ConfigurationPolicySeverity.BLOCKER.value == "blocker"


class TestConfigurationPolicyRule:
    def test_defaults(self):
        rule = ConfigurationPolicyRule()
        assert rule.rule_id
        assert rule.key_pattern == ""
        assert rule.expected_values == []

    def test_to_dict(self):
        rule = ConfigurationPolicyRule(
            key_pattern="host",
            rule_type="required_key",
            severity="error",
            rationale="Host is mandatory",
        )
        d = rule.to_dict()
        assert d["key_pattern"] == "host"
        assert d["rule_type"] == "required_key"
        assert d["rationale"] == "Host is mandatory"


class TestConfigurationPolicy:
    def test_defaults(self):
        policy = ConfigurationPolicy()
        assert policy.policy_id
        assert policy.name == ""
        assert policy.rules == []

    def test_to_dict(self):
        policy = ConfigurationPolicy(name="test-policy", description="desc")
        d = policy.to_dict()
        assert d["name"] == "test-policy"
        assert d["description"] == "desc"


class TestConfigurationPolicyViolation:
    def test_to_dict(self):
        v = ConfigurationPolicyViolation(
            key="host", rule_id="r1", severity="error", message="msg"
        )
        d = v.to_dict()
        assert d["key"] == "host"
        assert d["severity"] == "error"


class TestConfigurationPolicyResult:
    def test_defaults(self):
        result = ConfigurationPolicyResult()
        assert result.result_id
        assert result.passed is True
        assert result.violations == []
        assert result.blocker_count == 0

    def test_to_dict(self):
        result = ConfigurationPolicyResult(
            policy_id="p1", config_id="c1", passed=False, error_count=2
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert d["error_count"] == 2


class TestConfigurationPolicyReport:
    def test_defaults(self):
        report = ConfigurationPolicyReport()
        assert report.report_id
        assert report.policy_summary == ""


# ---------------------------------------------------------------------------
# Engine: REQUIRED_KEY
# ---------------------------------------------------------------------------


class TestPolicyRequiredKey:
    def test_missing_key_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "port", "value": "8080"}]}
        policy = {
            "name": "require-host",
            "rules": [
                {"key_pattern": "host", "rule_type": "required_key", "severity": "error"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert result["result"]["error_count"] == 1
        assert "Required key" in result["result"]["violations"][0]["message"]

    def test_present_key_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "host", "value": "localhost"}]}
        policy = {
            "name": "require-host",
            "rules": [
                {"key_pattern": "host", "rule_type": "required_key", "severity": "error"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is True
        assert result["result"]["error_count"] == 0


# ---------------------------------------------------------------------------
# Engine: FORBIDDEN_KEY
# ---------------------------------------------------------------------------


class TestPolicyForbiddenKey:
    def test_forbidden_key_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "debug", "value": "true"}]}
        policy = {
            "name": "no-debug",
            "rules": [
                {"key_pattern": "debug", "rule_type": "forbidden_key", "severity": "blocker"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert result["result"]["blocker_count"] == 1
        assert "Forbidden key" in result["result"]["violations"][0]["message"]

    def test_absent_forbidden_key_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "host", "value": "x"}]}
        policy = {
            "name": "no-debug",
            "rules": [
                {"key_pattern": "debug", "rule_type": "forbidden_key", "severity": "blocker"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is True
        assert result["result"]["blocker_count"] == 0


# ---------------------------------------------------------------------------
# Engine: ALLOWED_VALUES
# ---------------------------------------------------------------------------


class TestPolicyAllowedValues:
    def test_disallowed_value_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "env", "value": "staging"}]}
        policy = {
            "name": "env-policy",
            "rules": [
                {
                    "key_pattern": "env",
                    "rule_type": "allowed_values",
                    "severity": "error",
                    "expected_values": ["production", "development"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert "not in allowed values" in result["result"]["violations"][0]["message"]

    def test_allowed_value_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "env", "value": "production"}]}
        policy = {
            "name": "env-policy",
            "rules": [
                {
                    "key_pattern": "env",
                    "rule_type": "allowed_values",
                    "severity": "error",
                    "expected_values": ["production", "development"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Engine: DENIED_VALUES
# ---------------------------------------------------------------------------


class TestPolicyDeniedValues:
    def test_denied_value_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "password", "value": "admin"}]}
        policy = {
            "name": "no-weak-passwords",
            "rules": [
                {
                    "key_pattern": "password",
                    "rule_type": "denied_values",
                    "severity": "blocker",
                    "expected_values": ["admin", "password", "123456"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert result["result"]["blocker_count"] == 1
        assert "denied value" in result["result"]["violations"][0]["message"]

    def test_non_denied_value_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "password", "value": "str0ng!"}]}
        policy = {
            "name": "no-weak-passwords",
            "rules": [
                {
                    "key_pattern": "password",
                    "rule_type": "denied_values",
                    "severity": "blocker",
                    "expected_values": ["admin", "password", "123456"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Engine: NON_EMPTY
# ---------------------------------------------------------------------------


class TestPolicyNonEmpty:
    def test_empty_value_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "host", "value": ""}]}
        policy = {
            "name": "non-empty",
            "rules": [
                {"key_pattern": "host", "rule_type": "non_empty", "severity": "warning"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["warning_count"] == 1
        assert "must not be empty" in result["result"]["violations"][0]["message"]

    def test_non_empty_value_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "host", "value": "localhost"}]}
        policy = {
            "name": "non-empty",
            "rules": [
                {"key_pattern": "host", "rule_type": "non_empty", "severity": "warning"}
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["warning_count"] == 0


# ---------------------------------------------------------------------------
# Engine: REGEX_MATCH
# ---------------------------------------------------------------------------


class TestPolicyRegexMatch:
    def test_regex_mismatch_violation(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "port", "value": "abc"}]}
        policy = {
            "name": "port-numeric",
            "rules": [
                {
                    "key_pattern": "port",
                    "rule_type": "regex_match",
                    "severity": "error",
                    "expected_values": ["^[0-9]+$"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert "does not match pattern" in result["result"]["violations"][0]["message"]

    def test_regex_match_passes(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "port", "value": "8080"}]}
        policy = {
            "name": "port-numeric",
            "rules": [
                {
                    "key_pattern": "port",
                    "rule_type": "regex_match",
                    "severity": "error",
                    "expected_values": ["^[0-9]+$"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is True

    def test_regex_unanchored_pattern_uses_fullmatch(self, tmp_path):
        """Regression: unanchored pattern like [0-9]+ must not pass '8080abc'."""
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [{"key": "port", "value": "8080abc"}]}
        policy = {
            "name": "port-numeric",
            "rules": [
                {
                    "key_pattern": "port",
                    "rule_type": "regex_match",
                    "severity": "error",
                    "expected_values": ["[0-9]+"],
                }
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["passed"] is False
        assert result["result"]["error_count"] == 1


# ---------------------------------------------------------------------------
# Severity counts
# ---------------------------------------------------------------------------


class TestPolicySeverityCounts:
    def test_mixed_severities(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [
            {"key": "debug", "value": "true"},
            {"key": "port", "value": "abc"},
            {"key": "host", "value": ""},
        ]}
        policy = {
            "name": "mixed",
            "rules": [
                {"key_pattern": "debug", "rule_type": "forbidden_key", "severity": "blocker"},
                {"key_pattern": "port", "rule_type": "regex_match", "severity": "error", "expected_values": ["^[0-9]+$"]},
                {"key_pattern": "host", "rule_type": "non_empty", "severity": "warning"},
                {"key_pattern": "version", "rule_type": "required_key", "severity": "info"},
            ],
        }
        result = engine.check(config=config, policy=policy)
        assert result["result"]["blocker_count"] == 1
        assert result["result"]["error_count"] == 1
        assert result["result"]["warning_count"] == 1
        assert result["result"]["info_count"] == 1
        assert result["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestPolicyDeterministicOrdering:
    def test_violations_sorted_by_key(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        config = {"config_id": "C", "entries": [
            {"key": "z_key", "value": ""},
            {"key": "a_key", "value": ""},
            {"key": "m_key", "value": ""},
        ]}
        policy = {
            "name": "non-empty-all",
            "rules": [
                {"key_pattern": "z_key", "rule_type": "non_empty", "severity": "error"},
                {"key_pattern": "a_key", "rule_type": "non_empty", "severity": "error"},
                {"key_pattern": "m_key", "rule_type": "non_empty", "severity": "error"},
            ],
        }
        result = engine.check(config=config, policy=policy)
        keys = [v["key"] for v in result["result"]["violations"]]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestPolicyEvidence:
    def test_evidence_files_written(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        result = engine.check(
            config={"config_id": "C", "entries": [{"key": "a", "value": "1"}]},
            policy={"name": "p", "rules": []},
        )
        report_id = result["report_id"]
        evidence_dir = tmp_path / "config_policy" / report_id
        assert (evidence_dir / "config_policy_request.json").exists()
        assert (evidence_dir / "config_policy_result.json").exists()
        assert (evidence_dir / "config_policy_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_passed(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        result = engine.check(config={}, policy={"name": "empty", "rules": []})
        pf = json.loads(
            (tmp_path / "config_policy" / result["report_id"] / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_failed(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        result = engine.check(
            config={"config_id": "C", "entries": []},
            policy={"name": "p", "rules": [
                {"key_pattern": "host", "rule_type": "required_key", "severity": "error"}
            ]},
        )
        pf = json.loads(
            (tmp_path / "config_policy" / result["report_id"] / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False
        assert pf["status"] == "failed"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPolicyPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        result = engine.check(config={}, policy={"name": "p", "rules": []})
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]

    def test_get_report_unknown(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None

    def test_list_reports(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        engine.check(config={}, policy={"name": "p1", "rules": []})
        engine.check(config={}, policy={"name": "p2", "rules": []})
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        result = engine.check(
            config={"config_id": "C", "entries": []},
            policy={"name": "p", "rules": [
                {"key_pattern": "host", "rule_type": "required_key", "severity": "error"}
            ]},
        )
        md = engine.export_report(result["report_id"])
        assert "Configuration Policy Report" in md
        assert "ERROR" in md

    def test_export_report_unknown(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestPolicySafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_symlink_traversal_rejected(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        policy_dir = tmp_path / "config_policy"
        policy_dir.mkdir(parents=True, exist_ok=True)
        link = policy_dir / "evil-link"
        make_symlink_or_skip(link, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_policy_path("evil-link")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationPolicyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_config_policy_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "config-policy-check" in names
        assert "config-policy-show" in names
        assert "config-policy-export" in names


class TestSelectionMapping:
    def test_config_policy_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert "src/axiom_core/config_policy.py" in _FILE_TO_TEST
        assert _FILE_TO_TEST["src/axiom_core/config_policy.py"] == "tests/test_config_policy.py"
