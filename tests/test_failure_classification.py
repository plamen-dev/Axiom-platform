"""Tests for Retry & Failure Classification Engine v1 (PR #29).

Tests prove every acceptance criterion:
- pass / denied / refused / blocked / unsupported / execution_failed /
  transport / evidence_missing / parse_error classified correctly
- classification output writes JSON + Markdown
- CLI works on capability-run and validation-run evidence bundles
- JSON output is valid
"""

import json
from pathlib import Path

import pytest
from axiom_cli.main import cli
from axiom_core.runner.failure_classification import (
    FailureCategory,
    FailureClassificationEngine,
    FailureSeverity,
    RetryEligibility,
    RetryPolicyEvaluator,
    write_classification,
)
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def engine():
    return FailureClassificationEngine()


# ---------------------------------------------------------------------------
# Bundle helper — creates a minimal evidence folder with pass_fail.json
# ---------------------------------------------------------------------------


def _write_bundle(
    base: Path,
    outcome: str,
    *,
    capability_name: str = "TestCapability",
    bundle_type: str = "capability_run",
    checks: list[dict] | None = None,
    reason: str = "",
    malformed: bool = False,
    missing_pf: bool = False,
) -> Path:
    """Create a minimal evidence bundle for classification tests."""
    bundle = base / "test_run_001"
    bundle.mkdir(parents=True, exist_ok=True)

    if not missing_pf:
        if malformed:
            (bundle / "pass_fail.json").write_text("NOT VALID JSON{{{", encoding="utf-8")
        else:
            pf: dict = {
                ("capability_name" if bundle_type == "capability_run"
                 else "validation_name"): capability_name,
                "outcome": outcome,
                "passed": outcome == "passed",
                "exit_code": {"passed": 0, "failed": 1, "denied": 2,
                              "refused": 3, "unsupported": 4,
                              "blocked": 5}.get(outcome, 1),
                "checks_passed": sum(1 for c in (checks or []) if c.get("passed")),
                "checks_total": len(checks or []),
                "checks": checks or [],
            }
            (bundle / "pass_fail.json").write_text(
                json.dumps(pf, indent=2), encoding="utf-8")

    # Write a matching result file (for bundle type detection + reason).
    result_file = ("capability_result.json" if bundle_type == "capability_run"
                   else "validation_result.json")
    result: dict = {
        ("capability_name" if bundle_type == "capability_run"
         else "validation_name"): capability_name,
        "outcome": outcome,
        "reason": reason,
    }
    (bundle / result_file).write_text(json.dumps(result, indent=2), encoding="utf-8")

    return bundle


# ===================================================================
# Engine classification tests (acceptance criteria)
# ===================================================================


class TestPassedClassification:
    def test_pass_outcome_classifies_as_passed(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "passed")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.PASSED
        assert s.severity is FailureSeverity.INFO
        assert s.retry_eligibility is RetryEligibility.NOT_NEEDED
        assert not s.retry_decision.retry_allowed

    def test_passed_retry_not_needed(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "passed")
        s = engine.classify(bundle)
        assert not s.retry_decision.retry_recommended
        assert s.retry_decision.max_retries == 0


class TestDeniedClassification:
    def test_denied_classifies_correctly(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "denied")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.DENIED
        assert s.severity is FailureSeverity.WARNING
        assert not s.retry_decision.retry_allowed

    def test_denied_retry_not_allowed(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "denied")
        s = engine.classify(bundle)
        assert s.retry_eligibility is RetryEligibility.INELIGIBLE


class TestRefusedClassification:
    def test_refused_classifies_correctly(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "refused")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.REFUSED
        assert s.severity is FailureSeverity.INFO
        assert not s.retry_decision.retry_allowed

    def test_refused_retry_not_allowed(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "refused")
        s = engine.classify(bundle)
        assert s.retry_eligibility is RetryEligibility.INELIGIBLE


