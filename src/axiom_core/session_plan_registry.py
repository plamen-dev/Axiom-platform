"""Session Plan Registry v1 — durable planning artifacts.

Creates explicit planning artifacts for engineering sessions. Separates
planning from execution by producing ordered steps, assumptions,
constraints, dependencies, and rationale as durable evidence.

Consumes: Work Item Registry, Implementation Plans, Review Findings.

Non-goals: no execution, no file mutation, no network dependency,
no question tracking, no assertions, no reports.
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


class PlanStatus(str, Enum):
    """Status of a session plan."""

    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Status of a plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class StepCategory(str, Enum):
    """Category of a plan step."""

    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    REVIEW = "review"
    VALIDATION = "validation"
    EVIDENCE = "evidence"
    DOCUMENTATION = "documentation"


class GoalPriority(str, Enum):
    """Priority of a session goal."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Priority ranking for deterministic sorting
_PRIORITY_RANK: dict[str, int] = {
    GoalPriority.CRITICAL.value: 0,
    GoalPriority.HIGH.value: 1,
    GoalPriority.MEDIUM.value: 2,
    GoalPriority.LOW.value: 3,
}

# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    PlanStatus.ACTIVE.value: 0,
    PlanStatus.DRAFT.value: 1,
    PlanStatus.COMPLETED.value: 2,
    PlanStatus.SUPERSEDED.value: 3,
    PlanStatus.CANCELLED.value: 4,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionGoal:
    """A goal for a session plan."""

    goal_id: str = ""
    description: str = ""
    priority: str = "medium"
    linked_work_item_id: str = ""

    def __post_init__(self) -> None:
        if not self.goal_id:
            self.goal_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "priority": self.priority,
            "linked_work_item_id": self.linked_work_item_id,
        }


@dataclass
class SessionAssumption:
    """An assumption underlying a session plan."""

    assumption_id: str = ""
    description: str = ""
    verified: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if not self.assumption_id:
            self.assumption_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "description": self.description,
            "verified": self.verified,
            "source": self.source,
        }


@dataclass
class SessionConstraint:
    """A constraint on a session plan."""

    constraint_id: str = ""
    description: str = ""
    category: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not self.constraint_id:
            self.constraint_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "description": self.description,
            "category": self.category,
            "source": self.source,
        }


@dataclass
class SessionPlanStep:
    """A step in a session plan."""

    step_id: str = ""
    order: int = 0
    category: str = "implementation"
    description: str = ""
    rationale: str = ""
    status: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    linked_ids: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "order": self.order,
            "category": self.category,
            "description": self.description,
            "rationale": self.rationale,
            "status": self.status,
            "dependencies": list(self.dependencies),
            "linked_ids": list(self.linked_ids),
            "created_at": self.created_at,
        }


