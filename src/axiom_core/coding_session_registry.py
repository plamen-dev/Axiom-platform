"""Autonomous Coding Session Registry v1 — durable session tracking.

Tracks work item, implementation plan, patch proposal, review findings,
validation runs, evidence, status, blockers, and next actions. Preserves
session steps, artifacts, decisions, and linked IDs.

Non-goals: no autonomous execution, no code modification, no patch
application, no PR creation, no scheduling, no multi-agent execution.
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


class SessionStatus(str, Enum):
    """Status of a coding session."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepKind(str, Enum):
    """Kind of session step."""

    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    REVIEW = "review"
    VALIDATION = "validation"
    EVIDENCE = "evidence"
    DECISION = "decision"


class ArtifactKind(str, Enum):
    """Kind of session artifact."""

    WORK_ITEM = "work_item"
    IMPLEMENTATION_PLAN = "implementation_plan"
    PATCH_PROPOSAL = "patch_proposal"
    PATCH_APPLICATION = "patch_application"
    VALIDATION_RUN = "validation_run"
    REVIEW_FINDING = "review_finding"
    PR_DRAFT = "pr_draft"
    EVIDENCE_BUNDLE = "evidence_bundle"
    TEST_SELECTION = "test_selection"
    POLICY_EVALUATION = "policy_evaluation"


class DecisionKind(str, Enum):
    """Kind of session decision."""

    PROCEED = "proceed"
    BLOCK = "block"
    RETRY = "retry"
    ABORT = "abort"
    ESCALATE = "escalate"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionStep:
    """A step in a coding session."""

    step_id: str = ""
    kind: str = "planning"
    description: str = ""
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    linked_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = str(uuid4())
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "linked_ids": list(self.linked_ids),
        }


@dataclass
class SessionArtifact:
    """An artifact produced or consumed during a session."""

    artifact_id: str = ""
    kind: str = "evidence_bundle"
    reference_id: str = ""
    path: str = ""
    description: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "reference_id": self.reference_id,
            "path": self.path,
            "description": self.description,
            "created_at": self.created_at,
        }


@dataclass
class SessionDecision:
    """A decision made during a session."""

    decision_id: str = ""
    kind: str = "proceed"
    reason: str = ""
    made_at: str = ""
    linked_step_id: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            self.decision_id = str(uuid4())
        if not self.made_at:
            self.made_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind,
            "reason": self.reason,
            "made_at": self.made_at,
            "linked_step_id": self.linked_step_id,
        }


@dataclass
class SessionCostEstimate:
    """Cost estimate for a session."""

    total_steps: int = 0
    completed_steps: int = 0
    blocked_steps: int = 0
    artifacts_produced: int = 0
    decisions_made: int = 0
    estimated_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "blocked_steps": self.blocked_steps,
            "artifacts_produced": self.artifacts_produced,
            "decisions_made": self.decisions_made,
            "estimated_remaining": self.estimated_remaining,
        }


@dataclass
class CodingSession:
    """A durable coding session tracking the full engineering workflow."""

    session_id: str = ""
    status: str = "pending"
    title: str = ""
    description: str = ""
    work_item_id: str = ""
    implementation_plan_id: str = ""
    patch_proposal_id: str = ""
    validation_run_id: str = ""
    pr_draft_id: str = ""
    steps: list[SessionStep] = field(default_factory=list)
    artifacts: list[SessionArtifact] = field(default_factory=list)
    decisions: list[SessionDecision] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "work_item_id": self.work_item_id,
            "implementation_plan_id": self.implementation_plan_id,
            "patch_proposal_id": self.patch_proposal_id,
            "validation_run_id": self.validation_run_id,
            "pr_draft_id": self.pr_draft_id,
            "steps": [s.to_dict() for s in self.steps],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "decisions": [d.to_dict() for d in self.decisions],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cost_estimate": self._compute_cost().to_dict(),
        }

    def _compute_cost(self) -> SessionCostEstimate:
        completed = sum(1 for s in self.steps if s.status == "completed")
        blocked = sum(1 for s in self.steps if s.status == "blocked")
        return SessionCostEstimate(
            total_steps=len(self.steps),
            completed_steps=completed,
            blocked_steps=blocked,
            artifacts_produced=len(self.artifacts),
            decisions_made=len(self.decisions),
            estimated_remaining=len(self.steps) - completed,
        )