class TestBlockedClassification:
    def test_blocked_classifies_as_blocked(self, engine, tmp_path):
        # The runner emits outcome="blocked" when command prerequisites are not
        # met (capability_runner.CapabilityOutcome.BLOCKED). It must classify as
        # FailureCategory.BLOCKED — not the unrelated PREREQUISITE_MISSING — so
        # the BLOCKED category is reachable and matches CapabilityStatus.BLOCKED.
        bundle = _write_bundle(tmp_path, "blocked")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.BLOCKED
        assert s.severity is FailureSeverity.ERROR

    def test_blocked_retry_requires_environment_change(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "blocked")
        s = engine.classify(bundle)
        assert s.retry_decision.retry_allowed
        assert s.retry_decision.retry_requires_environment_change
        assert s.retry_eligibility is RetryEligibility.CONDITIONAL


class TestPrerequisiteMissingClassification:
    def test_failed_with_prerequisite_reason_classifies_as_prerequisite_missing(
        self, engine, tmp_path
    ):
        # A "failed" run whose failure names a missing prerequisite must
        # sub-classify as PREREQUISITE_MISSING (keeps the category reachable and
        # distinct from BLOCKED), with retry gated on an environment change.
        checks = [
            {"name": "missing_prerequisite", "passed": False,
             "detail": "Declared prerequisite DOTNET_SDK was not met."},
        ]
        bundle = _write_bundle(tmp_path, "failed", checks=checks,
                               reason="Missing prerequisite: DOTNET_SDK.")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.PREREQUISITE_MISSING
        assert s.severity is FailureSeverity.ERROR
        assert s.retry_decision.retry_requires_environment_change
        assert s.retry_eligibility is RetryEligibility.CONDITIONAL


class TestUnsupportedClassification:
    def test_unsupported_classifies_correctly(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "unsupported")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.UNSUPPORTED
        assert s.severity is FailureSeverity.WARNING
        assert not s.retry_decision.retry_allowed


class TestExecutionFailedClassification:
    def test_failed_execution_classifies_as_execution_failed(self, engine, tmp_path):
        checks = [
            {"name": "execution_error", "passed": False,
             "detail": "RuntimeError during model query"},
        ]
        bundle = _write_bundle(tmp_path, "failed", checks=checks,
                               reason="Execution failed during model query.")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.EXECUTION_FAILED
        assert s.severity is FailureSeverity.ERROR
        assert s.retry_decision.retry_allowed
        assert s.retry_decision.retry_recommended


class TestTransportFailedClassification:
    def test_bridge_unavailable_classifies_as_transport(self, engine, tmp_path):
        checks = [
            {"name": "execution_error", "passed": False,
             "detail": "Bridge connection unavailable — Revit pipe not found"},
        ]
        bundle = _write_bundle(tmp_path, "failed", checks=checks,
                               reason="Bridge transport failure.")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.TRANSPORT_FAILED
        assert s.severity is FailureSeverity.ERROR
        assert s.retry_decision.retry_allowed
        assert s.retry_decision.retry_requires_human


class TestTimeoutClassification:
    def test_timeout_classifies_correctly(self, engine, tmp_path):
        checks = [
            {"name": "execution_error", "passed": False,
             "detail": "Operation timed out after 120s"},
        ]
        bundle = _write_bundle(tmp_path, "failed", checks=checks,
                               reason="Timeout exceeded.")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.TIMEOUT
        assert s.severity is FailureSeverity.ERROR
        assert s.retry_decision.retry_allowed
        assert s.retry_decision.retry_delay_seconds >= 60


class TestEvidenceMissingClassification:
    def test_missing_pass_fail_classifies_as_evidence_missing(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "passed", missing_pf=True)
        s = engine.classify(bundle)
        assert s.category is FailureCategory.EVIDENCE_MISSING
        assert s.severity is FailureSeverity.ERROR
        assert not s.retry_decision.retry_allowed
        assert s.retry_decision.retry_requires_human


class TestParseErrorClassification:
    def test_malformed_pass_fail_classifies_as_parse_error(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "passed", malformed=True)
        s = engine.classify(bundle)
        assert s.category is FailureCategory.PARSE_ERROR
        assert s.severity is FailureSeverity.ERROR
        assert not s.retry_decision.retry_allowed

    @pytest.mark.parametrize("payload", ["[]", "42", "true", '"hello"', "null"])
    def test_non_object_json_classifies_as_parse_error(
        self, engine, tmp_path, payload
    ):
        # Valid JSON that is not an object must not crash the engine; it is
        # treated as unparseable evidence.
        bundle = tmp_path / "nonobj"
        bundle.mkdir()
        (bundle / "pass_fail.json").write_text(payload, encoding="utf-8")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.PARSE_ERROR
        assert not s.retry_decision.retry_allowed


