"""Validation Evidence Runner v1 — produce durable validation evidence bundles.

Connects the Runner Command Registry (PR #22) and the Capability Validation
Registry (PR #24) into a repeatable, read-only evidence generator. For a
requested validation the runner:

1. resolves it against the **validation registry** (unknown ⇒ denied by
   default; mutation/high-risk ⇒ refused — mutation allowance is deliberately
   NOT implemented),
2. checks the **command registry** for the command the validation drives —
   permission (allowed), classification (read-only / not mutation / not
   high-risk), and prerequisites against an :class:`ExecutionContext`,
3. runs only explicitly allowed, safe/read-only validation procedures, and
4. writes a **durable evidence bundle every time** — regardless of outcome.

Evidence bundle layout (one directory per run)::

    <output>/<validation>/<evr_id>/
        validation_request.json     # what was asked
        validation_result.json      # full machine-readable result
        validation_summary.md       # human-readable summary
        command_outputs/            # captured outputs of the checks performed
        pass_fail.json              # compact, machine-readable pass/fail verdict

Scope (PR #25): read-only evidence generation only. No autonomous scheduling,
no promotion engine, no learning loop, no model mutation, no SetParameterValue
execution. This is the first step toward Axiom validating Axiom without a human
manually recording tests; it consumes governance defined in PRs #22/#24.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from axiom_core.runner import command_registry as cmdreg
from axiom_core.validation import validation_registry as valreg

DEFAULT_OUTPUT_BASE = "artifacts/validation_evidence"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Outcome taxonomy
# ---------------------------------------------------------------------------


class EvidenceOutcome(str, Enum):
    """The machine-readable verdict for one evidence run."""

    PASSED = "passed"            # ran and met every pass check
    FAILED = "failed"            # ran but at least one check failed
    DENIED = "denied"            # unknown validation — denied by default
    REFUSED = "refused"          # known but mutation/high-risk — not allowed yet
    UNSUPPORTED = "unsupported"  # known capability, no safe read-only executor here
    BLOCKED = "blocked"          # command prerequisites not met


# Process exit codes per outcome (stable contract for callers/CI).
EXIT_CODES: dict[EvidenceOutcome, int] = {
    EvidenceOutcome.PASSED: 0,
    EvidenceOutcome.FAILED: 1,
    EvidenceOutcome.DENIED: 2,
    EvidenceOutcome.REFUSED: 3,
    EvidenceOutcome.UNSUPPORTED: 4,
    EvidenceOutcome.BLOCKED: 5,
}


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """A single pass/fail assertion performed during a validation run."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class ValidationRunResult:
    """The full record of one evidence run (also serialized to the bundle)."""

    validation_name: str
    outcome: EvidenceOutcome
    reason: str
    bundle_dir: str
    started_at: str
    finished_at: str
    command_name: str | None = None
    capability_name: str | None = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome is EvidenceOutcome.PASSED

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]

    @property
    def checks_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def to_dict(self) -> dict:
        return {
            "validation_name": self.validation_name,
            "outcome": self.outcome.value,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "command_name": self.command_name,
            "capability_name": self.capability_name,
            "checks": [c.to_dict() for c in self.checks],
            "checks_passed": self.checks_passed,
            "checks_total": len(self.checks),
            "bundle_dir": self.bundle_dir,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Supported validations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupportedValidation:
    """A validation this read-only runner knows how to execute.

    ``command_name`` is the Runner Command Registry entry the validation drives
    (gated for permission / classification / prerequisites). ``capability_name``
    is the Capability Validation Registry entry consumed for the validation
    contract, when one exists.
    """

    name: str
    command_name: str
    description: str
    capability_name: str | None = None


SUPPORTED_VALIDATIONS: dict[str, SupportedValidation] = {
    "DiscoveryHarness": SupportedValidation(
        name="DiscoveryHarness",
        command_name="discovery-run",
        capability_name="DiscoveryHarness",
        description=(
            "Run DiscoveryHarness over an InventoryModel export (or the built-in "
            "deterministic export) and verify the pass conditions declared in the "
            "validation registry: categories/parameters/candidates discovered and "
            "discovery_complete."
        ),
    ),
    "CommandRegistry": SupportedValidation(
        name="CommandRegistry",
        command_name="runner-commands",
        capability_name=None,
        description=(
            "Validate the Runner Command Registry (PR #22) via its read-only "
            "inspector: the catalog is non-empty and well-formed, and unknown "
            "commands are denied by default."
        ),
    ),
    "ValidationRegistry": SupportedValidation(
        name="ValidationRegistry",
        command_name="validation-registry",
        capability_name=None,
        description=(
            "Validate the Capability Validation Registry (PR #24) via its "
            "read-only inspector: the catalog is non-empty and structurally "
            "valid, and unknown capabilities are denied by default."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Evidence runner
# ---------------------------------------------------------------------------


class EvidenceRunner:
    """Repeatable, read-only validation evidence generator.

    Read-only: it consults the command/validation registries, runs only
    safe/read-only procedures, and writes evidence bundles. It never mutates a
    model, promotes anything, schedules, or learns.
    """

    def __init__(self, *, output_base: str | Path = DEFAULT_OUTPUT_BASE):
        self.output_base = Path(output_base)

    # -- public API --------------------------------------------------------

    @staticmethod
    def supported_validations() -> list[str]:
        return sorted(SUPPORTED_VALIDATIONS)

    def run(
        self,
        validation_name: str,
        *,
        inventory_export_path: str | None = None,
        output_base: str | Path | None = None,
        context: cmdreg.ExecutionContext | None = None,
    ) -> ValidationRunResult:
        """Run one validation and write a durable evidence bundle.

        A bundle is ALWAYS written, including for denied/refused/blocked
        outcomes. Returns the :class:`ValidationRunResult`.
        """
        started = _now_iso()
        base = Path(output_base) if output_base is not None else self.output_base
        run_id = "evr_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        bundle_dir = base / validation_name / run_id
        cmd_out = bundle_dir / "command_outputs"
        cmd_out.mkdir(parents=True, exist_ok=True)

        request = {
            "validation_name": validation_name,
            "inventory_export_path": inventory_export_path,
            "requested_at": started,
            "runner": "axiom evidence-run",
            "scope": "read-only evidence generation (PR #25)",
        }

        try:
            outcome, reason, checks, command_name, capability_name = (
                self._resolve_and_run(
                    validation_name, inventory_export_path, cmd_out, context
                )
            )
        except Exception as exc:
            outcome = EvidenceOutcome.FAILED
            reason = f"Unhandled executor exception: {type(exc).__name__}: {exc}"
            checks, command_name, capability_name = [], None, None

        finished = _now_iso()
        result = ValidationRunResult(
            validation_name=validation_name,
            outcome=outcome,
            reason=reason,
            bundle_dir=str(bundle_dir),
            started_at=started,
            finished_at=finished,
            command_name=command_name,
            capability_name=capability_name,
            checks=checks,
        )
        self._write_bundle(bundle_dir, request, result)
        return result

    # -- resolution / gating ----------------------------------------------

    def _resolve_and_run(self, name, inventory_export_path, cmd_out, context):
        spec = SUPPORTED_VALIDATIONS.get(name)

        # Not a supported validation: known capability ⇒ refuse/unsupported;
        # otherwise unknown ⇒ denied by default.
        if spec is None:
            if valreg.is_known(name):
                proc = valreg.get_procedure(name)
                if proc.is_mutation:
                    return (
                        EvidenceOutcome.REFUSED,
                        f"'{name}' is a mutation capability "
                        f"({proc.capability_type.value}); the evidence runner refuses "
                        "mutation/high-risk validations (mutation allowance is not "
                        "implemented).",
                        [], None, proc.capability_name,
                    )
                return (
                    EvidenceOutcome.UNSUPPORTED,
                    f"'{name}' is a known capability but the read-only evidence "
                    "runner has no safe executor for it yet (e.g. it requires live "
                    "Revit). Supported: "
                    f"{', '.join(self.supported_validations())}.",
                    [], None, proc.capability_name,
                )
            return (
                EvidenceOutcome.DENIED,
                f"Unknown validation '{name}' — denied by default. Supported: "
                f"{', '.join(self.supported_validations())}.",
                [], None, None,
            )

        # Gate on the command registry (PR #22).
        cmd = cmdreg.get_command(spec.command_name)
        if cmd is None or not cmdreg.is_allowed(spec.command_name):
            return (
                EvidenceOutcome.DENIED,
                f"Command '{spec.command_name}' is not in the command registry — "
                "denied by default.",
                [], spec.command_name, spec.capability_name,
            )
        if cmd.is_mutation or cmd.safety_level is cmdreg.SafetyLevel.HIGH_RISK:
            return (
                EvidenceOutcome.REFUSED,
                f"Command '{spec.command_name}' is classified "
                f"{cmd.classification.value}/{cmd.safety_level.value}; the read-only "
                "evidence runner refuses mutation/high-risk commands.",
                [], spec.command_name, spec.capability_name,
            )

        ctx = context or self._context_for(name, inventory_export_path)
        unmet = cmd.unmet_prerequisites(ctx)
        if unmet:
            return (
                EvidenceOutcome.BLOCKED,
                f"Unmet prerequisites for '{spec.command_name}': "
                f"{', '.join(p.value for p in unmet)}.",
                [], spec.command_name, spec.capability_name,
            )

        executor = self._executors()[name]
        checks, reason = executor(cmd_out, inventory_export_path=inventory_export_path)
        outcome = (
            EvidenceOutcome.PASSED
            if checks and all(c.passed for c in checks)
            else EvidenceOutcome.FAILED
        )
        return outcome, reason, checks, spec.command_name, spec.capability_name

    @staticmethod
    def _context_for(name, inventory_export_path) -> cmdreg.ExecutionContext:
        """The runtime conditions this read-only runner can satisfy.

        DiscoveryHarness drives ``discovery-run`` (needs an inventory export +
        db path). When no path is given the runner uses the built-in
        deterministic export as the substrate, so the export prerequisite is
        considered satisfied; persistence is optional so a db path is reported
        available.
        """
        if name == "DiscoveryHarness":
            return cmdreg.ExecutionContext(
                poetry_env=True,
                inventory_export_available=True,
                db_path_available=True,
            )
        return cmdreg.ExecutionContext(poetry_env=True)

    def _executors(self):
        return {
            "DiscoveryHarness": self._run_discovery_harness,
            "CommandRegistry": self._run_command_registry,
            "ValidationRegistry": self._run_validation_registry,
        }

    # -- executors (read-only) --------------------------------------------

    @staticmethod
    def _run_command_registry(cmd_out: Path, *, inventory_export_path=None):
        specs = cmdreg.list_commands()
        catalog = [s.to_dict() for s in specs]
        (cmd_out / "runner-commands.json").write_text(
            json.dumps(catalog, indent=2), encoding="utf-8")

        unknown = "__definitely_not_a_command__"
        unknown_allowed = cmdreg.is_allowed(unknown)
        (cmd_out / "unknown-command-denial.json").write_text(
            json.dumps({"name": unknown, "allowed": unknown_allowed}, indent=2),
            encoding="utf-8")

        well_formed = all(
            s.name and s.classification and s.safety_level for s in specs)
        checks = [
            CheckResult("catalog_non_empty", len(specs) > 0,
                        f"{len(specs)} commands cataloged"),
            CheckResult("entries_well_formed", well_formed,
                        "every command has name/classification/safety_level"),
            CheckResult("unknown_denied_by_default", not unknown_allowed,
                        f"is_allowed('{unknown}') == {unknown_allowed}"),
        ]
        return checks, "Runner Command Registry (PR #22) inspected via its catalog API."

    @staticmethod
    def _run_validation_registry(cmd_out: Path, *, inventory_export_path=None):
        procs = valreg.list_procedures()
        catalog = [p.to_dict() for p in procs]
        (cmd_out / "validation-registry.json").write_text(
            json.dumps(catalog, indent=2), encoding="utf-8")

        try:
            valreg.validate_registry()
            structural, sdetail = True, "validate_registry() passed"
        except ValueError as exc:  # structural problem
            structural, sdetail = False, f"validate_registry() raised: {exc}"

        unknown = "__not_a_capability__"
        unknown_known = valreg.is_known(unknown)
        (cmd_out / "unknown-capability-denial.json").write_text(
            json.dumps({"capability": unknown, "known": unknown_known}, indent=2),
            encoding="utf-8")

        well_formed = all(
            p.capability_name and p.pass_conditions and p.evidence.required_items()
            for p in procs)
        checks = [
            CheckResult("catalog_non_empty", len(procs) > 0,
                        f"{len(procs)} validation definitions"),
            CheckResult("registry_structurally_valid", structural, sdetail),
            CheckResult("entries_well_formed", well_formed,
                        "every definition has name/pass_conditions/required evidence"),
            CheckResult("unknown_denied_by_default", not unknown_known,
                        f"is_known('{unknown}') == {unknown_known}"),
        ]
        return checks, "Capability Validation Registry (PR #24) inspected via its catalog API."

    @staticmethod
    def _run_discovery_harness(cmd_out: Path, *, inventory_export_path=None):
        from axiom_core.discovery import run_discovery

        proc = valreg.get_procedure("DiscoveryHarness")
        simulate = inventory_export_path is None
        discovery_out = cmd_out / "discovery_run"
        result = run_discovery(
            simulate=simulate,
            inventory_export_path=inventory_export_path,
            output_dir=str(discovery_out),
        )
        metrics = result.metrics
        (cmd_out / "discovery_metrics.json").write_text(
            json.dumps(
                {
                    "mode": result.mode,
                    "metrics": metrics,
                    "discovery_complete": result.discovery_complete,
                    "object_source": result.object_source,
                    "parameter_source": result.parameter_source,
                    "parameter_rows_total": result.parameter_rows_total,
                    "parameter_rows_joined": result.parameter_rows_joined,
                    "warnings": result.warnings,
                    "run_id": result.run_id,
                    "artifacts": result.artifacts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Drive the checks from the validation registry's declared pass
        # conditions (consume the governance definition, don't hard-code it).
        pc = valreg.PassCondition
        pcs = proc.pass_conditions if proc else ()
        checks: list[CheckResult] = []
        if pc.CATEGORIES_DISCOVERED in pcs:
            v = metrics.get("categories_discovered", 0)
            checks.append(CheckResult("categories_discovered", v > 0,
                                      f"categories_discovered={v}"))
        if pc.PARAMETERS_DISCOVERED in pcs:
            v = metrics.get("parameters_discovered", 0)
            checks.append(CheckResult("parameters_discovered", v > 0,
                                      f"parameters_discovered={v}"))
        if pc.CANDIDATES_GENERATED in pcs:
            v = metrics.get("candidate_capabilities_generated", 0)
            checks.append(CheckResult("candidates_generated", v > 0,
                                      f"candidate_capabilities_generated={v}"))
        if pc.DISCOVERY_COMPLETE in pcs:
            checks.append(CheckResult("discovery_complete", bool(result.discovery_complete),
                                      f"discovery_complete={result.discovery_complete}"))

        proc_id = proc.validation_procedure_id if proc else "(none)"
        reason = (f"DiscoveryHarness ran in {result.mode} mode; checks derived from "
                  f"validation procedure '{proc_id}'.")
        return checks, reason

    # -- bundle writing ----------------------------------------------------

    @staticmethod
    def _write_bundle(bundle_dir: Path, request: dict, result: ValidationRunResult):
        (bundle_dir / "validation_request.json").write_text(
            json.dumps(request, indent=2), encoding="utf-8")
        (bundle_dir / "validation_result.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        pass_fail = {
            "validation_name": result.validation_name,
            "outcome": result.outcome.value,
            "passed": result.passed,
            "exit_code": result.exit_code,
            "checks_passed": result.checks_passed,
            "checks_total": len(result.checks),
            "checks": [c.to_dict() for c in result.checks],
        }
        (bundle_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2), encoding="utf-8")
        (bundle_dir / "validation_summary.md").write_text(
            _summary_md(result), encoding="utf-8")


def _summary_md(result: ValidationRunResult) -> str:
    lines = [
        f"# Validation Evidence — {result.validation_name}",
        "",
        f"- **Outcome:** {result.outcome.value}",
        f"- **Passed:** {result.passed}",
        f"- **Exit code:** {result.exit_code}",
        f"- **Command (governed):** {result.command_name or '(none)'}",
        f"- **Capability (validation registry):** {result.capability_name or '(none)'}",
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
    lines.append("_Read-only evidence run (PR #25). No model mutation, scheduling, "
                 "promotion, or learning._")
    return "\n".join(lines) + "\n"
