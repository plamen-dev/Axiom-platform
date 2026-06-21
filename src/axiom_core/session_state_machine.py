"""Session State Machine v1 — durable session lifecycle tracking.

Session states are first-class lifecycle markers that record the current
stage of an autonomous coding session without executing actions, approving
work, or changing workflow behavior automatically.

Non-goals: no automatic workflow execution, no automatic routing, no patch
application, no approvals, no architecture changes, no workflow engine
implementation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionStateValue(str, Enum):
    """Possible session states."""

    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    REPAIRING = "repairing"
    REVIEWING = "reviewing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class TransitionReason(str, Enum):
    """Reason for a state transition."""

    INITIALIZED = "initialized"
    PLAN_CREATED = "plan_created"
    EXECUTION_STARTED = "execution_started"
    VALIDATION_STARTED = "validation_started"
    REPAIR_REQUIRED = "repair_required"
    REVIEW_STARTED = "review_started"
    REPORT_CREATED = "report_created"
    COMPLETED_SUCCESSFULLY = "completed_successfully"
    FAILED_VALIDATION = "failed_validation"
    FAILED_REVIEW = "failed_review"
    FAILED_EXECUTION = "failed_execution"
    OTHER = "other"


class SessionStateSource(str, Enum):
    """Source that triggered the state change."""

    SESSION_REPORT = "session_report"
    ESCALATION = "escalation"
    REPAIR_PROPOSAL = "repair_proposal"
    REPAIR_DECISION = "repair_decision"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    REVIEW_FINDING = "review_finding"
    MANUAL = "manual"
    OTHER = "other"


# State ranking for deterministic sorting
_STATE_RANK: dict[str, int] = {
    SessionStateValue.CREATED.value: 0,
    SessionStateValue.PLANNING.value: 1,
    SessionStateValue.EXECUTING.value: 2,
    SessionStateValue.VALIDATING.value: 3,
    SessionStateValue.REPAIRING.value: 4,
    SessionStateValue.REVIEWING.value: 5,
    SessionStateValue.REPORTING.value: 6,
    SessionStateValue.COMPLETED.value: 7,
    SessionStateValue.FAILED.value: 8,
}

# Valid transitions: from_state -> set of allowed to_states
_VALID_TRANSITIONS: dict[str, set[str]] = {
    SessionStateValue.CREATED.value: {
        SessionStateValue.PLANNING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.PLANNING.value: {
        SessionStateValue.EXECUTING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.EXECUTING.value: {
        SessionStateValue.VALIDATING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.VALIDATING.value: {
        SessionStateValue.REPAIRING.value,
        SessionStateValue.REVIEWING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.REPAIRING.value: {
        SessionStateValue.VALIDATING.value,
        SessionStateValue.REVIEWING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.REVIEWING.value: {
        SessionStateValue.REPORTING.value,
        SessionStateValue.REPAIRING.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.REPORTING.value: {
        SessionStateValue.COMPLETED.value,
        SessionStateValue.FAILED.value,
    },
    SessionStateValue.COMPLETED.value: set(),
    SessionStateValue.FAILED.value: set(),
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """A durable session state artifact."""

    state_id: str = ""
    session_id: str = ""
    current_state: str = "created"
    previous_state: str = ""
    reason: str = "initialized"
    source: str = "other"
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.state_id:
            self.state_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "session_id": self.session_id,
            "current_state": self.current_state,
            "previous_state": self.previous_state,
            "reason": self.reason,
            "source": self.source,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class SessionStateTransition:
    """A durable state transition record."""

    transition_id: str = ""
    session_id: str = ""
    from_state: str = ""
    to_state: str = ""
    reason: str = "other"
    source: str = "other"
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.transition_id:
            self.transition_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "session_id": self.session_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "source": self.source,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionStateMachineRegistry:
    """Durable registry for session state artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._states_dir = self._artifacts_root / "session_states"
        self._states_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_state_path(self, state_id: str) -> Path:
        """Resolve and validate the state directory stays inside the sandbox."""
        target = (self._states_dir / state_id).resolve()
        sandbox = self._states_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {state_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_state(
        self,
        session_id: str,
        current_state: str = "",
        reason: str = "",
        source: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        """Create a new session state."""
        if current_state:
            valid_states = {s.value for s in SessionStateValue}
            if current_state not in valid_states:
                raise ValueError(
                    f"Invalid current_state: {current_state!r}. "
                    f"Must be one of: {sorted(valid_states)}"
                )
        if reason:
            valid_reasons = {r.value for r in TransitionReason}
            if reason not in valid_reasons:
                raise ValueError(
                    f"Invalid reason: {reason!r}. "
                    f"Must be one of: {sorted(valid_reasons)}"
                )
        if source:
            valid_sources = {s.value for s in SessionStateSource}
            if source not in valid_sources:
                raise ValueError(
                    f"Invalid source: {source!r}. "
                    f"Must be one of: {sorted(valid_sources)}"
                )

        state = SessionState(
            session_id=session_id,
            current_state=current_state or SessionStateValue.CREATED.value,
            reason=reason or TransitionReason.INITIALIZED.value,
            source=source or SessionStateSource.OTHER.value,
            rationale=rationale,
        )
        self._persist_state(state)
        return state.to_dict()

    def get_state(self, state_id: str) -> dict[str, Any] | None:
        """Get a session state by ID."""
        self._validate_id_segment(state_id, "state_id")
        return self._load_state(state_id)

    def list_states(
        self,
        session_id: str = "",
        current_state: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        """List all session states with optional filters."""
        states: list[dict[str, Any]] = []
        if not self._states_dir.exists():
            return states

        sandbox = self._states_dir.resolve()
        for entry in self._states_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            state_file = entry / "state.json"
            if not state_file.exists():
                continue
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if session_id and data.get("session_id") != session_id:
                    continue
                if current_state and data.get("current_state") != current_state:
                    continue
                if source and data.get("source") != source:
                    continue
                states.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: state rank → created_at
        states.sort(
            key=lambda s: (
                _STATE_RANK.get(s.get("current_state", ""), 99),
                s.get("created_at", ""),
            )
        )
        return states

    def transition_state(
        self,
        state_id: str,
        to_state: str,
        reason: str = "",
        source: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        """Create a state transition."""
        self._validate_id_segment(state_id, "state_id")

        valid_states = {s.value for s in SessionStateValue}
        if to_state not in valid_states:
            raise ValueError(
                f"Invalid to_state: {to_state!r}. "
                f"Must be one of: {sorted(valid_states)}"
            )
        if reason:
            valid_reasons = {r.value for r in TransitionReason}
            if reason not in valid_reasons:
                raise ValueError(
                    f"Invalid reason: {reason!r}. "
                    f"Must be one of: {sorted(valid_reasons)}"
                )
        if source:
            valid_sources = {s.value for s in SessionStateSource}
            if source not in valid_sources:
                raise ValueError(
                    f"Invalid source: {source!r}. "
                    f"Must be one of: {sorted(valid_sources)}"
                )

        current = self._load_state(state_id)
        if current is None:
            raise ValueError(f"Session state not found: {state_id}")

        from_state = current["current_state"]
        allowed = _VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Invalid transition from {from_state!r} to {to_state!r}. "
                f"Allowed: {sorted(allowed)}"
            )

        transition = SessionStateTransition(
            session_id=current["session_id"],
            from_state=from_state,
            to_state=to_state,
            reason=reason or TransitionReason.OTHER.value,
            source=source or SessionStateSource.OTHER.value,
            rationale=rationale,
        )

        # Update state
        current["previous_state"] = from_state
        current["current_state"] = to_state
        current["reason"] = transition.reason
        current["source"] = transition.source
        current["rationale"] = rationale

        state_dir = self._safe_state_path(state_id)
        (state_dir / "state.json").write_text(
            json.dumps(current, indent=2, default=str),
            encoding="utf-8",
        )

        # Persist transition
        self._persist_transition(state_id, transition)

        return transition.to_dict()

    def export_state(self, state_id: str) -> str:
        """Export a session state as markdown."""
        self._validate_id_segment(state_id, "state_id")
        data = self._load_state(state_id)
        if data is None:
            raise ValueError(f"Session state not found: {state_id}")

        lines: list[str] = []
        lines.append(f"# Session State: {data['current_state'].upper()}")
        lines.append("")
        lines.append(f"- State ID: {data['state_id']}")
        lines.append(f"- Session ID: {data['session_id']}")
        lines.append(f"- Current State: {data['current_state']}")
        if data.get("previous_state"):
            lines.append(f"- Previous State: {data['previous_state']}")
        lines.append(f"- Reason: {data['reason']}")
        lines.append(f"- Source: {data['source']}")
        lines.append(f"- Created: {data['created_at']}")
        lines.append("")

        if data.get("rationale"):
            lines.append("## Rationale")
            lines.append("")
            lines.append(data["rationale"])
            lines.append("")

        # Include transitions if any
        transitions = self._load_transitions(state_id)
        if transitions:
            lines.append("## Transitions")
            lines.append("")
            for t in transitions:
                lines.append(
                    f"- {t['from_state']} → {t['to_state']} "
                    f"({t['reason']}, {t['source']})"
                )
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, state_id: str) -> str:
        """Write evidence bundle for a session state."""
        self._validate_id_segment(state_id, "state_id")
        data = self._load_state(state_id)
        if data is None:
            raise ValueError(f"Session state not found: {state_id}")

        evidence_dir = self._safe_state_path(state_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # session_state_request.json
        request_data = {
            "state_id": data["state_id"],
            "session_id": data["session_id"],
            "current_state": data["current_state"],
            "reason": data["reason"],
            "source": data["source"],
        }
        (evidence_dir / "session_state_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # session_state_result.json
        result_data = dict(data)
        result_data["transitions"] = self._load_transitions(state_id)
        (evidence_dir / "session_state_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        # session_state_summary.md
        md = self.export_state(state_id)
        (evidence_dir / "session_state_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        is_terminal = data.get("current_state") in (
            SessionStateValue.COMPLETED.value,
            SessionStateValue.FAILED.value,
        )
        is_success = data.get("current_state") == SessionStateValue.COMPLETED.value
        pass_fail = {
            "passed": is_success,
            "state_id": state_id,
            "current_state": data.get("current_state", ""),
            "is_terminal": is_terminal,
            "session_id": data.get("session_id", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_state(self, state: SessionState) -> None:
        """Write a new state to disk."""
        state_dir = self._safe_state_path(state.state_id)
        state_dir.mkdir(parents=True, exist_ok=True)
        data = state.to_dict()
        (state_dir / "state.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_state(self, state_id: str) -> dict[str, Any] | None:
        """Load a state from disk."""
        state_dir = self._safe_state_path(state_id)
        state_file = state_dir / "state.json"
        if not state_file.exists():
            return None
        return json.loads(state_file.read_text(encoding="utf-8"))

    def _persist_transition(
        self, state_id: str, transition: SessionStateTransition,
    ) -> None:
        """Append a transition to the state's transition log."""
        state_dir = self._safe_state_path(state_id)
        transitions_file = state_dir / "transitions.json"
        transitions: list[dict[str, Any]] = []
        if transitions_file.exists():
            try:
                transitions = json.loads(
                    transitions_file.read_text(encoding="utf-8"),
                )
            except (json.JSONDecodeError, OSError):
                transitions = []
        transitions.append(transition.to_dict())
        transitions_file.write_text(
            json.dumps(transitions, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_transitions(self, state_id: str) -> list[dict[str, Any]]:
        """Load transitions for a state."""
        state_dir = self._safe_state_path(state_id)
        transitions_file = state_dir / "transitions.json"
        if not transitions_file.exists():
            return []
        try:
            return json.loads(transitions_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
