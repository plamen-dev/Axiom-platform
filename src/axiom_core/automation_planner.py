"""Axiom Event-Driven Automation Planner and Multi-Runner Strategy.

Accepts project/model/change events, decides which Axiom capabilities may
need to run, classifies execution lane requirements, and generates a
dry-run plan.

This module does NOT automatically mutate models. It detects, plans,
classifies, and recommends.

Artifacts produced per planning run::

    automation_plan.json     — structured plan output
    automation_plan.md       — human-readable summary
    policy_gate.json         — policy decisions for each action
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axiom_core.run_spine import (
    AuditEntry,
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

# ---------------------------------------------------------------------------
# Execution lane classification
# ---------------------------------------------------------------------------

LANE_DESKTOP_REVIT = "desktop_revit"
LANE_APS = "aps"
LANE_NON_REVIT_DATA = "non_revit_data"
LANE_UNKNOWN = "unknown"

VALID_LANES = frozenset({LANE_DESKTOP_REVIT, LANE_APS, LANE_NON_REVIT_DATA, LANE_UNKNOWN})

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES = frozenset({
    "model_updated",
    "project_template_updated",
    "linked_model_updated",
    "ruleset_updated",
    "new_model_registered",
    "revit_version_changed",
})

VALID_EVENT_SOURCES = frozenset({"manual", "file_watcher", "future_acc", "future_mcp", "test"})

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AutomationEvent:
    """An event that may trigger automation planning."""

    event_id: str
    event_type: str
    timestamp_utc: str = ""
    project_id: str = ""
    model_path: str = ""
    changed_fields: list[str] = field(default_factory=list)
    source: str = "manual"

    def __post_init__(self) -> None:
        if not self.timestamp_utc:
            self.timestamp_utc = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp_utc": self.timestamp_utc,
            "project_id": self.project_id,
            "model_path": self.model_path,
            "changed_fields": self.changed_fields,
            "source": self.source,
        }

    def validate(self) -> list[str]:
        """Return validation errors, if any."""
        errors: list[str] = []
        if not self.event_id:
            errors.append("event_id is required")
        if not self.event_type:
            errors.append("event_type is required")
        if self.event_type and self.event_type not in VALID_EVENT_TYPES:
            errors.append(
                f"event_type '{self.event_type}' not in {sorted(VALID_EVENT_TYPES)}"
            )
        if self.source and self.source not in VALID_EVENT_SOURCES:
            errors.append(
                f"source '{self.source}' not in {sorted(VALID_EVENT_SOURCES)}"
            )
        return errors


@dataclass
class RecommendedAction:
    """One recommended action from the planner."""

    capability_id: str
    reason: str
    recommended_mode: str = "dry_run"  # health_check | dry_run | execute
    execution_lane: str = LANE_UNKNOWN
    approval_required: bool = True
    risk_level: str = "low"  # low | medium | high
    blocking_conditions: list[str] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "reason": self.reason,
            "recommended_mode": self.recommended_mode,
            "execution_lane": self.execution_lane,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "blocking_conditions": self.blocking_conditions,
            "next_step": self.next_step,
        }


@dataclass
class PolicyGateDecision:
    """Policy gate output for one action."""

    capability_id: str
    auto_execute_allowed: bool = False
    reason: str = ""
    dry_run_recommended: bool = True
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "auto_execute_allowed": self.auto_execute_allowed,
            "reason": self.reason,
            "dry_run_recommended": self.dry_run_recommended,
            "approval_required": self.approval_required,
        }


@dataclass
class AutomationPlan:
    """Full planner output for an event."""

    event_id: str
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    policy_decisions: list[PolicyGateDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "recommended_actions": [a.to_dict() for a in self.recommended_actions],
            "policy_decisions": [p.to_dict() for p in self.policy_decisions],
        }


# ---------------------------------------------------------------------------
# Execution lane classifier
# ---------------------------------------------------------------------------


def classify_execution_lane(capability_id: str, mode: str = "dry_run") -> str:
    """Classify which execution lane a capability/mode requires.

    Rules:
    - Model health from prior extracted data → non_revit_data
    - Report generation from artifacts → non_revit_data
    - Any model mutation or live Revit interaction → desktop_revit
    - Health check on active model → desktop_revit
    - Unknown → unknown
    """
    cap_lower = capability_id.lower()

    # Non-Revit data tasks
    if mode == "health_check" and cap_lower == "model_health_report":
        return LANE_NON_REVIT_DATA
    if cap_lower in ("report_generation", "artifact_query"):
        return LANE_NON_REVIT_DATA

    # Desktop Revit tasks (all modes require active Revit instance)
    if cap_lower in ("grid_creation", "level_creation", "model_health"):
        return LANE_DESKTOP_REVIT

    # Project setup / mutation always desktop
    if cap_lower in ("project_setup", "set_parameter_value"):
        return LANE_DESKTOP_REVIT

    return LANE_UNKNOWN


# ---------------------------------------------------------------------------
# Impact rules (event_type → capabilities that should respond)
# ---------------------------------------------------------------------------

_IMPACT_RULES: dict[str, list[dict[str, Any]]] = {
    "model_updated": [
        {
            "capability_id": "model_health",
            "reason": "Model updated — re-evaluate health and readiness.",
            "recommended_mode": "health_check",
            "risk_level": "low",
        },
    ],
    "project_template_updated": [
        {
            "capability_id": "model_health",
            "reason": "Project template changed — verify model health baseline.",
            "recommended_mode": "health_check",
            "risk_level": "low",
        },
    ],
    "linked_model_updated": [
        {
            "capability_id": "model_health",
            "reason": "Linked model updated — check for broken references.",
            "recommended_mode": "health_check",
            "risk_level": "low",
        },
    ],
    "ruleset_updated": [
        {
            "capability_id": "model_health",
            "reason": "Ruleset changed — re-evaluate capability readiness.",
            "recommended_mode": "health_check",
            "risk_level": "low",
        },
        {
            "capability_id": "grid_creation",
            "reason": "Ruleset changed — verify GridCreation readiness classification.",
            "recommended_mode": "dry_run",
            "risk_level": "medium",
        },
    ],
    "new_model_registered": [
        {
            "capability_id": "model_health",
            "reason": "New model registered — initial health assessment required.",
            "recommended_mode": "health_check",
            "risk_level": "low",
        },
    ],
    "revit_version_changed": [
        {
            "capability_id": "model_health",
            "reason": "Revit version changed — verify compatibility.",
            "recommended_mode": "health_check",
            "risk_level": "medium",
        },
        {
            "capability_id": "grid_creation",
            "reason": "Revit version changed — verify capability still functions.",
            "recommended_mode": "dry_run",
            "risk_level": "medium",
        },
    ],
}


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------


def apply_policy_gate(action: RecommendedAction) -> PolicyGateDecision:
    """Apply the default policy gate to a recommended action.

    Rules:
    - No high-risk action auto-executes.
    - No execute mode auto-executes.
    - Medium-risk requires approval.
    - Low-risk health_check may auto-execute (but still recommends dry-run first).
    """
    if action.risk_level == "high":
        return PolicyGateDecision(
            capability_id=action.capability_id,
            auto_execute_allowed=False,
            reason="High-risk actions never auto-execute.",
            dry_run_recommended=True,
            approval_required=True,
        )

    if action.recommended_mode == "execute":
        return PolicyGateDecision(
            capability_id=action.capability_id,
            auto_execute_allowed=False,
            reason="Execute mode requires explicit approval.",
            dry_run_recommended=True,
            approval_required=True,
        )

    if action.risk_level == "medium":
        return PolicyGateDecision(
            capability_id=action.capability_id,
            auto_execute_allowed=False,
            reason="Medium-risk actions require approval.",
            dry_run_recommended=True,
            approval_required=True,
        )

    # Low-risk, non-execute (health_check or dry_run)
    return PolicyGateDecision(
        capability_id=action.capability_id,
        auto_execute_allowed=False,
        reason="Default policy: no auto-execution without explicit approval.",
        dry_run_recommended=True,
        approval_required=True,
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def plan_for_event(event: AutomationEvent) -> AutomationPlan:
    """Generate an automation plan for a given event.

    Looks up impact rules for the event type, classifies execution lanes,
    applies policy gates, and returns a structured plan.
    """
    actions: list[RecommendedAction] = []
    policies: list[PolicyGateDecision] = []

    rules = _IMPACT_RULES.get(event.event_type, [])

    for rule in rules:
        cap_id = rule["capability_id"]
        mode = rule["recommended_mode"]
        lane = classify_execution_lane(cap_id, mode)

        action = RecommendedAction(
            capability_id=cap_id,
            reason=rule["reason"],
            recommended_mode=mode,
            execution_lane=lane,
            risk_level=rule["risk_level"],
            approval_required=True,
            next_step=f"Run {mode} for {cap_id}" if mode != "execute" else f"Await approval to execute {cap_id}",
        )
        actions.append(action)
        policies.append(apply_policy_gate(action))

    return AutomationPlan(
        event_id=event.event_id,
        recommended_actions=actions,
        policy_decisions=policies,
    )


# ---------------------------------------------------------------------------
# Spine-integrated execution
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    # Local helper to avoid circular dependency.
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def execute_plan_run(event: AutomationEvent) -> dict[str, Any]:
    """Execute a planning run through the run spine.

    1. Validate the event.
    2. Generate a plan.
    3. Write plan artifacts to a spine-managed run folder.
    4. Append audit entries (started/completed).
    5. Return the plan result.
    """
    import getpass

    from axiom_core.dialog_watcher import write_default_dialog_artifacts
    from axiom_core.run_spine import ExternalCallDeclaration

    # --- Validate ---
    errors = event.validate()
    if errors:
        return {
            "error": True,
            "error_type": "EventValidationError",
            "errors": errors,
        }

    # --- Plan ---
    plan = plan_for_event(event)

    # --- Spine setup ---
    run_id = generate_run_id("AutomationPlanner", "plan")
    folder = create_run_folder(run_id)
    now_utc = _now_iso()

    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"

    metadata = RunMetadata(
        run_id=run_id,
        created_at_utc=now_utc,
        capability="AutomationPlanner",
        mode="plan",
        source=event.source,
        status="started",
        artifact_path=str(folder),
        model_path=event.model_path or None,
    )
    write_run_metadata(folder, metadata)

    event_dict = event.to_dict()
    if event.model_path:
        event_dict["model_path"] = redact_path(event.model_path)
    input_data = {
        "event": event_dict,
        "model_path": redact_path(event.model_path) if event.model_path else None,
    }
    write_command_input(folder, input_data)

    # --- Audit entry (started) ---
    _audit_common = dict(
        run_id=run_id,
        source=event.source,
        capability="AutomationPlanner",
        mode="plan",
        risk_level="low",
        model_path=event.model_path or None,
        model_path_redacted=redact_path(event.model_path) if event.model_path else None,
        user=user,
        input_summary=json.dumps(input_data, default=str)[:200],
        artifact_path=str(folder),
    )
    append_audit_entry(
        AuditEntry(timestamp_utc=now_utc, status="started", external_calls_made=False, **_audit_common)
    )

    # --- Write plan artifacts ---
    _write_json(folder / "automation_plan.json", plan.to_dict())
    _write_json(folder / "policy_gate.json", {
        "event_id": event.event_id,
        "decisions": [p.to_dict() for p in plan.policy_decisions],
    })

    # Markdown summary
    md_lines = [
        f"# Automation Plan: {event.event_id}",
        "",
        f"- **Event type:** {event.event_type}",
        f"- **Source:** {event.source}",
        f"- **Timestamp:** {event.timestamp_utc}",
    ]
    if event.model_path:
        md_lines.append(f"- **Model:** {redact_path(event.model_path)}")
    if event.project_id:
        md_lines.append(f"- **Project:** {event.project_id}")
    md_lines.append("")
    md_lines.append(f"## Recommended Actions ({len(plan.recommended_actions)})")
    md_lines.append("")
    for i, action in enumerate(plan.recommended_actions, 1):
        md_lines.append(f"### {i}. {action.capability_id}")
        md_lines.append(f"- **Reason:** {action.reason}")
        md_lines.append(f"- **Mode:** {action.recommended_mode}")
        md_lines.append(f"- **Lane:** {action.execution_lane}")
        md_lines.append(f"- **Risk:** {action.risk_level}")
        md_lines.append(f"- **Approval required:** {action.approval_required}")
        md_lines.append(f"- **Next step:** {action.next_step}")
        md_lines.append("")

    md_lines.append("## Policy Gate")
    md_lines.append("")
    for decision in plan.policy_decisions:
        md_lines.append(f"- **{decision.capability_id}**: {decision.reason}")
    md_lines.append("")

    (folder / "automation_plan.md").write_text("\n".join(md_lines), encoding="utf-8")

    # --- Standard spine artifacts ---
    result_data = {
        "outcome": "success",
        "mode": "plan",
        "capability": "AutomationPlanner",
        "actions_recommended": len(plan.recommended_actions),
        "note": "Event-driven automation plan generated.",
    }
    write_execution_result(folder, result_data)
    ext_calls = ExternalCallDeclaration()
    write_external_calls(folder, ext_calls)
    write_default_dialog_artifacts(folder, run_id)

    metadata.status = "completed"
    write_run_metadata(folder, metadata)
    write_run_summary(folder, run_id, metadata, "completed")
    write_artifact_manifest(folder, run_id)

    # --- Audit entry (completed) ---
    append_audit_entry(
        AuditEntry(timestamp_utc=_now_iso(), status="completed", external_calls_made=False, **_audit_common)
    )

    return {
        "error": False,
        "run_id": run_id,
        "artifact_path": str(folder),
        "plan": plan.to_dict(),
    }
