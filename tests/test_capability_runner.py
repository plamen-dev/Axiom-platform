"""Tests for the Capability Execution Runner (PR #26).

Covers the governed capability execution runner that connects the Runner
Command Registry (PR #22), the Capability Validation Registry (PR #24), and the
Automation Bridge (PR #19): supported-capability execution, unknown-denial,
mutation/high-risk refusal, unsafe-scan refusal, prerequisite blocking,
execution failure, durable bundle production, machine-readable pass/fail, and
the ``axiom capability-run`` CLI.

Safe/read-only only — nothing here mutates a model, schedules, retries,
promotes, or learns.
"""

import json
from pathlib import Path
from uuid import uuid4

from axiom_cli.main import cli
from axiom_core.runner import ExecutionContext
from axiom_core.runner.capability_runner import (
    EXIT_CODES,
    SUPPORTED_CAPABILITIES,
    CapabilityOutcome,
    CapabilityRunner,
    CapabilityRunResult,
    inventory_scan_refusal,
)
from axiom_core.schemas import StepStatus, ToolResult
from click.testing import CliRunner

BUNDLE_FILES = {
    "capability_request.json",
    "capability_result.json",
    "capability_summary.md",
    "pass_fail.json",
}


def _runner(tmp_path) -> CapabilityRunner:
    return CapabilityRunner(output_base=tmp_path)


def _assert_bundle_complete(result: CapabilityRunResult):
    bundle = Path(result.bundle_dir)
    assert bundle.is_dir(), "bundle directory must exist"
    for name in BUNDLE_FILES:
        assert (bundle / name).is_file(), f"missing bundle file: {name}"
    # command_outputs/ is always created (may be empty for denied/refused/blocked).
    assert (bundle / "command_outputs").is_dir()
    # pass_fail.json is machine-readable and consistent with the result.
    pf = json.loads((bundle / "pass_fail.json").read_text())
    assert pf["capability_name"] == result.capability_name
    assert pf["outcome"] == result.outcome.value
    assert pf["passed"] is result.passed
    assert pf["exit_code"] == result.exit_code
    assert pf["checks_total"] == len(result.checks)


class _FakePipe:
    """Injectable pipe client returning a fixed ToolResult (no Revit needed)."""

    def __init__(self, status: StepStatus, *, available: bool = True):
        self._status = status
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def execute_tool(self, *, tool_name, args, simulate, step_id=None,
                     transaction_name=None):
        return ToolResult(
            step_id=step_id or uuid4(),
            status=self._status,
            errors=["forced failure"] if self._status == StepStatus.FAILED else [],
            output_data={
                "source_model": "Fake Model",
                "element_count": 3,
                "type_count": 1,
                "parameter_count": 9,
            },
        )


# ---------------------------------------------------------------------------
# Catalog / supported set
# ---------------------------------------------------------------------------


def test_supported_capabilities_listed():
    assert CapabilityRunner.supported_capabilities() == ["InventoryModel"]


def test_exit_codes_are_distinct_and_complete():
    assert set(EXIT_CODES) == set(CapabilityOutcome)
    assert len(set(EXIT_CODES.values())) == len(CapabilityOutcome)
    assert EXIT_CODES[CapabilityOutcome.PASSED] == 0


def test_inventory_capability_maps_to_bridge_execute():
    spec = SUPPORTED_CAPABILITIES["InventoryModel"]
    assert spec.command_name == "bridge-execute"
    assert spec.validation_capability == "InventoryModel"


# ---------------------------------------------------------------------------
# Happy path — passed
# ---------------------------------------------------------------------------


def test_inventory_model_simulate_passes(tmp_path):
    result = _runner(tmp_path).run("InventoryModel", simulate=True)
    assert result.outcome is CapabilityOutcome.PASSED
    assert result.exit_code == 0
    assert result.passed is True
    assert result.command_name == "bridge-execute"
    assert result.validation_capability == "InventoryModel"
    assert result.checks and all(c.passed for c in result.checks)
    _assert_bundle_complete(result)


def test_passed_bundle_records_validation_contract(tmp_path):
    result = _runner(tmp_path).run("InventoryModel", simulate=True)
    payload = json.loads((Path(result.bundle_dir) / "capability_result.json").read_text())
    contract = payload["validation_contract"]
    assert contract["validation_procedure_id"] == "inventory_model.export_and_verify"
    assert "artifacts_exist" in contract["pass_conditions"]


