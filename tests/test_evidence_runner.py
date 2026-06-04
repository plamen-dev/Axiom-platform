"""Tests for the Validation Evidence Runner (PR #25).

Covers the read-only evidence runner that connects the Runner Command Registry
(PR #22) and the Capability Validation Registry (PR #24): supported-validation
execution, unknown-denial, mutation/high-risk refusal, durable bundle
production, machine-readable pass/fail, and the ``axiom evidence-run`` CLI.

Read-only only — nothing here mutates a model, schedules, promotes, or learns.
"""

import json
from pathlib import Path

from axiom_cli.main import cli
from axiom_core.runner import ExecutionContext
from axiom_core.validation import (
    EvidenceOutcome,
    EvidenceRunner,
    ValidationRunResult,
)
from axiom_core.validation.evidence_runner import EXIT_CODES, SUPPORTED_VALIDATIONS
from click.testing import CliRunner

BUNDLE_FILES = {
    "validation_request.json",
    "validation_result.json",
    "validation_summary.md",
    "pass_fail.json",
}


def _runner(tmp_path) -> EvidenceRunner:
    return EvidenceRunner(output_base=tmp_path)


def _assert_bundle_complete(result: ValidationRunResult):
    bundle = Path(result.bundle_dir)
    assert bundle.is_dir(), "bundle directory must exist"
    for name in BUNDLE_FILES:
        assert (bundle / name).is_file(), f"missing bundle file: {name}"
    # command_outputs/ is always created (may be empty for denied/refused).
    assert (bundle / "command_outputs").is_dir()
    # pass_fail.json is machine-readable and consistent with the result.
    pf = json.loads((bundle / "pass_fail.json").read_text())
    assert pf["validation_name"] == result.validation_name
    assert pf["outcome"] == result.outcome.value
    assert pf["passed"] is result.passed
    assert pf["exit_code"] == result.exit_code
    assert pf["checks_total"] == len(result.checks)


# ---------------------------------------------------------------------------
# Supported validations — happy path
# ---------------------------------------------------------------------------


def test_supported_validations_listed():
    assert EvidenceRunner.supported_validations() == [
        "CommandRegistry",
        "DiscoveryHarness",
        "ValidationRegistry",
    ]


def test_command_registry_validation_passes(tmp_path):
    result = _runner(tmp_path).run("CommandRegistry")
    assert result.outcome is EvidenceOutcome.PASSED
    assert result.passed is True
    assert result.exit_code == 0
    assert result.command_name == "runner-commands"
    assert result.checks and all(c.passed for c in result.checks)
    _assert_bundle_complete(result)
    # The catalog snapshot is captured as command output.
    catalog = json.loads(
        (Path(result.bundle_dir) / "command_outputs" / "runner-commands.json").read_text()
    )
    assert len(catalog) > 0


def test_validation_registry_validation_passes(tmp_path):
    result = _runner(tmp_path).run("ValidationRegistry")
    assert result.outcome is EvidenceOutcome.PASSED
    assert result.command_name == "validation-registry"
    assert {c.name for c in result.checks} >= {
        "catalog_non_empty",
        "registry_structurally_valid",
        "unknown_denied_by_default",
    }
    _assert_bundle_complete(result)


def test_discovery_harness_validation_passes_in_simulate(tmp_path):
    # No --inventory-export-path → built-in deterministic export → complete=YES.
    result = _runner(tmp_path).run("DiscoveryHarness")
    assert result.outcome is EvidenceOutcome.PASSED
    assert result.capability_name == "DiscoveryHarness"
    names = {c.name for c in result.checks}
    assert {"categories_discovered", "parameters_discovered",
            "candidates_generated", "discovery_complete"} <= names
    _assert_bundle_complete(result)
    metrics = json.loads(
        (Path(result.bundle_dir) / "command_outputs" / "discovery_metrics.json").read_text()
    )
    assert metrics["discovery_complete"] is True
    assert metrics["metrics"]["parameters_discovered"] > 0


# ---------------------------------------------------------------------------
# Denial / refusal / blocking — bundle still produced every time
# ---------------------------------------------------------------------------