@dataclass
class SessionPlan:
    """A durable session plan artifact."""

    plan_id: str = ""
    title: str = ""
    status: str = "draft"
    session_id: str = ""
    work_item_id: str = ""
    implementation_plan_id: str = ""
    goals: list[SessionGoal] = field(default_factory=list)
    assumptions: list[SessionAssumption] = field(default_factory=list)
    constraints: list[SessionConstraint] = field(default_factory=list)
    steps: list[SessionPlanStep] = field(default_factory=list)
    rationale: str = ""
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
            "title": self.title,
            "status": self.status,
            "session_id": self.session_id,
            "work_item_id": self.work_item_id,
            "implementation_plan_id": self.implementation_plan_id,
            "goals": [g.to_dict() for g in self.goals],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "constraints": [c.to_dict() for c in self.constraints],
            "steps": [s.to_dict() for s in self.steps],
            "rationale": self.rationale,
            "step_summary": self._step_summary(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _step_summary(self) -> dict[str, int]:
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == "completed")
        pending = sum(1 for s in self.steps if s.status == "pending")
        blocked = sum(1 for s in self.steps if s.status == "blocked")
        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "blocked": blocked,
            "remaining": total - completed,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionPlanRegistry:
    """Durable registry for session planning artifacts."""

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._plans_dir = Path(self._artifacts_root) / "session_plans"
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

    # -- Create plan --------------------------------------------------------

    def create_plan(
        self,
        title: str,
        session_id: str = "",
        work_item_id: str = "",
        implementation_plan_id: str = "",
        rationale: str = "",
        goals: list[dict[str, Any]] | None = None,
        assumptions: list[dict[str, Any]] | None = None,
        constraints: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new session plan."""
        plan_goals = [
            SessionGoal(
                description=g.get("description", ""),
                priority=g.get("priority", "medium"),
                linked_work_item_id=g.get("linked_work_item_id", ""),
            )
            for g in (goals or [])
        ]
        plan_assumptions = [
            SessionAssumption(
                description=a.get("description", ""),
                verified=a.get("verified", False),
                source=a.get("source", ""),
            )
            for a in (assumptions or [])
        ]
        plan_constraints = [
            SessionConstraint(
                description=c.get("description", ""),
                category=c.get("category", ""),
                source=c.get("source", ""),
            )
            for c in (constraints or [])
        ]
        plan_steps = [
            SessionPlanStep(
                order=i + 1,
                category=s.get("category", "implementation"),
                description=s.get("description", ""),
                rationale=s.get("rationale", ""),
                dependencies=s.get("dependencies", []),
                linked_ids=s.get("linked_ids", []),
            )
            for i, s in enumerate(steps or [])
        ]

        plan = SessionPlan(
            title=title,
            session_id=session_id,
            work_item_id=work_item_id,
            implementation_plan_id=implementation_plan_id,
            rationale=rationale,
            goals=plan_goals,
            assumptions=plan_assumptions,
            constraints=plan_constraints,
            steps=plan_steps,
        )
        self._persist_plan(plan)
        return plan.to_dict()

    # -- Get plan -----------------------------------------------------------

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Get a plan by ID."""
        self._validate_id_segment(plan_id, "plan_id")
        return self._load_plan(plan_id)

    # -- List plans ---------------------------------------------------------

    def list_plans(
        self,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """List all plans, optionally filtered by status."""
        plans: list[dict[str, Any]] = []
        if not self._plans_dir.exists():
            return plans

        for entry in sorted(self._plans_dir.iterdir()):
            if not entry.is_dir():
                continue
            plan_file = entry / "plan.json"
            if not plan_file.exists():
                continue
            try:
                data = json.loads(plan_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                plans.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read plan %s", entry.name)

        plans.sort(
            key=lambda p: (
                _STATUS_RANK.get(p.get("status", ""), 99),
                p.get("created_at", ""),
            ),
        )
        return plans

    # -- Update status ------------------------------------------------------

    _VALID_STATUSES = frozenset(s.value for s in PlanStatus)

    def update_status(
        self,
        plan_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update plan status."""
        self._validate_id_segment(plan_id, "plan_id")
        if status not in self._VALID_STATUSES:
            msg = f"Invalid status {status!r}, expected one of {sorted(self._VALID_STATUSES)}"
            raise ValueError(msg)
        plan = self._load_plan(plan_id)
        if plan is None:
            return None
        plan["status"] = status
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Add step -----------------------------------------------------------

    def add_step(
        self,
        plan_id: str,
        category: str = "implementation",
        description: str = "",
        rationale: str = "",
        dependencies: list[str] | None = None,
        linked_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Add a step to a plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None
        existing_steps = plan.get("steps", [])
        max_order = max((s.get("order", 0) for s in existing_steps), default=0)
        step = SessionPlanStep(
            order=max_order + 1,
            category=category,
            description=description,
            rationale=rationale,
            dependencies=dependencies or [],
            linked_ids=linked_ids or [],
        )
        existing_steps.append(step.to_dict())
        plan["steps"] = existing_steps
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Add goal -----------------------------------------------------------

    def add_goal(
        self,
        plan_id: str,
        description: str,
        priority: str = "medium",
        linked_work_item_id: str = "",
    ) -> dict[str, Any] | None:
        """Add a goal to a plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None
        goal = SessionGoal(
            description=description,
            priority=priority,
            linked_work_item_id=linked_work_item_id,
        )
        plan.setdefault("goals", []).append(goal.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Add assumption -----------------------------------------------------

    def add_assumption(
        self,
        plan_id: str,
        description: str,
        verified: bool = False,
        source: str = "",
    ) -> dict[str, Any] | None:
        """Add an assumption to a plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None
        assumption = SessionAssumption(
            description=description,
            verified=verified,
            source=source,
        )
        plan.setdefault("assumptions", []).append(assumption.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Add constraint -----------------------------------------------------

    def add_constraint(
        self,
        plan_id: str,
        description: str,
        category: str = "",
        source: str = "",
    ) -> dict[str, Any] | None:
        """Add a constraint to a plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            return None
        constraint = SessionConstraint(
            description=description,
            category=category,
            source=source,
        )
        plan.setdefault("constraints", []).append(constraint.to_dict())
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_plan(plan_id, plan)
        return plan

    # -- Export plan ---------------------------------------------------------

    def export_plan(self, plan_id: str) -> str:
        """Export plan as markdown."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            msg = f"Plan not found: {plan_id}"
            raise ValueError(msg)

        lines = [
            f"# Session Plan: {plan.get('title', '')}\n",
            f"- Plan ID: {plan_id}",
            f"- Status: {plan.get('status', '')}",
            f"- Session ID: {plan.get('session_id', '')}",
            f"- Work Item ID: {plan.get('work_item_id', '')}",
            f"- Created: {plan.get('created_at', '')}",
        ]

        if plan.get("rationale"):
            lines.append(f"\n## Rationale\n\n{plan['rationale']}")

        goals = plan.get("goals", [])
        if goals:
            lines.append("\n## Goals\n")
            for g in sorted(
                goals,
                key=lambda x: _PRIORITY_RANK.get(
                    x.get("priority", "medium"), 99,
                ),
            ):
                lines.append(
                    f"- [{g.get('priority', 'medium')}] {g.get('description', '')}",
                )

        assumptions = plan.get("assumptions", [])
        if assumptions:
            lines.append("\n## Assumptions\n")
            for a in assumptions:
                verified = "verified" if a.get("verified") else "unverified"
                lines.append(f"- [{verified}] {a.get('description', '')}")

        constraints = plan.get("constraints", [])
        if constraints:
            lines.append("\n## Constraints\n")
            for c in constraints:
                cat = f"[{c['category']}] " if c.get("category") else ""
                lines.append(f"- {cat}{c.get('description', '')}")

        steps = plan.get("steps", [])
        if steps:
            lines.append("\n## Steps\n")
            for s in sorted(steps, key=lambda x: x.get("order", 0)):
                deps = ""
                if s.get("dependencies"):
                    deps = f" (depends: {', '.join(s['dependencies'])})"
                lines.append(
                    f"{s.get('order', 0)}. [{s.get('category', '')}] "
                    f"{s.get('description', '')}{deps}",
                )
                if s.get("rationale"):
                    lines.append(f"   Rationale: {s['rationale']}")

        return "\n".join(lines) + "\n"

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, plan_id: str) -> str:
        """Write evidence bundle for a plan."""
        self._validate_id_segment(plan_id, "plan_id")
        plan = self._load_plan(plan_id)
        if plan is None:
            msg = f"Plan not found: {plan_id}"
            raise ValueError(msg)

        evidence_dir = self._plans_dir / plan_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "plan_id": plan_id,
            "title": plan.get("title", ""),
            "status": plan.get("status", ""),
            "session_id": plan.get("session_id", ""),
            "work_item_id": plan.get("work_item_id", ""),
            "created_at": plan.get("created_at", ""),
        }
        (evidence_dir / "session_plan_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "session_plan_result.json").write_text(
            json.dumps(plan, indent=2, default=str),
        )

        (evidence_dir / "session_plan.md").write_text(
            self.export_plan(plan_id),
        )

        summary = plan.get("step_summary", {})
        pass_fail = {
            "passed": plan.get("status") in (
                PlanStatus.DRAFT.value,
                PlanStatus.ACTIVE.value,
                PlanStatus.COMPLETED.value,
            ),
            "plan_id": plan_id,
            "status": plan.get("status", ""),
            "total_steps": summary.get("total", 0),
            "completed_steps": summary.get("completed", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_plan(self, plan: SessionPlan) -> None:
        plan_dir = self._plans_dir / plan.plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "plan.json").write_text(
            json.dumps(plan.to_dict(), indent=2, default=str),
        )

    def _load_plan(self, plan_id: str) -> dict[str, Any] | None:
        plan_path = self._plans_dir / plan_id / "plan.json"
        if not plan_path.exists():
            return None
        return json.loads(plan_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_step_summary(data: dict[str, Any]) -> None:
        """Recalculate step_summary from current plan state."""
        steps = data.get("steps", [])
        completed = sum(1 for s in steps if s.get("status") == "completed")
        pending = sum(1 for s in steps if s.get("status") == "pending")
        blocked = sum(1 for s in steps if s.get("status") == "blocked")
        data["step_summary"] = {
            "total": len(steps),
            "completed": completed,
            "pending": pending,
            "blocked": blocked,
            "remaining": len(steps) - completed,
        }

    def _write_plan(
        self, plan_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_step_summary(data)
        plan_dir = self._plans_dir / plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "plan.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