def test_validation_contract_evidence_is_structured(tmp_path):
    """Evidence items must serialize as structured dicts, not opaque repr strings."""
    result = _runner(tmp_path).run("InventoryModel", simulate=True)
    payload = json.loads((Path(result.bundle_dir) / "capability_result.json").read_text())
    contract = payload["validation_contract"]
    artifacts = contract["required_artifacts"]
    assert artifacts and all(isinstance(it, dict) for it in artifacts)
    assert all({"kind", "name", "required"} <= set(it) for it in artifacts)
    assert {"elements.jsonl", "summary.md"} <= {it["name"] for it in artifacts}
    checkpoints = contract["required_checkpoints"]
    assert checkpoints and all(isinstance(it, dict) for it in checkpoints)


def test_passed_bundle_has_bridge_command_output(tmp_path):
    result = _runner(tmp_path).run("InventoryModel", simulate=True)
    bridge_result = Path(result.bundle_dir) / "command_outputs" / "bridge_result.json"
    assert bridge_result.is_file()
    data = json.loads(bridge_result.read_text())
    assert data["classification"] == "pass"
    assert data["summary"]["element_count"] > 0


def test_bounded_scan_with_summary_off_is_allowed(tmp_path):
    result = _runner(tmp_path).run(
        "InventoryModel", args={"SummaryOnly": False, "Category": "Walls"},
        simulate=True,
    )
    assert result.outcome is CapabilityOutcome.PASSED
    assert result.args == {"SummaryOnly": False, "Category": "Walls"}


# ---------------------------------------------------------------------------
# Unknown — denied by default
# ---------------------------------------------------------------------------


def test_unknown_capability_denied(tmp_path):
    result = _runner(tmp_path).run("DefinitelyNotACapability", simulate=True)
    assert result.outcome is CapabilityOutcome.DENIED
    assert result.exit_code == 2
    assert result.checks == []
    _assert_bundle_complete(result)


# ---------------------------------------------------------------------------
# Mutation / high-risk — refused
# ---------------------------------------------------------------------------


def test_set_parameter_value_refused(tmp_path):
    result = _runner(tmp_path).run("SetParameterValue", simulate=True)
    assert result.outcome is CapabilityOutcome.REFUSED
    assert result.exit_code == 3
    assert "mutation" in result.reason.lower()
    _assert_bundle_complete(result)


def test_known_nonmutation_without_executor_is_unsupported(tmp_path):
    # BridgeExecute is a known (non-mutation) validation-registry capability but
    # the execution runner has no safe executor wired for it yet.
    result = _runner(tmp_path).run("BridgeExecute", simulate=True)
    assert result.outcome is CapabilityOutcome.UNSUPPORTED
    assert result.exit_code == 4
    _assert_bundle_complete(result)


# ---------------------------------------------------------------------------
# Unsafe InventoryModel scan shapes — refused
# ---------------------------------------------------------------------------


def test_unbounded_full_param_scan_refused(tmp_path):
    result = _runner(tmp_path).run(
        "InventoryModel", args={"SummaryOnly": False}, simulate=True,
    )
    assert result.outcome is CapabilityOutcome.REFUSED
    assert result.exit_code == 3
    assert "bounded" in result.reason.lower()
    _assert_bundle_complete(result)


def test_explicit_full_scan_refused(tmp_path):
    result = _runner(tmp_path).run(
        "InventoryModel", args={"FullScan": True}, simulate=True,
    )
    assert result.outcome is CapabilityOutcome.REFUSED
    assert "full" in result.reason.lower()


def test_inventory_scan_refusal_helper():
    assert inventory_scan_refusal({}) is None
    assert inventory_scan_refusal({"SummaryOnly": True}) is None
    assert inventory_scan_refusal({"Category": "Walls"}) is None
    assert inventory_scan_refusal({"SummaryOnly": False, "MaxElements": 50}) is None
    assert inventory_scan_refusal({"SummaryOnly": False}) is not None
    assert inventory_scan_refusal({"full_scan": "true"}) is not None


