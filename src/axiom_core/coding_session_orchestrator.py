"""Coding Session Orchestrator v1 — deterministic session orchestration.

Coordinates work items, implementation plans, patch proposals, validation,
review findings, evidence, and session state without performing autonomous
execution. Establishes the control layer required for future self-improving
engineering loops and Verification Planner architecture.

Non-goals: no autonomous execution, no code modification, no patch
application, no test execution, no PR creation, no scheduling, no
multi-agent coordination, no repair loops, no self-improvement, no
agent invocation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionStage(str, Enum):
    """Ordered stages of a coding session."""

    INITIALIZATION = "initialization"
    IMPLEMENTATION_PLANNING = "implementation_planning"
    PATCH_PROPOSAL = "patch_proposal"
    IMPACT_ANALYSIS = "impact_analysis"
    TEST_SELECTION = "test_selection"
    VALIDATION = "validation"
    REVIEW_POLICY = "review_policy"
    EVIDENCE_COLLECTION = "evidence_collection"
    SESSION_SUMMARY = "session_summary"


class OrchestratorStatus(str, Enum):
    """Status of an orchestration."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CheckpointKind(str, Enum):
    """Deterministic checkpoint types."""

    PATCH_READY = "patch_ready"
    VALIDATION_READY = "validation_ready"
    REVIEW_READY = "review_ready"
    EVIDENCE_COMPLETE = "evidence_complete"
    SESSION_COMPLETE = "session_complete"