# Status transition ordering
_STATUS_RANK: dict[str, int] = {
    SessionStatus.RUNNING.value: 0,
    SessionStatus.BLOCKED.value: 1,
    SessionStatus.PENDING.value: 2,
    SessionStatus.COMPLETED.value: 3,
    SessionStatus.FAILED.value: 4,
    SessionStatus.CANCELLED.value: 5,
}


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class CodingSessionRegistry:
    """Durable registry for autonomous coding sessions."""

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._sessions_dir = Path(self._artifacts_root) / "coding_sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            msg = f"{name} must not be empty"
            raise ValueError(msg)
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Create session -----------------------------------------------------

    def create_session(
        self,
        title: str,
        description: str = "",
        work_item_id: str = "",
    ) -> dict[str, Any]:
        """Create a new coding session."""
        session = CodingSession(
            title=title,
            description=description,
            work_item_id=work_item_id,
        )
        self._persist_session(session)
        return session.to_dict()

    # -- Get session --------------------------------------------------------

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a session by ID."""
        self._validate_id_segment(session_id, "session_id")
        session_path = self._sessions_dir / session_id / "session.json"
        if not session_path.exists():
            return None
        return json.loads(session_path.read_text(encoding="utf-8"))

    # -- List sessions ------------------------------------------------------

    def list_sessions(
        self,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """List all sessions, optionally filtered by status."""
        sessions: list[dict[str, Any]] = []
        if not self._sessions_dir.exists():
            return sessions

        for entry in sorted(self._sessions_dir.iterdir()):
            if not entry.is_dir():
                continue
            session_file = entry / "session.json"
            if not session_file.exists():
                continue
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                sessions.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read session %s", entry.name)

        sessions.sort(
            key=lambda s: (
                _STATUS_RANK.get(s.get("status", ""), 99),
                s.get("created_at", ""),
            ),
        )
        return sessions

    # -- Update status ------------------------------------------------------

    def update_status(
        self,
        session_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update session status."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        session["status"] = status
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Add step -----------------------------------------------------------

    def add_step(
        self,
        session_id: str,
        kind: str,
        description: str,
        linked_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Add a step to a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        step = SessionStep(
            kind=kind,
            description=description,
            linked_ids=linked_ids or [],
        )
        session.setdefault("steps", []).append(step.to_dict())
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Add artifact -------------------------------------------------------

    def add_artifact(
        self,
        session_id: str,
        kind: str,
        reference_id: str = "",
        path: str = "",
        description: str = "",
    ) -> dict[str, Any] | None:
        """Add an artifact to a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        artifact = SessionArtifact(
            kind=kind,
            reference_id=reference_id,
            path=path,
            description=description,
        )
        session.setdefault("artifacts", []).append(artifact.to_dict())
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Add decision -------------------------------------------------------

    def add_decision(
        self,
        session_id: str,
        kind: str,
        reason: str,
        linked_step_id: str = "",
    ) -> dict[str, Any] | None:
        """Add a decision to a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        decision = SessionDecision(
            kind=kind,
            reason=reason,
            linked_step_id=linked_step_id,
        )
        session.setdefault("decisions", []).append(decision.to_dict())
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Set blockers -------------------------------------------------------

    def set_blockers(
        self,
        session_id: str,
        blockers: list[str],
    ) -> dict[str, Any] | None:
        """Set blockers for a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        session["blockers"] = list(blockers)
        if blockers:
            session["status"] = SessionStatus.BLOCKED.value
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Set next actions ---------------------------------------------------

    def set_next_actions(
        self,
        session_id: str,
        next_actions: list[str],
    ) -> dict[str, Any] | None:
        """Set next actions for a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            return None
        session["next_actions"] = list(next_actions)
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Link IDs -----------------------------------------------------------

    def link_id(
        self,
        session_id: str,
        field_name: str,
        linked_id: str,
    ) -> dict[str, Any] | None:
        """Link an ID (work_item_id, patch_proposal_id, etc.) to a session."""
        self._validate_id_segment(session_id, "session_id")
        valid_fields = {
            "work_item_id",
            "implementation_plan_id",
            "patch_proposal_id",
            "validation_run_id",
            "pr_draft_id",
        }
        if field_name not in valid_fields:
            msg = f"Invalid field: {field_name!r}. Must be one of {valid_fields}"
            raise ValueError(msg)
        session = self._load_session(session_id)
        if session is None:
            return None
        session[field_name] = linked_id
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_session(session_id, session)
        return session

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, session_id: str) -> str:
        """Write evidence bundle for a session."""
        self._validate_id_segment(session_id, "session_id")
        session = self._load_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        evidence_dir = self._sessions_dir / session_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "session_id": session_id,
            "title": session.get("title", ""),
            "status": session.get("status", ""),
            "work_item_id": session.get("work_item_id", ""),
            "created_at": session.get("created_at", ""),
        }
        (evidence_dir / "session_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "session_result.json").write_text(
            json.dumps(session, indent=2, default=str),
        )

        cost = session.get("cost_estimate", {})
        summary_lines = [
            "# Coding Session Summary\n",
            f"- Session ID: {session_id}",
            f"- Title: {session.get('title', '')}",
            f"- Status: {session.get('status', '')}",
            f"- Steps: {cost.get('total_steps', 0)} "
            f"({cost.get('completed_steps', 0)} completed)",
            f"- Artifacts: {cost.get('artifacts_produced', 0)}",
            f"- Decisions: {cost.get('decisions_made', 0)}",
        ]
        blockers = session.get("blockers", [])
        if blockers:
            summary_lines.append("\n## Blockers")
            for b in blockers:
                summary_lines.append(f"- {b}")
        (evidence_dir / "session_summary.md").write_text(
            "\n".join(summary_lines) + "\n",
        )

        pass_fail = {
            "passed": session.get("status") in (
                SessionStatus.COMPLETED.value,
                SessionStatus.RUNNING.value,
                SessionStatus.PENDING.value,
            ),
            "session_id": session_id,
            "status": session.get("status", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_session(self, session: CodingSession) -> None:
        session_dir = self._sessions_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps(session.to_dict(), indent=2, default=str),
        )

    def _load_session(self, session_id: str) -> dict[str, Any] | None:
        session_path = self._sessions_dir / session_id / "session.json"
        if not session_path.exists():
            return None
        return json.loads(session_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_cost_estimate(data: dict[str, Any]) -> None:
        """Recalculate cost_estimate from current session state."""
        steps = data.get("steps", [])
        completed = sum(1 for s in steps if s.get("status") == "completed")
        blocked = sum(1 for s in steps if s.get("status") == "blocked")
        data["cost_estimate"] = {
            "total_steps": len(steps),
            "completed_steps": completed,
            "blocked_steps": blocked,
            "artifacts_produced": len(data.get("artifacts", [])),
            "decisions_made": len(data.get("decisions", [])),
            "estimated_remaining": len(steps) - completed,
        }

    def _write_session(
        self, session_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_cost_estimate(data)
        session_dir = self._sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