def test_unknown_validation_denied_by_default(tmp_path):
    result = _runner(tmp_path).run("totally-made-up")
    assert result.outcome is EvidenceOutcome.DENIED
    assert result.exit_code == 2
    assert result.checks == []
    _assert_bundle_complete(result)


def test_mutation_capability_refused(tmp_path):
    # SetParameterValue is a known mutation capability → refused, not executed.
    result = _runner(tmp_path).run("SetParameterValue")
    assert result.outcome is EvidenceOutcome.REFUSED
    assert result.exit_code == 3
    assert "mutation" in result.reason.lower()
    _assert_bundle_complete(result)


def test_known_but_unsupported_capability(tmp_path):
    # BridgeExecute is known + non-mutation but has no read-only executor here.
    result = _runner(tmp_path).run("BridgeExecute")
    assert result.outcome is EvidenceOutcome.UNSUPPORTED
    assert result.exit_code == 4
    _assert_bundle_complete(result)


def test_blocked_when_prerequisites_unmet(tmp_path):
    # An ExecutionContext with no Poetry env fails discovery-run prerequisites.
    ctx = ExecutionContext(poetry_env=False)
    result = _runner(tmp_path).run("CommandRegistry", context=ctx)
    assert result.outcome is EvidenceOutcome.BLOCKED
    assert result.exit_code == 5
    assert "poetry_env" in result.reason
    _assert_bundle_complete(result)


def test_bundle_produced_for_every_outcome(tmp_path):
    runner = _runner(tmp_path)
    for name in ["CommandRegistry", "ValidationRegistry", "DiscoveryHarness",
                 "SetParameterValue", "BridgeExecute", "nope-not-real"]:
        result = runner.run(name)
        _assert_bundle_complete(result)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def test_exit_codes_cover_all_outcomes():
    assert set(EXIT_CODES) == set(EvidenceOutcome)


def test_supported_validations_reference_real_commands():
    from axiom_core.runner import get_command

    for spec in SUPPORTED_VALIDATIONS.values():
        cmd = get_command(spec.command_name)
        assert cmd is not None, f"{spec.command_name} not in command registry"
        # Supported validations must drive read-only / non-high-risk commands.
        assert not cmd.is_mutation
        assert cmd.safety_level.value != "high_risk"


def test_result_to_dict_is_json_serializable(tmp_path):
    result = _runner(tmp_path).run("CommandRegistry")
    blob = json.dumps(result.to_dict())
    restored = json.loads(blob)
    assert restored["validation_name"] == "CommandRegistry"
    assert restored["outcome"] == "passed"
    assert restored["checks_total"] == len(result.checks)


# ---------------------------------------------------------------------------
# CLI — axiom evidence-run
# ---------------------------------------------------------------------------


def test_cli_evidence_run_passes(tmp_path):
    out = tmp_path / "evidence"
    res = CliRunner().invoke(
        cli, ["evidence-run", "--validation", "CommandRegistry",
              "--output-dir", str(out)])
    assert res.exit_code == 0, res.output
    assert "PASSED" in res.output
    assert "Evidence bundle:" in res.output


def test_cli_evidence_run_unknown_denied(tmp_path):
    out = tmp_path / "evidence"
    res = CliRunner().invoke(
        cli, ["evidence-run", "--validation", "made-up",
              "--output-dir", str(out)])
    assert res.exit_code == 2, res.output
    assert "DENIED" in res.output


def test_cli_evidence_run_mutation_refused(tmp_path):
    out = tmp_path / "evidence"
    res = CliRunner().invoke(
        cli, ["evidence-run", "--validation", "SetParameterValue",
              "--output-dir", str(out)])
    assert res.exit_code == 3, res.output
    assert "REFUSED" in res.output


def test_cli_evidence_run_discovery_simulate(tmp_path):
    out = tmp_path / "evidence"
    res = CliRunner().invoke(
        cli, ["evidence-run", "--validation", "DiscoveryHarness",
              "--output-dir", str(out)])
    assert res.exit_code == 0, res.output
    assert "PASSED" in res.output