def test_inventory_scan_refusal_mode_value_full():
    # A 'mode'/'scan' key carrying a full/unbounded value is refused even when
    # SummaryOnly is left at its safe default, so 'full' never reaches the bridge.
    assert inventory_scan_refusal({"ScanMode": "full"}) is not None
    assert inventory_scan_refusal({"mode": "all"}) is not None
    assert inventory_scan_refusal({"scan": "everything"}) is not None
    assert inventory_scan_refusal({"scan_type": "WholeModel"}) is not None
    # A bounded mode value is still allowed.
    assert inventory_scan_refusal({"ScanMode": "category"}) is None


def test_inventory_scan_refusal_oversized_or_invalid_limit():
    # A huge numeric limit is effectively unbounded and is refused outright.
    assert inventory_scan_refusal({"SummaryOnly": False, "max": 999999}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "limit": 10_000_000}) is not None
    assert inventory_scan_refusal({"max": 50_000}) is not None
    # Non-numeric / non-positive limits do not count as a bound and are refused.
    assert inventory_scan_refusal({"SummaryOnly": False, "limit": "all"}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "max": 0}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "max": -5}) is not None
    # float('inf') must not crash with OverflowError — must be refused.
    assert inventory_scan_refusal({"SummaryOnly": False, "limit": float("inf")}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "max": float("inf")}) is not None
    # A modest positive limit remains a valid bound.
    assert inventory_scan_refusal({"SummaryOnly": False, "limit": 100}) is None
    assert inventory_scan_refusal({"SummaryOnly": False, "max": 10_000}) is None


def test_inventory_scan_refusal_empty_categorical_not_a_bound():
    # Regression: a categorical key with an empty/null/malformed value is NOT a
    # real bound. With SummaryOnly=false these previously PASSED (key-presence was
    # treated as bounded), letting an effectively unbounded scan reach the bridge.
    assert inventory_scan_refusal({"SummaryOnly": False, "category": ""}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "category": None}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "category": "   "}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "category": []}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "category": False}) is not None
    # A categorical value that is itself a full-scan alias is not a bound.
    assert inventory_scan_refusal({"SummaryOnly": False, "category": "all"}) is not None
    assert inventory_scan_refusal({"SummaryOnly": False, "category": "full"}) is not None
    # Real categorical values (incl. a list with at least one real entry) bound it.
    assert inventory_scan_refusal({"SummaryOnly": False, "category": "Walls"}) is None
    assert inventory_scan_refusal(
        {"SummaryOnly": False, "categories": ["Walls", "Doors"]}) is None
    assert inventory_scan_refusal({"SummaryOnly": False, "level": 2}) is None


def test_empty_categorical_bypass_refused(tmp_path):
    # End-to-end: an empty category with SummaryOnly=false must be refused before
    # execution (no unbounded scan reaches the bridge).
    result = _runner(tmp_path).run(
        "InventoryModel", args={"SummaryOnly": False, "category": ""}, simulate=True,
    )
    assert result.outcome is CapabilityOutcome.REFUSED
    assert result.exit_code == 3
    _assert_bundle_complete(result)


def test_scan_mode_full_bypass_refused(tmp_path):
    # Regression: {"ScanMode":"full"} previously PASSED (ran summary, forwarding
    # the raw 'full' arg to the bridge). It must now be refused before execution.
    result = _runner(tmp_path).run(
        "InventoryModel", args={"ScanMode": "full"}, simulate=True,
    )
    assert result.outcome is CapabilityOutcome.REFUSED
    assert result.exit_code == 3
    _assert_bundle_complete(result)


def test_oversized_limit_bypass_refused(tmp_path):
    # Regression: a huge numeric limit previously PASSED as if bounded.
    result = _runner(tmp_path).run(
        "InventoryModel", args={"SummaryOnly": False, "max": 999999}, simulate=True,
    )
    assert result.outcome is CapabilityOutcome.REFUSED
    assert result.exit_code == 3
    assert "limit" in result.reason.lower()
    _assert_bundle_complete(result)


# ---------------------------------------------------------------------------
# Missing prerequisites — blocked
# ---------------------------------------------------------------------------


