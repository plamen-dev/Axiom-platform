"""Axiom Model Health and Capability Readiness Engine v1.

Produces a local model health/readiness report for the active Revit model and
integrates with the run spine (PR #31) for artifact storage and audit logging.

Outputs per health/readiness run::

    axiom_environment_report.json
    axiom_model_health.json
    axiom_model_health.md
    axiom_capability_readiness.json

These are stored in the run artifact folder alongside the standard run spine
files (run_metadata.json, command_input.json, etc.).

The readiness engine is extensible: each capability registers its own
``ReadinessCheck`` callable. GridCreation is the first proof target.
"""

from __future__ import annotations

import json as _json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path as _Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKER_VERSION = "1.0.0"
RULESET_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: _Path, data: dict[str, Any]) -> None:
    """Write a dict as indented JSON. Local helper to avoid private imports."""
    path.write_text(
        _json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Model health data
# ---------------------------------------------------------------------------


@dataclass
class ModelHealth:
    """Captured model health snapshot.

    Fields that cannot be safely retrieved are ``None``.
    """

    generated_at_utc: str = ""
    checker_version: str = CHECKER_VERSION
    ruleset_version: str = RULESET_VERSION
    revit_version: str | None = None
    model_path: str | None = None
    model_path_redacted: str | None = None
    model_last_modified_utc: str | None = None
    active_document_title: str | None = None
    active_view_name: str | None = None
    active_view_type: str | None = None
    worksharing_enabled: bool | None = None
    linked_model_count: int | None = None
    level_count: int | None = None
    grid_count: int | None = None
    room_count: int | None = None
    space_count: int | None = None
    warning_count: int | None = None
    cad_import_count: int | None = None
    cad_link_count: int | None = None
    view_template_count: int | None = None
    sheet_count: int | None = None
    stale_status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "checker_version": self.checker_version,
            "ruleset_version": self.ruleset_version,
            "revit_version": self.revit_version,
            "model_path": self.model_path,
            "model_path_redacted": self.model_path_redacted,
            "model_last_modified_utc": self.model_last_modified_utc,
            "active_document_title": self.active_document_title,
            "active_view_name": self.active_view_name,
            "active_view_type": self.active_view_type,
            "worksharing_enabled": self.worksharing_enabled,
            "linked_model_count": self.linked_model_count,
            "level_count": self.level_count,
            "grid_count": self.grid_count,
            "room_count": self.room_count,
            "space_count": self.space_count,
            "warning_count": self.warning_count,
            "cad_import_count": self.cad_import_count,
            "cad_link_count": self.cad_link_count,
            "view_template_count": self.view_template_count,
            "sheet_count": self.sheet_count,
            "stale_status": self.stale_status,
        }


# ---------------------------------------------------------------------------
# Environment report
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentReport:
    """Snapshot of the Axiom execution environment."""

    generated_at_utc: str = ""
    axiom_version: str = "0.1.0"
    python_version: str = ""
    platform_system: str = ""
    platform_release: str = ""
    platform_machine: str = ""
    revit_version: str | None = None
    revit_connected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "axiom_version": self.axiom_version,
            "python_version": self.python_version,
            "platform_system": self.platform_system,
            "platform_release": self.platform_release,
            "platform_machine": self.platform_machine,
            "revit_version": self.revit_version,
            "revit_connected": self.revit_connected,
        }


def capture_environment(
    revit_version: str | None = None,
    revit_connected: bool = False,
) -> EnvironmentReport:
    """Capture a snapshot of the current execution environment."""
    return EnvironmentReport(
        generated_at_utc=_now_iso(),
        python_version=sys.version.split()[0],
        platform_system=platform.system(),
        platform_release=platform.release(),
        platform_machine=platform.machine(),
        revit_version=revit_version,
        revit_connected=revit_connected,
    )


# ---------------------------------------------------------------------------
# Capability readiness
# ---------------------------------------------------------------------------