class ObservationSeverity(str, Enum):
    """Severity of a session observation."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


# Stage ordering for deterministic progression
_STAGE_ORDER: list[str] = [s.value for s in SessionStage]

_STAGE_INDEX: dict[str, int] = {
    s: i for i, s in enumerate(_STAGE_ORDER)
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionTask:
    """A task within a session stage."""

    task_id: str = ""
    stage: str = "initialization"
    description: str = ""
    status: str = "pending"
    linked_ids: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "description": self.description,
            "status": self.status,
            "linked_ids": list(self.linked_ids),
            "created_at": self.created_at,
        }


@dataclass
class SessionCheckpoint:
    """A deterministic checkpoint in a session."""

    checkpoint_id: str = ""
    kind: str = "session_complete"
    status: str = "pending"
    linked_ids: list[str] = field(default_factory=list)
    evidence_references: list[str] = field(default_factory=list)
    reached_at: str = ""

    def __post_init__(self) -> None:
        if not self.checkpoint_id:
            self.checkpoint_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "kind": self.kind,
            "status": self.status,
            "linked_ids": list(self.linked_ids),
            "evidence_references": list(self.evidence_references),
            "reached_at": self.reached_at,
        }


@dataclass
class SessionObservation:
    """An observation recorded during orchestration."""

    observation_id: str = ""
    severity: str = "info"
    stage: str = ""
    message: str = ""
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.observation_id:
            self.observation_id = str(uuid4())
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "severity": self.severity,
            "stage": self.stage,
            "message": self.message,
            "recorded_at": self.recorded_at,
        }


@dataclass
class SessionTransitionReason:
    """Reason for a stage transition."""

    from_stage: str = ""
    to_stage: str = ""
    reason: str = ""
    transitioned_at: str = ""

    def __post_init__(self) -> None:
        if not self.transitioned_at:
            self.transitioned_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "reason": self.reason,
            "transitioned_at": self.transitioned_at,
        }


@dataclass
class SessionExecutionPlan:
    """The orchestration plan for a coding session."""

    plan_id: str = ""
    session_id: str = ""
    title: str = ""
    status: str = "pending"
    current_stage: str = "initialization"
    completed_stages: list[str] = field(default_factory=list)
    blocked_stages: list[str] = field(default_factory=list)
    tasks: list[SessionTask] = field(default_factory=list)
    checkpoints: list[SessionCheckpoint] = field(default_factory=list)
    observations: list[SessionObservation] = field(default_factory=list)
    transitions: list[SessionTransitionReason] = field(default_factory=list)
    pending_actions: list[str] = field(default_factory=list)
    linked_ids: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status,
            "current_stage": self.current_stage,
            "completed_stages": list(self.completed_stages),
            "blocked_stages": list(self.blocked_stages),
            "tasks": [t.to_dict() for t in self.tasks],
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "observations": [o.to_dict() for o in self.observations],
            "transitions": [t.to_dict() for t in self.transitions],
            "pending_actions": list(self.pending_actions),
            "linked_ids": dict(self.linked_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stage_progress": self._compute_progress(),
        }

    def _compute_progress(self) -> dict[str, Any]:
        total = len(_STAGE_ORDER)
        completed = len(self.completed_stages)
        current_idx = _STAGE_INDEX.get(self.current_stage, 0)
        return {
            "total_stages": total,
            "completed_stages": completed,
            "current_stage_index": current_idx,
            "percentage": round(completed / total * 100) if total else 0,
        }


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


class CodingSessionOrchestrator:
    """Deterministic orchestration of coding sessions.

    Coordinates information flow between engineering stages without
    performing autonomous execution.
    """

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._plans_dir = Path(self._artifacts_root) / "session_orchestrations"
        self._plans_dir.mkdir(parents=True, exist_ok=True)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            msg = f"{name} must not be empty"
            raise ValueError(msg)
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Create orchestration -----------------------------------------------

    def create_orchestration(
        self,
        session_id: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Create a new orchestration plan for a session."""
        self._validate_id_segment(session_id, "session_id")

        plan = SessionExecutionPlan(
            session_id=session_id,
            title=title,
            status=OrchestratorStatus.RUNNING.value,
            current_stage=SessionStage.INITIALIZATION.value,
        )

        # Initialize all stage checkpoints
        checkpoint_map = {
            SessionStage.PATCH_PROPOSAL.value: CheckpointKind.PATCH_READY.value,
            SessionStage.VALIDATION.value: CheckpointKind.VALIDATION_READY.value,
            SessionStage.REVIEW_POLICY.value: CheckpointKind.REVIEW_READY.value,
            SessionStage.EVIDENCE_COLLECTION.value: CheckpointKind.EVIDENCE_COMPLETE.value,
            SessionStage.SESSION_SUMMARY.value: CheckpointKind.SESSION_COMPLETE.value,
        }
        for _stage, kind in checkpoint_map.items():
            plan.checkpoints.append(SessionCheckpoint(kind=kind))

        self._persist_plan(plan)
        return plan.to_dict()

    # -- Get orchestration --------------------------------------------------

    def get_orchestration(self, plan_id: str) -> dict[str, Any] | None:
        """Get an orchestration plan by ID."""
        self._validate_id_segment(plan_id, "plan_id")
        return self._load_plan(plan_id)

    # -- List orchestrations ------------------------------------------------

    def list_orchestrations(
        self,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """List all orchestration plans."""
        plans: list[dict[str, Any]] = []
        if not self._plans_dir.exists():
            return plans

        for entry in sorted(self._plans_dir.iterdir()):
            if not entry.is_dir():
                continue
            plan_file = entry / "orchestration.json"
            if not plan_file.exists():
                continue
            try:
                data = json.loads(plan_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                plans.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read plan %s", entry.name)

        return plans

    # -- Advance stage ------------------------------------------------------

    def advance_stage(
        self,
        plan_id: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        """Advance to the next stage in deterministic order."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        current = plan.get("current_stage", "")
        current_idx = _STAGE_INDEX.get(current, -1)
        if current_idx < 0 or current_idx >= len(_STAGE_ORDER) - 1:
            return plan

        next_stage = _STAGE_ORDER[current_idx + 1]

        # Record transition
        transition = SessionTransitionReason(
            from_stage=current,
            to_stage=next_stage,
            reason=reason or f"Completed {current}",
        )
        plan.setdefault("transitions", []).append(transition.to_dict())

        # Mark current as completed
        completed = plan.setdefault("completed_stages", [])
        if current not in completed:
            completed.append(current)

        plan["current_stage"] = next_stage
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Update checkpoint if applicable
        checkpoint_map = {
            SessionStage.PATCH_PROPOSAL.value: CheckpointKind.PATCH_READY.value,
            SessionStage.VALIDATION.value: CheckpointKind.VALIDATION_READY.value,
            SessionStage.REVIEW_POLICY.value: CheckpointKind.REVIEW_READY.value,
            SessionStage.EVIDENCE_COLLECTION.value: CheckpointKind.EVIDENCE_COMPLETE.value,
        }
        if current in checkpoint_map:
            kind = checkpoint_map[current]
            for cp in plan.get("checkpoints", []):
                if cp.get("kind") == kind and cp.get("status") == "pending":
                    cp["status"] = "reached"
                    cp["reached_at"] = datetime.now(timezone.utc).isoformat()
                    break

        self._write_plan(plan_id, plan)
        return plan

    # -- Block stage --------------------------------------------------------

    def block_stage(
        self,
        plan_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        """Mark the current stage as blocked."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        current = plan.get("current_stage", "")
        blocked = plan.setdefault("blocked_stages", [])
        if current not in blocked:
            blocked.append(current)

        plan["status"] = OrchestratorStatus.BLOCKED.value

        observation = SessionObservation(
            severity=ObservationSeverity.BLOCKER.value,
            stage=current,
            message=reason,
        )
        plan.setdefault("observations", []).append(observation.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._write_plan(plan_id, plan)
        return plan

    # -- Add observation ----------------------------------------------------

    def add_observation(
        self,
        plan_id: str,
        severity: str,
        message: str,
        stage: str = "",
    ) -> dict[str, Any] | None:
        """Record an observation during orchestration."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        observation = SessionObservation(
            severity=severity,
            stage=stage or plan.get("current_stage", ""),
            message=message,
        )
        plan.setdefault("observations", []).append(observation.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._write_plan(plan_id, plan)
        return plan

    # -- Add task -----------------------------------------------------------

    def add_task(
        self,
        plan_id: str,
        description: str,
        stage: str = "",
        linked_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Add a task to the orchestration plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        task = SessionTask(
            stage=stage or plan.get("current_stage", ""),
            description=description,
            linked_ids=linked_ids or [],
        )
        plan.setdefault("tasks", []).append(task.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._write_plan(plan_id, plan)
        return plan

    # -- Link ID ------------------------------------------------------------

    def link_id(
        self,
        plan_id: str,
        key: str,
        value: str,
    ) -> dict[str, Any] | None:
        """Link an external ID to the orchestration."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        plan.setdefault("linked_ids", {})[key] = value
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Complete session ---------------------------------------------------

    def complete_session(
        self,
        plan_id: str,
    ) -> dict[str, Any] | None:
        """Mark the orchestration as completed."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        plan["status"] = OrchestratorStatus.COMPLETED.value
        plan["current_stage"] = SessionStage.SESSION_SUMMARY.value

        # Mark all remaining stages as completed
        completed = plan.setdefault("completed_stages", [])
        for stage in _STAGE_ORDER:
            if stage not in completed:
                completed.append(stage)

        # Mark session_complete checkpoint
        for cp in plan.get("checkpoints", []):
            if cp.get("kind") == CheckpointKind.SESSION_COMPLETE.value:
                cp["status"] = "reached"
                cp["reached_at"] = datetime.now(timezone.utc).isoformat()
                break

        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Generate summary ---------------------------------------------------

    def generate_summary(
        self,
        plan_id: str,
    ) -> dict[str, Any] | None:
        """Generate a session summary from the orchestration plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None

        progress = plan.get("stage_progress", {})
        observations = plan.get("observations", [])
        tasks = plan.get("tasks", [])
        checkpoints = plan.get("checkpoints", [])

        return {
            "plan_id": plan_id,
            "session_id": plan.get("session_id", ""),
            "status": plan.get("status", ""),
            "current_stage": plan.get("current_stage", ""),
            "progress": progress,
            "total_tasks": len(tasks),
            "total_observations": len(observations),
            "checkpoints_reached": sum(
                1 for c in checkpoints if c.get("status") == "reached"
            ),
            "checkpoints_total": len(checkpoints),
            "blocked_stages": plan.get("blocked_stages", []),
            "linked_ids": plan.get("linked_ids", {}),
            "warnings": [
                o for o in observations
                if o.get("severity") in ("warning", "error", "blocker")
            ],
        }

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, plan_id: str) -> str:
        """Write evidence bundle for an orchestration plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            msg = f"Orchestration not found: {plan_id}"
            raise ValueError(msg)

        evidence_dir = self._plans_dir / plan_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "plan_id": plan_id,
            "session_id": plan.get("session_id", ""),
            "status": plan.get("status", ""),
            "current_stage": plan.get("current_stage", ""),
            "created_at": plan.get("created_at", ""),
        }
        (evidence_dir / "orchestration_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "orchestration_result.json").write_text(
            json.dumps(plan, indent=2, default=str),
        )

        progress = plan.get("stage_progress", {})
        summary_lines = [
            "# Coding Session Orchestration Summary\n",
            f"- Plan ID: {plan_id}",
            f"- Session ID: {plan.get('session_id', '')}",
            f"- Status: {plan.get('status', '')}",
            f"- Current stage: {plan.get('current_stage', '')}",
            f"- Progress: {progress.get('percentage', 0)}%",
            f"- Completed stages: {progress.get('completed_stages', 0)}/{progress.get('total_stages', 0)}",
            f"- Tasks: {len(plan.get('tasks', []))}",
            f"- Observations: {len(plan.get('observations', []))}",
        ]
        blocked = plan.get("blocked_stages", [])
        if blocked:
            summary_lines.append("\n## Blocked Stages")
            for b in blocked:
                summary_lines.append(f"- {b}")
        (evidence_dir / "orchestration_summary.md").write_text(
            "\n".join(summary_lines) + "\n",
        )

        pass_fail = {
            "passed": plan.get("status") in (
                OrchestratorStatus.COMPLETED.value,
                OrchestratorStatus.RUNNING.value,
                OrchestratorStatus.PENDING.value,
            ),
            "plan_id": plan_id,
            "status": plan.get("status", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_plan(self, plan: SessionExecutionPlan) -> None:
        plan_dir = self._plans_dir / plan.plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "orchestration.json").write_text(
            json.dumps(plan.to_dict(), indent=2, default=str),
        )

    def _load_plan(self, plan_id: str) -> dict[str, Any] | None:
        plan_path = self._plans_dir / plan_id / "orchestration.json"
        if not plan_path.exists():
            return None
        return json.loads(plan_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_progress(data: dict[str, Any]) -> None:
        """Recalculate stage_progress from current plan state."""
        total = len(_STAGE_ORDER)
        completed = len(data.get("completed_stages", []))
        current_idx = _STAGE_INDEX.get(data.get("current_stage", ""), 0)
        data["stage_progress"] = {
            "total_stages": total,
            "completed_stages": completed,
            "current_stage_index": current_idx,
            "percentage": round(completed / total * 100) if total else 0,
        }

    def _write_plan(
        self, plan_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_progress(data)
        plan_dir = self._plans_dir / plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "orchestration.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
