"""Capability Execution Runner v1 — governed execution of safe capabilities.

The first step from *validation evidence* (PR #25) to *governed capability
execution*. For a requested capability the runner:

1. resolves it against the set of explicitly supported capabilities (unknown ⇒
   denied by default; known-but-mutation/high-risk ⇒ refused — mutation
   allowance is deliberately NOT implemented),
2. gates the command the capability drives against the **Runner Command
   Registry** (PR #22) — permission (allowed), classification/safety
   (not mutation, not high-risk), and prerequisites against an
   :class:`ExecutionContext`,
3. maps the capability to its **Capability Validation Registry** (PR #24)
   contract where one exists (evidence/pass expectations are recorded), and
4. executes only explicitly allowed, safe/read-only capabilities through the
   existing **Automation Bridge** (PR #19) and writes a **durable evidence
   bundle every time** — regardless of outcome.

Evidence bundle layout (one directory per run)::

    artifacts/capability_runs/<run_id>/
        capability_request.json     # what was asked
        capability_result.json      # full machine-readable result
        capability_summary.md       # human-readable summary
        command_outputs/            # captured outputs of the execution
        pass_fail.json              # compact, machine-readable verdict

Scope (PR #26): governed execution of safe/read-only capabilities only. The
only initial supported capability is **InventoryModel** in summary / bounded
read-only mode — full/unbounded scans are refused (they crashed Revit 2027).
No autonomous scheduling, no discovered-candidate execution, no
SetParameterValue execution, no mutation allowance, no retry engine, no
promotion engine, no scoring, no learning loop, no workflow generation, and no
external/MCP integrations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from axiom_core.runner import command_registry as cmdreg
from axiom_core.validation import validation_registry as valreg

DEFAULT_OUTPUT_BASE = "artifacts/capability_runs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Outcome taxonomy
# ---------------------------------------------------------------------------


class CapabilityOutcome(str, Enum):
    """The machine-readable verdict for one capability run."""

    PASSED = "passed"            # executed and met every pass check
    FAILED = "failed"           # executed but at least one check failed
    DENIED = "denied"           # unknown capability — denied by default
    REFUSED = "refused"         # known but mutation/high-risk/unbounded — not allowed
    UNSUPPORTED = "unsupported"  # known capability, no safe executor here yet
    BLOCKED = "blocked"         # command prerequisites not met


# Process exit codes per outcome (stable contract for callers/CI). Mirrors the
# Validation Evidence Runner (PR #25) so the two runners are interchangeable.
EXIT_CODES: dict[CapabilityOutcome, int] = {
    CapabilityOutcome.PASSED: 0,
    CapabilityOutcome.FAILED: 1,
    CapabilityOutcome.DENIED: 2,
    CapabilityOutcome.REFUSED: 3,
    CapabilityOutcome.UNSUPPORTED: 4,
    CapabilityOutcome.BLOCKED: 5,
}


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """A single pass/fail assertion performed during a capability run."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class CapabilityRunResult:
    """The full record of one capability run (also serialized to the bundle)."""

    capability_name: str
    outcome: CapabilityOutcome
    reason: str
    bundle_dir: str
    started_at: str
    finished_at: str
    simulate: bool = False
    command_name: str | None = None
    validation_capability: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome is CapabilityOutcome.PASSED

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]

    @property
    def checks_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "outcome": self.outcome.value,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "simulate": self.simulate,
            "command_name": self.command_name,
            "validation_capability": self.validation_capability,
            "args": self.args,
            "checks": [c.to_dict() for c in self.checks],
            "checks_passed": self.checks_passed,
            "checks_total": len(self.checks),
            "bundle_dir": self.bundle_dir,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Supported capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupportedCapability:
    """A capability this runner knows how to execute safely.

    ``command_name`` is the Runner Command Registry entry the execution drives
    (gated for permission / classification / prerequisites). ``validation_capability``
    is the Capability Validation Registry entry consumed for the evidence/pass
    contract, when one exists.
    """

    name: str
    command_name: str
    description: str
    validation_capability: str | None = None


SUPPORTED_CAPABILITIES: dict[str, SupportedCapability] = {
    "InventoryModel": SupportedCapability(
        name="InventoryModel",
        command_name="bridge-execute",
        validation_capability="InventoryModel",
        description=(
            "Execute the read-only InventoryModel capability through the "
            "Automation Bridge in summary / bounded mode and record evidence. "
            "Full/unbounded scans are refused (crashed Revit 2027)."
        ),
    ),
}