@dataclass
class CapabilityReadiness:
    """Readiness assessment for a single capability against a model."""

    capability: str
    capability_version: str = ""
    readiness: str = "UNKNOWN"  # READY | WARNING | BLOCKED | UNKNOWN
    risk_level: str = "low"
    dry_run_available: bool = True
    execute_available: bool = False
    blocking_conditions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_user_decisions: list[str] = field(default_factory=list)
    recommended_next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "capability_version": self.capability_version,
            "readiness": self.readiness,
            "risk_level": self.risk_level,
            "dry_run_available": self.dry_run_available,
            "execute_available": self.execute_available,
            "blocking_conditions": self.blocking_conditions,
            "warnings": self.warnings,
            "required_user_decisions": self.required_user_decisions,
            "recommended_next_actions": self.recommended_next_actions,
        }


class ReadinessCheck(Protocol):
    """Protocol for capability-specific readiness check functions.

    Each capability registers a callable matching this signature.
    """

    def __call__(self, health: ModelHealth) -> CapabilityReadiness: ...


# ---------------------------------------------------------------------------
# Readiness registry
#
# The registry is intentionally mutable module-level state.  Capabilities
# self-register at import time (see ``register_readiness_check`` below).
# This mirrors how capability registries work across the Axiom codebase
# (e.g. the capability registry in server_tools).
#
# **Test isolation:**  Call ``reset_readiness_registry()`` inside test
# teardown (or use the ``_readiness_checks`` dict directly via
# ``monkeypatch``) to restore the default set.  The helper re-registers
# only the built-in GridCreation check so that custom checks added by a
# test do not leak into subsequent tests.
# ---------------------------------------------------------------------------


_readiness_checks: dict[str, ReadinessCheck] = {}


def register_readiness_check(capability: str, check: ReadinessCheck) -> None:
    """Register a readiness check for a capability."""
    _readiness_checks[capability] = check


def get_readiness_check(capability: str) -> ReadinessCheck | None:
    """Look up the readiness check for a capability."""
    return _readiness_checks.get(capability)


def list_readiness_capabilities() -> list[str]:
    """Return names of capabilities with registered readiness checks."""
    return sorted(_readiness_checks.keys())


def reset_readiness_registry() -> None:
    """Reset the registry to only the built-in checks.

    Intended for test isolation.  After calling this, only
    GridCreation (the sole built-in) is registered.
    """
    _readiness_checks.clear()
    # Re-register built-ins (defined later in this module).
    # Deferred import avoids circular reference at module level.
    _readiness_checks["GridCreation"] = _grid_creation_readiness  # noqa: F821


def evaluate_readiness(
    capability: str, health: ModelHealth
) -> CapabilityReadiness:
    """Evaluate readiness for a capability. Returns UNKNOWN if no check registered."""
    check = _readiness_checks.get(capability)
    if check is None:
        return CapabilityReadiness(
            capability=capability,
            readiness="UNKNOWN",
            execute_available=False,
            warnings=[f"No readiness check registered for '{capability}'."],
            recommended_next_actions=[
                f"Register a readiness check for '{capability}'."
            ],
        )
    return check(health)


def evaluate_all_readiness(
    health: ModelHealth,
) -> list[CapabilityReadiness]:
    """Evaluate readiness for all registered capabilities."""
    return [evaluate_readiness(cap, health) for cap in sorted(_readiness_checks)]


# ---------------------------------------------------------------------------
# GridCreation readiness check
# ---------------------------------------------------------------------------


