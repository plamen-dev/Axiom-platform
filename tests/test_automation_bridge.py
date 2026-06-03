"""Tests for the Axiom Automation Bridge v0.

Covers (per PR #19 acceptance):
- driver sends a request and records durable evidence (request/response/summary/pass-fail)
- classifier: SUCCESS -> pass; FAILED -> capability_failed
- classifier: pipe unavailable (real mode) -> bridge_unavailable (request not sent)
- simulate path works without a live pipe
- transport/driver exception -> bridge_error, evidence still written
- evidence checkpoints prove: request sent / received / executed / result / evidence

All tests use a mock PipeClient, so they run off-Windows with no live Revit.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from axiom_cli.main import cli
from axiom_core import automation_bridge as ab
from axiom_core.schemas import StepStatus, ToolResult
from click.testing import CliRunner


class MockPipeClient:
    """Injectable stand-in for axiom_core.pipe_client.PipeClient."""

    def __init__(self, *, available: bool, result: ToolResult | None = None,
                 raise_on_execute: bool = False):
        self._available = available
        self._result = result
        self._raise = raise_on_execute
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return self._available

    def execute_tool(self, *, tool_name, args, simulate, step_id, transaction_name):
        self.calls.append(
            {
                "tool_name": tool_name,
                "args": args,
                "simulate": simulate,
                "step_id": step_id,
                "transaction_name": transaction_name,
            }
        )
        if self._raise:
            raise RuntimeError("pipe write failed")
        if self._result is not None:
            return self._result
        return ToolResult(step_id=step_id, status=StepStatus.SUCCESS)


def _success_result() -> ToolResult:
    return ToolResult(
        step_id=uuid4(),
        status=StepStatus.SUCCESS,
        duration_ms=42,
        output_data={"element_count": 10, "type_count": 3},
    )


def _failed_result() -> ToolResult:
    return ToolResult(
        step_id=uuid4(),
        status=StepStatus.FAILED,
        errors=["No active Revit document."],
    )


# ---------------------------------------------------------------------------
# Pure classifier (no I/O)
# ---------------------------------------------------------------------------


class TestClassifier:
    def test_success_is_pass_with_all_checkpoints(self):
        cls, _reason, cp = ab.classify_outcome(
            pipe_available=True, simulate=False, result=_success_result()
        )
        assert cls == ab.CLASS_PASS
        assert cp.request_sent and cp.request_received
        assert cp.capability_executed and cp.result_returned

    def test_failed_capability(self):
        cls, reason, cp = ab.classify_outcome(
            pipe_available=True, simulate=False, result=_failed_result()
        )
        assert cls == ab.CLASS_CAPABILITY_FAILED
        assert "No active Revit document." in reason
        assert cp.request_sent and cp.result_returned

    def test_unavailable_pipe_real_mode(self):
        cls, _reason, cp = ab.classify_outcome(
            pipe_available=False, simulate=False, result=None
        )
        assert cls == ab.CLASS_BRIDGE_UNAVAILABLE
        assert cp.request_sent is False

    def test_simulate_reachable_without_pipe(self):
        cls, _reason, cp = ab.classify_outcome(
            pipe_available=False, simulate=True, result=_success_result()
        )
        assert cls == ab.CLASS_PASS
        assert cp.request_sent

    def test_no_result_when_reachable_is_bridge_error(self):
        cls, _reason, cp = ab.classify_outcome(
            pipe_available=True, simulate=False, result=None
        )
        assert cls == ab.CLASS_BRIDGE_ERROR
        assert cp.request_sent is True


# ---------------------------------------------------------------------------
# Driver + evidence
# ---------------------------------------------------------------------------


def _read_bundle(run_dir: Path) -> dict:
    return {
        "request": json.loads((run_dir / "bridge_request.json").read_text()),
        "response": json.loads((run_dir / "bridge_response.json").read_text()),
        "pass_fail": json.loads((run_dir / "pass_fail.json").read_text()),
        "summary": (run_dir / "bridge_result_summary.md").read_text(),
    }


class TestDriver:
    def test_success_writes_full_evidence_bundle(self, tmp_path):
        client = MockPipeClient(available=True, result=_success_result())
        result = ab.execute_capability_via_bridge(
            capability="InventoryModel",
            args={"SummaryOnly": True},
            run_id="brun_test_ok",
            output_dir=str(tmp_path),
            pipe_client=client,
        )
        assert result.passed
        assert result.classification == ab.CLASS_PASS

        run_dir = tmp_path / "brun_test_ok" / "bridge"
        for fname in (
            "bridge_request.json",
            "bridge_response.json",
            "pass_fail.json",
            "bridge_result_summary.md",
        ):
            assert (run_dir / fname).exists(), fname

        bundle = _read_bundle(run_dir)
        assert bundle["request"]["capability"] == "InventoryModel"
        assert bundle["response"]["status"] == "SUCCESS"
        cp = bundle["pass_fail"]["checkpoints"]
        assert all(
            cp[k]
            for k in (
                "request_sent",
                "request_received",
                "capability_executed",
                "result_returned",
                "evidence_produced",
            )
        )
        assert "PASS" in bundle["summary"]

    def test_failed_capability_classification(self, tmp_path):
        client = MockPipeClient(available=True, result=_failed_result())
        result = ab.execute_capability_via_bridge(
            capability="InventoryModel",
            run_id="brun_test_fail",
            output_dir=str(tmp_path),
            pipe_client=client,
        )
        assert not result.passed
        assert result.classification == ab.CLASS_CAPABILITY_FAILED
        pf = json.loads(
            (tmp_path / "brun_test_fail" / "bridge" / "pass_fail.json").read_text()
        )
        assert pf["classification"] == ab.CLASS_CAPABILITY_FAILED
        assert pf["passed"] is False

    def test_unavailable_pipe_does_not_send(self, tmp_path):
        client = MockPipeClient(available=False)
        result = ab.execute_capability_via_bridge(
            capability="InventoryModel",
            run_id="brun_test_unavail",
            output_dir=str(tmp_path),
            pipe_client=client,
        )
        assert result.classification == ab.CLASS_BRIDGE_UNAVAILABLE
        assert client.calls == []  # never attempted to send
        assert result.checkpoints.request_sent is False
        # Evidence is still produced (durable record of the failed attempt).
        assert (tmp_path / "brun_test_unavail" / "bridge" / "pass_fail.json").exists()

    def test_simulate_works_without_pipe(self, tmp_path):
        client = MockPipeClient(available=False, result=_success_result())
        result = ab.execute_capability_via_bridge(
            capability="InventoryModel",
            run_id="brun_test_sim",
            simulate=True,
            output_dir=str(tmp_path),
            pipe_client=client,
        )
        assert result.passed
        assert len(client.calls) == 1
        assert client.calls[0]["simulate"] is True

    def test_transport_exception_is_bridge_error(self, tmp_path):
        client = MockPipeClient(available=True, raise_on_execute=True)
        result = ab.execute_capability_via_bridge(
            capability="InventoryModel",
            run_id="brun_test_err",
            output_dir=str(tmp_path),
            pipe_client=client,
        )
        assert result.classification == ab.CLASS_BRIDGE_ERROR
        assert (tmp_path / "brun_test_err" / "bridge" / "pass_fail.json").exists()


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestCli:
    def test_bridge_execute_simulate_exit_zero(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "bridge-execute",
                "--capability",
                "InventoryModel",
                "--simulate",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Classification: pass" in result.output

    def test_bridge_execute_invalid_args_json_exit_two(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "bridge-execute",
                "--args-json",
                "{not json}",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2