# Categorical keys that bound an InventoryModel scan to a safe subset.
_INVENTORY_CATEGORICAL_KEYS = {
    "category", "categories", "categoryname", "categoryfilter", "category_filter",
    "level", "levels", "levelname",
    "sample", "samplevalues", "sample_values",
}
# Numeric limit keys. These only bound a scan when their value is a positive
# integer at or below ``_INVENTORY_MAX_BOUND`` — an oversized limit is
# effectively unbounded and is refused.
_INVENTORY_LIMIT_KEYS = {
    "samplesize", "sample_size", "maxelements", "max_elements",
    "max", "limit", "take", "top",
}
# Conservative ceiling for a bounded read-only scan. A larger limit defeats the
# purpose of bounding (full scans crashed Revit 2027). Tunable if/when chunked
# extraction is proven safe.
_INVENTORY_MAX_BOUND = 10_000
# Flag-style keys whose truthy value requests a full/whole-model scan.
_INVENTORY_FULL_KEYS = {"fullscan", "full_scan", "full", "wholemodel", "whole_model"}
# Mode-style keys whose value can request a full/unbounded scan.
_INVENTORY_MODE_KEYS = {"scanmode", "scan_mode", "mode", "scan", "scantype", "scan_type"}
_INVENTORY_FULL_VALUES = {
    "full", "all", "everything", "complete", "unbounded",
    "whole", "wholemodel", "whole_model", "entire", "fullscan", "full_scan",
}


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _valid_limit(value: Any) -> bool:
    """A numeric limit only bounds a scan when it is a positive int <= ceiling."""
    if isinstance(value, bool):
        return False
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False
    return 0 < n <= _INVENTORY_MAX_BOUND


def _valid_categorical(value: Any) -> bool:
    """A categorical bound must name a real, narrowing subset.

    An empty/whitespace/null value, a boolean, or a full-scan alias
    (``all``/``everything``/``full`` …) does not bound a scan — accepting it
    would let an unbounded ``SummaryOnly=false`` scan reach the bridge.
    """
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        s = value.strip().lower()
        return bool(s) and s not in _INVENTORY_FULL_VALUES
    if isinstance(value, (list, tuple, set)):
        return any(_valid_categorical(v) for v in value)
    if isinstance(value, (int, float)):
        return True
    return False


def _has_valid_bound(lowered: dict[str, Any]) -> bool:
    if any(
        key in lowered and _valid_categorical(lowered[key])
        for key in _INVENTORY_CATEGORICAL_KEYS
    ):
        return True
    return any(
        key in lowered and _valid_limit(lowered[key])
        for key in _INVENTORY_LIMIT_KEYS
    )


def inventory_scan_refusal(args: dict[str, Any]) -> str | None:
    """Return a refusal reason if ``args`` request an unsafe InventoryModel scan.

    Safe (allowed): summary mode (the default) and bounded scans that name a
    category/level/sample or a modest positive numeric limit. Unsafe (refused):
    an explicit full/whole-model request (flag or ``mode``/``scan`` value), an
    oversized or non-numeric limit (effectively unbounded), or turning summary
    mode off without a valid bound. Returns ``None`` when the scan is allowed.
    """
    lowered = {str(k).lower(): v for k, v in args.items()}

    for key in _INVENTORY_FULL_KEYS:
        if key in lowered and _is_truthy(lowered[key]):
            return (
                "InventoryModel full/whole-model scan is refused — it is "
                "blocked/high-risk (crashed Revit 2027). Use summary or a "
                "bounded category/level/sample scan."
            )

    # Mode/scan keys carrying a full/unbounded value are refused regardless of
    # SummaryOnly, so a raw 'full' value can never reach the bridge.
    for key in _INVENTORY_MODE_KEYS:
        if key in lowered and str(lowered[key]).strip().lower() in _INVENTORY_FULL_VALUES:
            return (
                f"InventoryModel {key}={lowered[key]!r} requests a full/unbounded "
                "scan, which is refused — it is blocked/high-risk (crashed Revit "
                "2027). Use summary or a bounded category/level/sample scan."
            )

    # An oversized or non-numeric limit is effectively unbounded — refuse it
    # unconditionally so a huge 'max'/'limit' can never bypass bounding.
    for key in _INVENTORY_LIMIT_KEYS:
        if key in lowered and not _valid_limit(lowered[key]):
            return (
                f"InventoryModel {key}={lowered[key]!r} is not a safe bound — a "
                f"limit must be a positive integer <= {_INVENTORY_MAX_BOUND}. An "
                "oversized/invalid limit is refused (effectively unbounded; "
                "crashed Revit 2027)."
            )

    # SummaryOnly defaults to True (summary mode). Only an explicit opt-out
    # without a valid bound is an unbounded scan.
    summary_only = lowered.get("summaryonly", True)
    if not _is_truthy(summary_only) and not _has_valid_bound(lowered):
        return (
            "InventoryModel scan with SummaryOnly=false must be bounded "
            "(category/level/sample or a modest numeric limit). An unbounded "
            "parameter scan is refused — it is blocked/high-risk (crashed "
            "Revit 2027)."
        )
    return None