def _grid_creation_readiness(health: ModelHealth) -> CapabilityReadiness:
    """Readiness check for GridCreation capability."""
    blocking: list[str] = []
    warnings: list[str] = []
    decisions: list[str] = []
    actions: list[str] = []

    # No active document → BLOCKED
    if health.active_document_title is None:
        blocking.append("No active Revit document detected.")
        actions.append("Open a Revit document before running GridCreation.")

    # Invalid/unsupported active view → WARNING or BLOCKED
    supported_views = {"FloorPlan", "CeilingPlan", "EngineeringPlan"}
    if health.active_view_type is None:
        if health.active_document_title is not None:
            warnings.append(
                "Active view type is unknown. GridCreation may not work "
                "in all view contexts."
            )
            actions.append("Switch to a floor plan view for best results.")
    elif health.active_view_type not in supported_views:
        if health.active_view_type in {"ThreeD", "Section", "Elevation", "Schedule"}:
            blocking.append(
                f"Active view type '{health.active_view_type}' is not "
                "supported for grid creation."
            )
            actions.append("Switch to a floor plan view.")
        else:
            warnings.append(
                f"Active view type '{health.active_view_type}' may not be "
                "optimal for grid creation."
            )
            actions.append("Consider switching to a floor plan view.")

    # Revit version unavailable → WARNING
    if health.revit_version is None:
        warnings.append("Revit version is unavailable.")
        actions.append("Verify Revit connection is active.")

    # Existing grids → warning + user decision
    if health.grid_count is not None and health.grid_count > 0:
        warnings.append(
            f"Model already contains {health.grid_count} grids. "
            "Creating new grids may conflict with existing ones."
        )
        decisions.append(
            f"Confirm whether to proceed with {health.grid_count} existing "
            "grids in the model."
        )
        actions.append("Review existing grids before proceeding.")

    # Determine overall readiness
    if blocking:
        readiness = "BLOCKED"
    elif warnings or decisions:
        readiness = "WARNING"
    else:
        readiness = "READY"

    return CapabilityReadiness(
        capability="GridCreation",
        capability_version="1.0.0",
        readiness=readiness,
        risk_level="medium",
        dry_run_available=True,
        execute_available=readiness != "BLOCKED",
        blocking_conditions=blocking,
        warnings=warnings,
        required_user_decisions=decisions,
        recommended_next_actions=actions,
    )


# Register the GridCreation readiness check at import time.
register_readiness_check("GridCreation", _grid_creation_readiness)


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------


def generate_health_markdown(
    health: ModelHealth,
    readiness_results: list[CapabilityReadiness],
) -> str:
    """Generate a human-readable Markdown health report."""
    lines: list[str] = [
        "# Axiom Model Health Report",
        "",
        f"**Generated:** {health.generated_at_utc}",
        f"**Model:** {health.model_path_redacted or health.model_path or 'N/A'}",
        f"**Revit version:** {health.revit_version or 'N/A'}",
        f"**Active view:** {health.active_view_name or 'N/A'}"
        f" ({health.active_view_type or 'N/A'})",
        "",
        "## Health Summary",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Checker version | {health.checker_version} |",
        f"| Ruleset version | {health.ruleset_version} |",
        f"| Document title | {health.active_document_title or 'N/A'} |",
        f"| Worksharing | {_fmt_nullable(health.worksharing_enabled)} |",
        f"| Linked models | {_fmt_nullable(health.linked_model_count)} |",
        f"| Levels | {_fmt_nullable(health.level_count)} |",
        f"| Grids | {_fmt_nullable(health.grid_count)} |",
        f"| Rooms | {_fmt_nullable(health.room_count)} |",
        f"| Spaces | {_fmt_nullable(health.space_count)} |",
        f"| Warnings | {_fmt_nullable(health.warning_count)} |",
        f"| CAD imports | {_fmt_nullable(health.cad_import_count)} |",
        f"| CAD links | {_fmt_nullable(health.cad_link_count)} |",
        f"| View templates | {_fmt_nullable(health.view_template_count)} |",
        f"| Sheets | {_fmt_nullable(health.sheet_count)} |",
        f"| Stale status | {health.stale_status} |",
        "",
        "## Capability Readiness",
        "",
    ]

    for r in readiness_results:
        lines.append(f"### {r.capability}")
        lines.append("")
        lines.append(f"**Status:** {r.readiness}")
        lines.append(f"**Risk level:** {r.risk_level}")
        lines.append(f"**Dry-run available:** {r.dry_run_available}")
        lines.append(f"**Execute available:** {r.execute_available}")
        lines.append("")

        if r.blocking_conditions:
            lines.append("**Blocking conditions:**")
            for bc in r.blocking_conditions:
                lines.append(f"- {bc}")
            lines.append("")

        if r.warnings:
            lines.append("**Warnings:**")
            for w in r.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if r.required_user_decisions:
            lines.append("**Required user decisions:**")
            for d in r.required_user_decisions:
                lines.append(f"- {d}")
            lines.append("")

        if r.recommended_next_actions:
            lines.append("**Recommended next actions:**")
            for a in r.recommended_next_actions:
                lines.append(f"- {a}")
            lines.append("")

    return "\n".join(lines)