def test_live_mode_without_revit_blocked(tmp_path):
    # Live (non-simulate) with default context: Revit/model prerequisites unmet.
    result = _runner(tmp_path).run("InventoryModel", simulate=False)
    assert result.outcome is CapabilityOutcome.BLOCKED
    assert result.exit_code == 5
    assert "revit_running" in result.reason
    _assert_bundle_complete(result)


def test_explicit_context_overrides_gate(tmp_path):
    # Supplying a context that proves Revit is up lets a live run reach execution
    # (driven here through an injected fake pipe so no real Revit is needed).
    ctx = ExecutionContext(poetry_env=True, revit_running=True, model_open=True)
    result = _runner(tmp_path).run(
        "InventoryModel", simulate=False, context=ctx,
        pipe_client=_FakePipe(StepStatus.SUCCESS),
    )
    assert result.outcome is CapabilityOutcome.PASSED


# ---------------------------------------------------------------------------
# Execution failure — failed (still produces evidence)
# ---------------------------------------------------------------------------


def test_capability_failure_produces_evidence(tmp_path):
    result = _runner(tmp_path).run(
        "InventoryModel", simulate=True,
        pipe_client=_FakePipe(StepStatus.FAILED),
    )
    assert result.outcome is CapabilityOutcome.FAILED
    assert result.exit_code == 1
    assert result.passed is False
    # Evidence is still written for a failed run.
    _assert_bundle_complete(result)
    assert any(not c.passed for c in result.checks)


def test_unhandled_exception_still_writes_evidence(tmp_path):
    # Regression: an unhandled exception during execution previously propagated
    # out of run() before the bundle was written, leaving no evidence. It must
    # now be classified FAILED (exit 1) with a complete durable bundle.
    from unittest.mock import patch

    with patch(
        "axiom_core.automation_bridge.execute_capability_via_bridge",
        side_effect=RuntimeError("bridge boom"),
    ):
        result = _runner(tmp_path).run("InventoryModel", simulate=True, run_id="boom")
    assert result.outcome is CapabilityOutcome.FAILED
    assert result.exit_code == 1
    assert "RuntimeError" in result.reason and "bridge boom" in result.reason
    _assert_bundle_complete(result)
    pass_fail = json.loads((Path(result.bundle_dir) / "pass_fail.json").read_text())
    assert pass_fail["outcome"] == "failed" and pass_fail["passed"] is False
    assert any(c.name == "execution_error" and not c.passed for c in result.checks)


# ---------------------------------------------------------------------------
# Bundle always produced
# ---------------------------------------------------------------------------


def test_every_outcome_writes_a_bundle(tmp_path):
    cases = [
        ("InventoryModel", {}, True),                       # passed
        ("DefinitelyNot", {}, True),                        # denied
        ("SetParameterValue", {}, True),                    # refused
        ("InventoryModel", {"SummaryOnly": False}, True),   # refused (unbounded)
        ("InventoryModel", {}, False),                      # blocked (live)
    ]
    runner = _runner(tmp_path)
    for name, args, simulate in cases:
        result = runner.run(name, args=args, simulate=simulate)
        _assert_bundle_complete(result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_passed_exit_code(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "capability-run", "--capability", "InventoryModel", "--simulate",
        "--output-dir", str(tmp_path),
    ])
    assert res.exit_code == 0
    assert "PASSED" in res.output


def test_cli_unknown_denied_exit_code(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "capability-run", "--capability", "Nope", "--simulate",
        "--output-dir", str(tmp_path),
    ])
    assert res.exit_code == 2
    assert "DENIED" in res.output


def test_cli_mutation_refused_exit_code(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "capability-run", "--capability", "SetParameterValue", "--simulate",
        "--output-dir", str(tmp_path),
    ])
    assert res.exit_code == 3
    assert "REFUSED" in res.output


def test_cli_invalid_args_json(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "capability-run", "--capability", "InventoryModel",
        "--args-json", "{not json}", "--simulate", "--output-dir", str(tmp_path),
    ])
    assert res.exit_code == 2
    assert "Invalid --args-json" in res.output


def test_cli_args_json_must_be_object(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, [
        "capability-run", "--capability", "InventoryModel",
        "--args-json", "[1, 2, 3]", "--simulate", "--output-dir", str(tmp_path),
    ])
    assert res.exit_code == 2
    assert "must be a JSON object" in res.output