# ---------------------------------------------------------------------------
# Capability runner
# ---------------------------------------------------------------------------


class CapabilityRunner:
    """Governed execution runner for safe/read-only capabilities.

    It consults the command/validation registries, executes only explicitly
    allowed safe/read-only capabilities through the Automation Bridge, and
    writes an evidence bundle every time. It never mutates a model, promotes
    anything, schedules, retries, or learns.
    """

    def __init__(self, *, output_base: str | Path = DEFAULT_OUTPUT_BASE):
        self.output_base = Path(output_base)

    # -- public API --------------------------------------------------------

    @staticmethod
    def supported_capabilities() -> list[str]:
        return sorted(SUPPORTED_CAPABILITIES)

    def run(
        self,
        capability_name: str,
        *,
        args: dict[str, Any] | None = None,
        simulate: bool = False,
        run_id: str | None = None,
        output_base: str | Path | None = None,
        context: cmdreg.ExecutionContext | None = None,
        pipe_client: Any = None,
    ) -> CapabilityRunResult:
        """Run one capability and write a durable evidence bundle.

        A bundle is ALWAYS written, including for denied/refused/blocked
        outcomes. Returns the :class:`CapabilityRunResult`.
        """
        started = _now_iso()
        args = dict(args or {})
        base = Path(output_base) if output_base is not None else self.output_base
        run_id = run_id or ("crun_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
        bundle_dir = base / capability_name / run_id
        cmd_out = bundle_dir / "command_outputs"
        cmd_out.mkdir(parents=True, exist_ok=True)

        request = {
            "capability_name": capability_name,
            "args": args,
            "simulate": simulate,
            "run_id": run_id,
            "requested_at": started,
            "runner": "axiom capability-run",
            "scope": "governed execution of safe/read-only capabilities (PR #26)",
        }

        try:
            outcome, reason, checks, command_name, validation_capability = self._resolve_and_run(
                capability_name, args, simulate, cmd_out, context, pipe_client
            )
        except Exception as exc:  # noqa: BLE001 — any failure must still write evidence
            # An unhandled error during gating/execution is a failure, not a
            # missing run: classify it FAILED and fall through so the durable
            # evidence bundle is still written (evidence is produced every time).
            outcome = CapabilityOutcome.FAILED
            reason = f"Execution raised an unhandled {type(exc).__name__}: {exc}"
            checks = [CheckResult("execution_error", False, reason)]
            command_name = None
            validation_capability = None
            spec = SUPPORTED_CAPABILITIES.get(capability_name)
            if spec is not None:
                command_name = spec.command_name
                validation_capability = spec.validation_capability

        finished = _now_iso()
        result = CapabilityRunResult(
            capability_name=capability_name,
            outcome=outcome,
            reason=reason,
            bundle_dir=str(bundle_dir),
            started_at=started,
            finished_at=finished,
            simulate=simulate,
            command_name=command_name,
            validation_capability=validation_capability,
            args=args,
            checks=checks,
        )
        self._write_bundle(bundle_dir, request, result)
        return result

    # -- resolution / gating ----------------------------------------------

    def _resolve_and_run(self, name, args, simulate, cmd_out, context, pipe_client):
        spec = SUPPORTED_CAPABILITIES.get(name)

        # Not an explicitly supported capability: known capability ⇒
        # refuse (mutation) / unsupported; otherwise unknown ⇒ denied.
        if spec is None:
            if valreg.is_known(name):
                proc = valreg.get_procedure(name)
                if proc.is_mutation:
                    return (
                        CapabilityOutcome.REFUSED,
                        f"'{name}' is a mutation capability "
                        f"({proc.capability_type.value}); the capability runner refuses "
                        "mutation/high-risk capabilities (mutation allowance is not "
                        "implemented).",
                        [], None, proc.capability_name,
                    )
                return (
                    CapabilityOutcome.UNSUPPORTED,
                    f"'{name}' is a known capability but the runner has no safe "
                    "executor for it yet. Supported: "
                    f"{', '.join(self.supported_capabilities())}.",
                    [], None, proc.capability_name,
                )
            return (
                CapabilityOutcome.DENIED,
                f"Unknown capability '{name}' — denied by default. Supported: "
                f"{', '.join(self.supported_capabilities())}.",
                [], None, None,
            )

        # Gate on the command registry (PR #22).
        cmd = cmdreg.get_command(spec.command_name)
        if cmd is None or not cmdreg.is_allowed(spec.command_name):
            return (
                CapabilityOutcome.DENIED,
                f"Command '{spec.command_name}' is not in the command registry — "
                "denied by default.",
                [], spec.command_name, spec.validation_capability,
            )
        if cmd.is_mutation or cmd.safety_level is cmdreg.SafetyLevel.HIGH_RISK:
            return (
                CapabilityOutcome.REFUSED,
                f"Command '{spec.command_name}' is classified "
                f"{cmd.classification.value}/{cmd.safety_level.value}; the capability "
                "runner refuses mutation/high-risk commands.",
                [], spec.command_name, spec.validation_capability,
            )

        # Capability-level safety: refuse unsafe InventoryModel scan shapes.
        if name == "InventoryModel":
            refusal = inventory_scan_refusal(args)
            if refusal:
                return (
                    CapabilityOutcome.REFUSED,
                    refusal,
                    [], spec.command_name, spec.validation_capability,
                )

        # Prerequisite gate against the resolved execution context.
        ctx = context or self._context_for(name, simulate)
        unmet = cmd.unmet_prerequisites(ctx)
        if unmet:
            return (
                CapabilityOutcome.BLOCKED,
                f"Unmet prerequisites for '{spec.command_name}': "
                f"{', '.join(p.value for p in unmet)}."
                + ("" if simulate else " (use --simulate to exercise the mock path)."),
                [], spec.command_name, spec.validation_capability,
            )

        executor = self._executors()[name]
        checks, reason = executor(cmd_out, args=args, simulate=simulate, pipe_client=pipe_client)
        outcome = (
            CapabilityOutcome.PASSED
            if checks and all(c.passed for c in checks)
            else CapabilityOutcome.FAILED
        )
        return outcome, reason, checks, spec.command_name, spec.validation_capability

    @staticmethod
    def _context_for(name, simulate) -> cmdreg.ExecutionContext:
        """The runtime conditions this runner reports for gating.

        In ``simulate`` mode the Automation Bridge uses the mock path (no live
        Revit), so the live-Revit prerequisites are considered satisfied. In
        live mode the defaults leave Revit/​model prerequisites unmet, so an
        off-Windows / no-Revit run is correctly BLOCKED unless the caller
        supplies a context proving Revit is up.
        """
        if name == "InventoryModel":
            return cmdreg.ExecutionContext(
                poetry_env=True,
                revit_running=simulate,
                model_open=simulate,
            )
        return cmdreg.ExecutionContext(poetry_env=True)

    def _executors(self):
        return {
            "InventoryModel": self._run_inventory_model,
        }

    # -- executors (safe/read-only) ---------------------------------------

    @staticmethod
    def _run_inventory_model(cmd_out: Path, *, args, simulate, pipe_client=None):
        from axiom_core.automation_bridge import execute_capability_via_bridge

        # Default to safe summary mode when the caller passes no args.
        exec_args = dict(args)
        exec_args.setdefault("SummaryOnly", True)

        bridge = execute_capability_via_bridge(
            capability="InventoryModel",
            args=exec_args,
            simulate=simulate,
            output_dir=str(cmd_out / "bridge"),
            pipe_client=pipe_client,
        )

        out = (bridge.tool_result.output_data if bridge.tool_result else {}) or {}
        element_count = out.get("element_count", 0)
        (cmd_out / "bridge_result.json").write_text(
            json.dumps(
                {
                    "run_id": bridge.run_id,
                    "capability": bridge.capability,
                    "classification": bridge.classification,
                    "reason": bridge.reason,
                    "simulate": bridge.simulate,
                    "artifact_dir": bridge.artifact_dir,
                    "checkpoints": bridge.checkpoints.to_dict(),
                    "summary": {
                        "source_model": out.get("source_model"),
                        "element_count": element_count,
                        "type_count": out.get("type_count"),
                        "parameter_count": out.get("parameter_count"),
                    },
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        cp = bridge.checkpoints
        checks = [
            CheckResult("bridge_request_sent", cp.request_sent,
                        f"classification={bridge.classification}"),
            CheckResult("capability_executed", cp.capability_executed,
                        bridge.reason),
            CheckResult("result_returned", cp.result_returned,
                        "structured ToolResult returned" if cp.result_returned
                        else "no result returned"),
            CheckResult("execution_pass", bridge.passed,
                        f"bridge classification == {bridge.classification}"),
            CheckResult("inventory_summary_present", bool(element_count),
                        f"element_count={element_count}, "
                        f"source_model={out.get('source_model')!r}"),
            CheckResult("evidence_produced", cp.evidence_produced,
                        f"bridge evidence at {bridge.artifact_dir}"),
        ]
        mode = "simulate" if simulate else "live"
        reason = (
            f"InventoryModel executed via the Automation Bridge in {mode} mode "
            f"(summary/bounded); bridge classification: {bridge.classification}."
        )
        return checks, reason

    # -- bundle writing ----------------------------------------------------

    @staticmethod
    def _write_bundle(bundle_dir: Path, request: dict, result: CapabilityRunResult):
        (bundle_dir / "capability_request.json").write_text(
            json.dumps(request, indent=2, default=str), encoding="utf-8")

        result_dict = result.to_dict()
        result_dict["validation_contract"] = _validation_contract(result.validation_capability)
        (bundle_dir / "capability_result.json").write_text(
            json.dumps(result_dict, indent=2, default=str), encoding="utf-8")

        pass_fail = {
            "capability_name": result.capability_name,
            "outcome": result.outcome.value,
            "passed": result.passed,
            "exit_code": result.exit_code,
            "checks_passed": result.checks_passed,
            "checks_total": len(result.checks),
            "checks": [c.to_dict() for c in result.checks],
        }
        (bundle_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2), encoding="utf-8")
        (bundle_dir / "capability_summary.md").write_text(
            _summary_md(result), encoding="utf-8")


def _validation_contract(capability_name: str | None) -> dict | None:
    """The validation registry (PR #24) evidence/pass contract for a capability.

    Recorded in the bundle so governed execution maps to declared evidence
    expectations. Returns ``None`` when the capability has no registry entry.
    """
    if not capability_name:
        return None
    proc = valreg.get_procedure(capability_name)
    if proc is None:
        return None
    return {
        "validation_procedure_id": proc.validation_procedure_id,
        "pass_conditions": [pc.value for pc in proc.pass_conditions],
        "required_artifacts": [it.to_dict() for it in proc.evidence.required_artifacts],
        "required_checkpoints": [it.to_dict() for it in proc.evidence.required_checkpoints],
    }


def _summary_md(result: CapabilityRunResult) -> str:
    lines = [
        f"# Capability Execution — {result.capability_name}",
        "",
        f"- **Outcome:** {result.outcome.value}",
        f"- **Passed:** {result.passed}",
        f"- **Exit code:** {result.exit_code}",
        f"- **Mode:** {'simulate' if result.simulate else 'live'}",
        f"- **Command (governed):** {result.command_name or '(none)'}",
        f"- **Validation contract:** {result.validation_capability or '(none)'}",
        f"- **Args:** `{json.dumps(result.args)}`",
        f"- **Started:** {result.started_at}",
        f"- **Finished:** {result.finished_at}",
        "",
        f"{result.reason}",
        "",
    ]
    if result.checks:
        lines.append(f"## Checks ({result.checks_passed}/{len(result.checks)} passed)")
        lines.append("")
        lines.append("| Check | Result | Detail |")
        lines.append("|-------|--------|--------|")
        for c in result.checks:
            lines.append(f"| {c.name} | {'PASS' if c.passed else 'FAIL'} | {c.detail} |")
        lines.append("")
    lines.append("_Governed capability execution (PR #26). Safe/read-only only; "
                 "no mutation, scheduling, retry, promotion, or learning._")
    return "\n".join(lines) + "\n"