def _fmt_nullable(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


# ---------------------------------------------------------------------------
# Run spine integration — execute a health/readiness run
# ---------------------------------------------------------------------------


@dataclass
class HealthRunContext:
    """Input for a model health/readiness run."""

    model_path: str | None = None
    model_path_redacted: str | None = None
    revit_version: str | None = None
    revit_connected: bool = False
    active_document_title: str | None = None
    active_view_name: str | None = None
    active_view_type: str | None = None
    model_last_modified_utc: str | None = None
    worksharing_enabled: bool | None = None
    linked_model_count: int | None = None
    level_count: int | None = None
    grid_count: int | None = None
    room_count: int | None = None
    space_count: int | None = None
    warning_count: int | None = None
    cad_import_count: int | None = None
    cad_link_count: int | None = None
    view_template_count: int | None = None
    sheet_count: int | None = None
    stale_status: str = "unknown"
    capabilities: list[str] | None = None
    source: str = "cli"


@dataclass
class HealthRunResult:
    """Outcome of a health/readiness run."""

    run_id: str
    artifact_path: str
    status: str
    health: ModelHealth
    environment: EnvironmentReport
    readiness_results: list[CapabilityReadiness]
    error: str | None = None


def execute_health_run(ctx: HealthRunContext) -> HealthRunResult:
    """Execute a model health/readiness run through the run spine.

    Uses the run spine's lower-level building blocks directly so that the
    health-specific files (environment report, model health, capability
    readiness, markdown) are written alongside the standard spine artifacts.

    Steps:
        1. Generate run ID + artifact folder via the spine.
        2. Build ModelHealth from the context.
        3. Capture EnvironmentReport.
        4. Evaluate readiness for requested capabilities (or all registered).
        5. Write standard spine artifacts (metadata, input, result, external
           calls, manifest, summary) + health-specific files.
        6. Append start + completion audit entries.
        7. Return HealthRunResult.
    """
    from axiom_core.run_spine import (
        AuditEntry,
        ExternalCallDeclaration,
        RunMetadata,
        append_audit_entry,
        create_run_folder,
        generate_run_id,
        redact_path,
        write_artifact_manifest,
        write_command_input,
        write_execution_result,
        write_external_calls,
        write_run_metadata,
        write_run_summary,
    )

    run_id = generate_run_id("ModelHealth", "diagnose")
    folder = create_run_folder(run_id)
    now_utc = _now_iso()

    import getpass

    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"

    # --- Build health snapshot ---
    health = ModelHealth(
        generated_at_utc=now_utc,
        revit_version=ctx.revit_version,
        model_path=ctx.model_path,
        model_path_redacted=ctx.model_path_redacted or redact_path(ctx.model_path),
        model_last_modified_utc=ctx.model_last_modified_utc,
        active_document_title=ctx.active_document_title,
        active_view_name=ctx.active_view_name,
        active_view_type=ctx.active_view_type,
        worksharing_enabled=ctx.worksharing_enabled,
        linked_model_count=ctx.linked_model_count,
        level_count=ctx.level_count,
        grid_count=ctx.grid_count,
        room_count=ctx.room_count,
        space_count=ctx.space_count,
        warning_count=ctx.warning_count,
        cad_import_count=ctx.cad_import_count,
        cad_link_count=ctx.cad_link_count,
        view_template_count=ctx.view_template_count,
        sheet_count=ctx.sheet_count,
        stale_status=ctx.stale_status,
    )

    # --- Environment snapshot ---
    env_report = capture_environment(
        revit_version=ctx.revit_version,
        revit_connected=ctx.revit_connected,
    )

    # --- Readiness evaluation ---
    if ctx.capabilities is not None:
        readiness_results = [
            evaluate_readiness(cap, health) for cap in ctx.capabilities
        ]
    else:
        readiness_results = evaluate_all_readiness(health)

    # --- Spine metadata ---
    redacted_model_path = health.model_path_redacted
    input_data = {
        "model_path": redacted_model_path,
        "revit_version": ctx.revit_version,
        "active_document_title": ctx.active_document_title,
        "active_view_name": ctx.active_view_name,
        "active_view_type": ctx.active_view_type,
        "capabilities_requested": ctx.capabilities
        if ctx.capabilities is not None
        else list_readiness_capabilities(),
    }
    metadata = RunMetadata(
        run_id=run_id,
        created_at_utc=now_utc,
        capability="ModelHealth",
        mode="diagnose",
        source=ctx.source,
        status="started",
        artifact_path=str(folder),
        revit_version=ctx.revit_version,
        model_path=ctx.model_path,
        active_view=ctx.active_view_name,
        active_view_type=ctx.active_view_type,
    )
    write_run_metadata(folder, metadata)
    write_command_input(folder, input_data)

    # --- Audit entry (started) ---
    _audit_common = dict(
        run_id=run_id,
        source=ctx.source,
        capability="ModelHealth",
        mode="diagnose",
        risk_level="low",
        model_path=ctx.model_path,
        model_path_redacted=redacted_model_path,
        user=user,
        input_summary=_json.dumps(input_data, default=str)[:200],
        artifact_path=str(folder),
    )
    append_audit_entry(AuditEntry(timestamp_utc=now_utc, status="started", external_calls_made=False, **_audit_common))

    # --- Execute health checks ---
    status = "completed"
    error_msg: str | None = None
    result_data: dict[str, Any] = {}

    try:
        # Write health-specific files
        _write_json(folder / "axiom_environment_report.json", env_report.to_dict())
        _write_json(folder / "axiom_model_health.json", health.to_dict())
        _write_json(
            folder / "axiom_capability_readiness.json",
            {
                "generated_at_utc": health.generated_at_utc,
                "capabilities": [r.to_dict() for r in readiness_results],
            },
        )
        md_content = generate_health_markdown(health, readiness_results)
        (folder / "axiom_model_health.md").write_text(md_content, encoding="utf-8")

        result_data = {
            "outcome": "success",
            "mode": "diagnose",
            "capability": "ModelHealth",
            "health_status": health.stale_status,
            "capabilities_assessed": len(readiness_results),
            "note": "Model health and capability readiness report generated.",
        }
    except Exception as exc:
        status = "failed"
        error_msg = str(exc)
        result_data = {}
        from axiom_core.run_spine import write_error_result

        write_error_result(
            folder,
            {
                "error_type": type(exc).__name__,
                "error_message": error_msg,
                "run_id": run_id,
                "capability": "ModelHealth",
                "mode": "diagnose",
                "timestamp_utc": _now_iso(),
            },
        )

    # --- Standard spine artifacts ---
    write_execution_result(folder, result_data)
    ext_calls = ExternalCallDeclaration()
    write_external_calls(folder, ext_calls)
    metadata.status = status
    write_run_metadata(folder, metadata)
    write_run_summary(folder, run_id, metadata, status)
    write_artifact_manifest(folder, run_id)

    # --- Audit entry (final) ---
    append_audit_entry(AuditEntry(timestamp_utc=_now_iso(), status=status, external_calls_made=ext_calls.external_calls_made, **_audit_common))

    return HealthRunResult(
        run_id=run_id,
        artifact_path=str(folder),
        status=status,
        health=health,
        environment=env_report,
        readiness_results=readiness_results,
        error=error_msg,
    )