class TestNullFieldsOnFailedOutcome:
    """A ``failed`` bundle with JSON ``null`` reason/detail/name/checks must
    classify without crashing (regression for AttributeError on ``None.lower``).
    """

    def _write_failed_bundle(self, base: Path, *, result: dict, checks) -> Path:
        bundle = base / "null_run"
        bundle.mkdir(parents=True, exist_ok=True)
        pf = {"capability_name": "NullCap", "outcome": "failed", "checks": checks}
        (bundle / "pass_fail.json").write_text(json.dumps(pf), encoding="utf-8")
        (bundle / "capability_result.json").write_text(
            json.dumps(result), encoding="utf-8")
        return bundle

    def test_null_reason_does_not_crash(self, engine, tmp_path):
        bundle = self._write_failed_bundle(
            tmp_path,
            result={"capability_name": "NullCap", "outcome": "failed",
                    "reason": None},
            checks=[{"name": "exec", "passed": False, "detail": "boom"}],
        )
        s = engine.classify(bundle)
        assert s.category is FailureCategory.EXECUTION_FAILED
        assert s.error_detail == ""

    def test_null_check_detail_and_name_do_not_crash(self, engine, tmp_path):
        bundle = self._write_failed_bundle(
            tmp_path,
            result={"capability_name": "NullCap", "outcome": "failed",
                    "reason": "bridge unavailable"},
            checks=[{"name": None, "passed": False, "detail": None}],
        )
        s = engine.classify(bundle)
        # reason keyword still drives sub-classification despite null check fields
        assert s.category is FailureCategory.TRANSPORT_FAILED
        # rendered markdown must not leak literal "None" for null check fields
        _, md_path = write_classification(s)
        assert "| None |" not in md_path.read_text(encoding="utf-8")

    def test_null_checks_list_does_not_crash(self, engine, tmp_path):
        bundle = self._write_failed_bundle(
            tmp_path,
            result={"capability_name": "NullCap", "outcome": "failed",
                    "reason": None},
            checks=None,
        )
        s = engine.classify(bundle)
        assert s.category is FailureCategory.EXECUTION_FAILED


class TestValidationFailedClassification:
    def test_failed_validation_bundle(self, engine, tmp_path):
        checks = [
            {"name": "categories_discovered", "passed": False,
             "detail": "categories_discovered=0"},
        ]
        bundle = _write_bundle(tmp_path, "failed", bundle_type="validation_run",
                               checks=checks,
                               reason="Validation failed — 0 categories discovered.")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.VALIDATION_FAILED
        assert s.severity is FailureSeverity.ERROR
        assert s.retry_decision.retry_allowed
        assert s.retry_decision.retry_recommended


class TestUnknownOutcome:
    def test_unrecognized_outcome_classifies_as_unknown(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "banana")
        s = engine.classify(bundle)
        assert s.category is FailureCategory.UNKNOWN_ERROR
        assert s.severity is FailureSeverity.ERROR
        assert not s.retry_decision.retry_allowed


# ===================================================================
# Output writing tests
# ===================================================================


class TestClassificationOutput:
    def test_writes_json_and_markdown(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "passed")
        s = engine.classify(bundle)
        json_path, md_path = write_classification(s)
        assert json_path.exists()
        assert md_path.exists()
        assert json_path.name == "failure_classification.json"
        assert md_path.name == "failure_classification.md"

    def test_json_output_is_valid(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "failed", checks=[
            {"name": "some_check", "passed": False, "detail": "error"},
        ])
        s = engine.classify(bundle)
        json_path, _ = write_classification(s)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["category"] == "execution_failed"
        assert "retry_decision" in data
        assert isinstance(data["retry_decision"]["retry_allowed"], bool)

    def test_does_not_overwrite_pass_fail(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "refused")
        original_pf = (bundle / "pass_fail.json").read_text(encoding="utf-8")
        s = engine.classify(bundle)
        write_classification(s)
        # pass_fail.json must be identical after classification
        assert (bundle / "pass_fail.json").read_text(encoding="utf-8") == original_pf

    def test_markdown_includes_key_fields(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "blocked",
                               capability_name="InventoryModel")
        s = engine.classify(bundle)
        _, md_path = write_classification(s)
        md = md_path.read_text(encoding="utf-8")
        assert "InventoryModel" in md
        assert "blocked" in md
        assert "Retry Decision" in md


