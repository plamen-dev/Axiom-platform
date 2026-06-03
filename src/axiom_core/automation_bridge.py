"""Axiom Automation Bridge v0.

The communication boundary between *Axiom outside Revit* (CI / Validation Loop)
and *Axiom inside Revit* (the running add-in). v0 reuses the existing named-pipe
bridge (PR #2): :class:`axiom_core.pipe_client.PipeClient` sends one
``execute_tool`` request to the in-Revit ``AxiomPipeServer``, which executes a
single capability on the Revit main thread (via ``ExternalEvent``) and returns a
structured result.

This module adds the two pieces the autonomous loop needs on top of that
transport:

1. A **non-interactive** driver (no Revit UI, no human click) that sends one
   capability request and returns a structured outcome.
2. **Durable evidence** proving the full path - request sent, request received,
   capability executed, result returned, evidence produced - plus a pass/fail
   classification, written under ``artifacts/validation_runs/<run_id>/bridge/``.

Design notes
------------
- No transport is invented here; we depend on the existing ``PipeClient`` and
  inject it so the driver is unit-testable off-Windows with a mock.
- Pure outcome/classification logic is separated from I/O so it can be tested
  without a live pipe or filesystem layout.
- v0 defaults to a **read-only** capability (InventoryModel summary), so the
  acceptance test needs no model mutation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from axiom_core.schemas import StepStatus, ToolResult

# ---------------------------------------------------------------------------
# Classification taxonomy
# ---------------------------------------------------------------------------

CLASS_PASS = "pass"
CLASS_CAPABILITY_FAILED = "capability_failed"
CLASS_BRIDGE_UNAVAILABLE = "bridge_unavailable"
CLASS_BRIDGE_ERROR = "bridge_error"

ALL_BRIDGE_CLASSIFICATIONS = (
    CLASS_PASS,
    CLASS_CAPABILITY_FAILED,
    CLASS_BRIDGE_UNAVAILABLE,
    CLASS_BRIDGE_ERROR,
)


# ---------------------------------------------------------------------------
# Evidence checkpoints (the v0 acceptance proof)
# ---------------------------------------------------------------------------


@dataclass
class BridgeCheckpoints:
    """The five evidence checkpoints the acceptance test must prove."""

    request_sent: bool = False
    request_received: bool = False
    capability_executed: bool = False
    result_returned: bool = False
    evidence_produced: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "request_sent": self.request_sent,
            "request_received": self.request_received,
            "capability_executed": self.capability_executed,
            "result_returned": self.result_returned,
            "evidence_produced": self.evidence_produced,
        }


@dataclass
class BridgeRunResult:
    """Outcome of a single bridge execution."""

    run_id: str = ""
    capability: str = ""
    classification: str = ""
    reason: str = ""
    simulate: bool = False
    artifact_dir: str = ""
    checkpoints: BridgeCheckpoints = field(default_factory=BridgeCheckpoints)
    tool_result: Optional[ToolResult] = None

    @property
    def passed(self) -> bool:
        return self.classification == CLASS_PASS


# ---------------------------------------------------------------------------
# Pure outcome logic (no I/O) - unit testable
# ---------------------------------------------------------------------------


def classify_outcome(
    *,
    pipe_available: bool,
    simulate: bool,
    result: ToolResult | None,
) -> tuple[str, str, BridgeCheckpoints]:
    """Classify a bridge attempt into (classification, reason, checkpoints).

    The pipe transport is considered reachable when ``simulate`` is True (mock
    path needs no Revit) or ``pipe_available`` is True. A returned ``ToolResult``
    means the request was received and the capability executed inside Revit.
    """
    cp = BridgeCheckpoints()

    reachable = simulate or pipe_available
    if not reachable:
        return (
            CLASS_BRIDGE_UNAVAILABLE,
            "Revit pipe not available - ensure Revit is running with the Axiom "
            "add-in loaded (AxiomPipeServer.Start in App.OnStartup).",
            cp,
        )

    # We attempted (and were able) to send.
    cp.request_sent = True

    if result is None:
        return (
            CLASS_BRIDGE_ERROR,
            "No result returned from the bridge (transport error or timeout).",
            cp,
        )

    # A structured ToolResult means the in-Revit server received the request,
    # ran the capability, and returned a result.
    cp.request_received = True
    cp.capability_executed = True
    cp.result_returned = True

    if result.status == StepStatus.SUCCESS:
        return (CLASS_PASS, "Capability executed successfully via the bridge.", cp)
    if result.status == StepStatus.WARNING:
        return (
            CLASS_PASS,
            "Capability executed with warnings via the bridge.",
            cp,
        )

    errors = "; ".join(result.errors) if result.errors else "no error detail"
    return (
        CLASS_CAPABILITY_FAILED,
        f"Capability returned {result.status.value}: {errors}",
        cp,
    )


# ---------------------------------------------------------------------------
# Evidence rendering
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_bridge_run_id() -> str:
    return datetime.now(timezone.utc).strftime("brun_%Y%m%d_%H%M%S")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _tool_result_to_dict(result: ToolResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "step_id": str(result.step_id),
        "status": result.status.value,
        "created_ids": result.created_ids,
        "modified_ids": result.modified_ids,
        "warnings": result.warnings,
        "errors": result.errors,
        "duration_ms": result.duration_ms,
        "output_data": result.output_data,
    }


def render_result_summary(result: BridgeRunResult) -> str:
    """Human-readable summary (ASCII only - PowerShell-safe)."""
    cp = result.checkpoints
    status_word = "PASS" if result.passed else "FAIL"
    lines = [
        "# Axiom Automation Bridge - Run Summary",
        "",
        f"- Run ID: {result.run_id}",
        f"- Capability: {result.capability}",
        f"- Mode: {'simulate' if result.simulate else 'live'}",
        f"- Classification: {result.classification}",
        f"- Result: {status_word}",
        f"- Reason: {result.reason}",
        f"- Generated: {_utc_now_iso()}",
        "",
        "## Evidence checkpoints",
        f"- Request sent: {cp.request_sent}",
        f"- Request received: {cp.request_received}",
        f"- Capability executed: {cp.capability_executed}",
        f"- Result returned: {cp.result_returned}",
        f"- Evidence produced: {cp.evidence_produced}",
    ]

    tr = result.tool_result
    if tr is not None:
        lines += [
            "",
            "## Capability result",
            f"- Status: {tr.status.value}",
            f"- Duration (ms): {tr.duration_ms}",
            f"- Created IDs: {len(tr.created_ids)}",
            f"- Modified IDs: {len(tr.modified_ids)}",
            f"- Warnings: {len(tr.warnings)}",
            f"- Errors: {len(tr.errors)}",
        ]
        if tr.errors:
            lines.append("")
            lines.append("### Errors")
            lines += [f"- {e}" for e in tr.errors]

    return "\n".join(lines) + "\n"


def write_bridge_evidence(
    *,
    run_dir: Path,
    request: dict[str, Any],
    result: BridgeRunResult,
) -> None:
    """Write the durable bridge evidence bundle into ``run_dir``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "bridge_request.json", request)
    _write_json(run_dir / "bridge_response.json", _tool_result_to_dict(result.tool_result))
    _write_json(
        run_dir / "pass_fail.json",
        {
            "run_id": result.run_id,
            "capability": result.capability,
            "classification": result.classification,
            "reason": result.reason,
            "passed": result.passed,
            "simulate": result.simulate,
            "checkpoints": result.checkpoints.to_dict(),
            "classified_at": _utc_now_iso(),
        },
    )
    (run_dir / "bridge_result_summary.md").write_text(
        render_result_summary(result), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def execute_capability_via_bridge(
    *,
    capability: str,
    args: dict[str, Any] | None = None,
    run_id: str | None = None,
    simulate: bool = False,
    transaction_name: str | None = None,
    output_dir: str = "artifacts/validation_runs",
    pipe_client: Any = None,
    step_id: UUID | None = None,
) -> BridgeRunResult:
    """Send one capability request over the bridge and write durable evidence.

    Parameters
    ----------
    capability:
        Registered capability name (e.g. ``"InventoryModel"``).
    args:
        Capability argument dict (serialized to ``args_json``). Defaults to a
        safe empty dict (InventoryModel summary mode).
    simulate:
        If True, use the mock path (no Revit needed) - the request is still
        recorded and classified as a normal run.
    pipe_client:
        Injected client (defaults to a real :class:`PipeClient`). Injecting a
        mock makes this fully testable off-Windows.

    Returns a :class:`BridgeRunResult`; evidence is written under
    ``<output_dir>/<run_id>/bridge/``.
    """
    args = dict(args or {})
    run_id = run_id or new_bridge_run_id()
    request_id = step_id or uuid4()

    if pipe_client is None:
        from axiom_core.pipe_client import PipeClient

        pipe_client = PipeClient()

    run_dir = Path(output_dir) / run_id / "bridge"

    request_record = {
        "id": str(request_id),
        "method": "execute_tool",
        "capability": capability,
        "args": args,
        "simulate": simulate,
        "transaction_name": transaction_name or f"Axiom_{capability}",
        "sent_at": _utc_now_iso(),
    }

    pipe_available = False
    tool_result: ToolResult | None = None
    try:
        pipe_available = bool(pipe_client.is_available())
        if simulate or pipe_available:
            tool_result = pipe_client.execute_tool(
                tool_name=capability,
                args=args,
                simulate=simulate,
                step_id=request_id,
                transaction_name=transaction_name,
            )
    except Exception as exc:  # transport/driver-level failure
        classification = CLASS_BRIDGE_ERROR
        reason = f"Bridge driver error: {exc}"
        checkpoints = BridgeCheckpoints(request_sent=True)
        result = BridgeRunResult(
            run_id=run_id,
            capability=capability,
            classification=classification,
            reason=reason,
            simulate=simulate,
            artifact_dir=str(run_dir),
            checkpoints=checkpoints,
            tool_result=None,
        )
        checkpoints.evidence_produced = True
        write_bridge_evidence(run_dir=run_dir, request=request_record, result=result)
        return result

    classification, reason, checkpoints = classify_outcome(
        pipe_available=pipe_available,
        simulate=simulate,
        result=tool_result,
    )

    result = BridgeRunResult(
        run_id=run_id,
        capability=capability,
        classification=classification,
        reason=reason,
        simulate=simulate,
        artifact_dir=str(run_dir),
        checkpoints=checkpoints,
        tool_result=tool_result,
    )

    checkpoints.evidence_produced = True
    write_bridge_evidence(run_dir=run_dir, request=request_record, result=result)
    return result