# ===================================================================
# CLI tests — both bundle types
# ===================================================================


class TestClassifyFailureCLI:
    def test_cli_capability_run_bundle(self, runner, tmp_path):
        bundle = _write_bundle(tmp_path, "passed")
        result = runner.invoke(cli, [
            "classify-failure", "--evidence-path", str(bundle),
        ])
        assert result.exit_code == 0, result.output
        assert (bundle / "failure_classification.json").exists()
        assert (bundle / "failure_classification.md").exists()

    def test_cli_validation_run_bundle(self, runner, tmp_path):
        bundle = _write_bundle(tmp_path, "failed", bundle_type="validation_run",
                               checks=[
                                   {"name": "categories_discovered", "passed": False,
                                    "detail": "0"},
                               ])
        result = runner.invoke(cli, [
            "classify-failure", "--evidence-path", str(bundle),
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(
            (bundle / "failure_classification.json").read_text(encoding="utf-8"))
        assert data["bundle_type"] == "validation_run"
        assert data["category"] == "validation_failed"

    def test_cli_json_output(self, runner, tmp_path):
        bundle = _write_bundle(tmp_path, "denied")
        result = runner.invoke(cli, [
            "classify-failure", "--evidence-path", str(bundle), "--json",
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["category"] == "denied"
        assert data["severity"] == "warning"
        assert isinstance(data["retry_decision"], dict)

    def test_cli_missing_evidence(self, runner, tmp_path):
        bundle = _write_bundle(tmp_path, "passed", missing_pf=True)
        result = runner.invoke(cli, [
            "classify-failure", "--evidence-path", str(bundle),
        ])
        assert result.exit_code == 0
        data = json.loads(
            (bundle / "failure_classification.json").read_text(encoding="utf-8"))
        assert data["category"] == "evidence_missing"


# ===================================================================
# RetryPolicyEvaluator direct tests
# ===================================================================


class TestRetryPolicyEvaluator:
    @pytest.mark.parametrize("category,allowed,recommended", [
        (FailureCategory.PASSED, False, False),
        (FailureCategory.DENIED, False, False),
        (FailureCategory.REFUSED, False, False),
        (FailureCategory.UNSUPPORTED, False, False),
        (FailureCategory.EXECUTION_FAILED, True, True),
        (FailureCategory.VALIDATION_FAILED, True, True),
        (FailureCategory.TRANSPORT_FAILED, True, True),
        (FailureCategory.TIMEOUT, True, False),
        (FailureCategory.PARSE_ERROR, False, False),
        (FailureCategory.EVIDENCE_MISSING, False, False),
        (FailureCategory.POLICY_VIOLATION, False, False),
        (FailureCategory.UNKNOWN_ERROR, False, False),
        (FailureCategory.BLOCKED, True, False),
        (FailureCategory.PREREQUISITE_MISSING, True, False),
    ])
    def test_retry_policy_decisions(self, category, allowed, recommended):
        decision = RetryPolicyEvaluator.evaluate(category, FailureSeverity.ERROR)
        assert decision.retry_allowed is allowed
        assert decision.retry_recommended is recommended


# ===================================================================
# FailureEvidenceSummary serialization
# ===================================================================


class TestFailureEvidenceSummary:
    def test_to_dict_round_trip(self, engine, tmp_path):
        bundle = _write_bundle(tmp_path, "refused",
                               capability_name="SetParameterValue")
        s = engine.classify(bundle)
        d = s.to_dict()
        assert d["capability_name"] == "SetParameterValue"
        assert d["category"] == "refused"
        assert d["severity"] == "info"
        assert d["retry_eligibility"] == "ineligible"
        assert isinstance(d["retry_decision"], dict)
        assert d["retry_decision"]["retry_allowed"] is False
