"""Tests for SessionStateMachineRegistry and Session State Machine v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_state_machine import (
    SessionState,
    SessionStateMachineRegistry,
    SessionStateSource,
    SessionStateTransition,
    SessionStateValue,
    TransitionReason,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestSessionStateValue:
    def test_values(self) -> None:
        assert SessionStateValue.CREATED.value == "created"
        assert SessionStateValue.PLANNING.value == "planning"
        assert SessionStateValue.EXECUTING.value == "executing"
        assert SessionStateValue.VALIDATING.value == "validating"
        assert SessionStateValue.REPAIRING.value == "repairing"
        assert SessionStateValue.REVIEWING.value == "reviewing"
        assert SessionStateValue.REPORTING.value == "reporting"
        assert SessionStateValue.COMPLETED.value == "completed"
        assert SessionStateValue.FAILED.value == "failed"

    def test_count(self) -> None:
        assert len(SessionStateValue) == 9


class TestTransitionReason:
    def test_values(self) -> None:
        assert TransitionReason.INITIALIZED.value == "initialized"
        assert TransitionReason.PLAN_CREATED.value == "plan_created"
        assert TransitionReason.EXECUTION_STARTED.value == "execution_started"
        assert TransitionReason.VALIDATION_STARTED.value == "validation_started"
        assert TransitionReason.REPAIR_REQUIRED.value == "repair_required"
        assert TransitionReason.REVIEW_STARTED.value == "review_started"
        assert TransitionReason.REPORT_CREATED.value == "report_created"
        assert TransitionReason.COMPLETED_SUCCESSFULLY.value == "completed_successfully"
        assert TransitionReason.FAILED_VALIDATION.value == "failed_validation"
        assert TransitionReason.FAILED_REVIEW.value == "failed_review"
        assert TransitionReason.FAILED_EXECUTION.value == "failed_execution"
        assert TransitionReason.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(TransitionReason) == 12


class TestSessionStateSource:
    def test_values(self) -> None:
        assert SessionStateSource.SESSION_REPORT.value == "session_report"
        assert SessionStateSource.ESCALATION.value == "escalation"
        assert SessionStateSource.REPAIR_PROPOSAL.value == "repair_proposal"
        assert SessionStateSource.REPAIR_DECISION.value == "repair_decision"
        assert SessionStateSource.CONFLICT.value == "conflict"
        assert SessionStateSource.VALIDATION.value == "validation"
        assert SessionStateSource.REVIEW_FINDING.value == "review_finding"
        assert SessionStateSource.MANUAL.value == "manual"
        assert SessionStateSource.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(SessionStateSource) == 9


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestSessionStateDataclass:
    def test_defaults(self) -> None:
        s = SessionState(session_id="sess-1")
        assert s.session_id == "sess-1"
        assert s.state_id
        assert s.current_state == "created"
        assert s.previous_state == ""
        assert s.reason == "initialized"
        assert s.source == "other"
        assert s.rationale == ""
        assert s.created_at

    def test_to_dict(self) -> None:
        s = SessionState(session_id="sess-1")
        d = s.to_dict()
        assert d["session_id"] == "sess-1"
        assert d["current_state"] == "created"
        assert "state_id" in d
        assert "created_at" in d


class TestSessionStateTransitionDataclass:
    def test_defaults(self) -> None:
        t = SessionStateTransition(
            session_id="sess-1",
            from_state="created",
            to_state="planning",
        )
        assert t.transition_id
        assert t.from_state == "created"
        assert t.to_state == "planning"
        assert t.reason == "other"
        assert t.created_at

    def test_to_dict(self) -> None:
        t = SessionStateTransition(
            session_id="sess-1",
            from_state="created",
            to_state="planning",
        )
        d = t.to_dict()
        assert d["from_state"] == "created"
        assert d["to_state"] == "planning"
        assert "transition_id" in d


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateState:
    def test_basic(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        assert state["session_id"] == "sess-1"
        assert state["current_state"] == "created"
        assert state["reason"] == "initialized"
        assert state["source"] == "other"

    def test_custom_fields(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(
            session_id="sess-2",
            current_state="planning",
            reason="plan_created",
            source="manual",
            rationale="Starting plan phase",
        )
        assert state["current_state"] == "planning"
        assert state["reason"] == "plan_created"
        assert state["source"] == "manual"
        assert state["rationale"] == "Starting plan phase"

    def test_invalid_state(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid current_state"):
            reg.create_state(session_id="s", current_state="nonexistent")

    def test_invalid_reason(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid reason"):
            reg.create_state(session_id="s", reason="nonexistent")

    def test_invalid_source(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid source"):
            reg.create_state(session_id="s", source="nonexistent")


class TestGetState:
    def test_existing(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        created = reg.create_state(session_id="sess-1")
        found = reg.get_state(created["state_id"])
        assert found is not None
        assert found["session_id"] == "sess-1"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        assert reg.get_state("does-not-exist") is None


class TestListStates:
    def test_empty(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        assert reg.list_states() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        reg.create_state(session_id="sess-1")
        reg.create_state(session_id="sess-2")
        result = reg.list_states()
        assert len(result) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        reg.create_state(session_id="s1", current_state="executing")
        reg.create_state(session_id="s2", current_state="created")
        reg.create_state(session_id="s3", current_state="planning")
        result = reg.list_states()
        order = [s["current_state"] for s in result]
        assert order == ["created", "planning", "executing"]

    def test_filter_session_id(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        reg.create_state(session_id="sess-1")
        reg.create_state(session_id="sess-2")
        filtered = reg.list_states(session_id="sess-1")
        assert len(filtered) == 1
        assert filtered[0]["session_id"] == "sess-1"

    def test_filter_current_state(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        reg.create_state(session_id="s1", current_state="created")
        reg.create_state(session_id="s2", current_state="planning")
        filtered = reg.list_states(current_state="planning")
        assert len(filtered) == 1
        assert filtered[0]["session_id"] == "s2"


# ---------------------------------------------------------------------------
# Transition tests
# ---------------------------------------------------------------------------


class TestTransitionState:
    def test_valid_transition(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        transition = reg.transition_state(
            state_id=state["state_id"],
            to_state="planning",
            reason="plan_created",
            source="manual",
            rationale="Starting planning",
        )
        assert transition["from_state"] == "created"
        assert transition["to_state"] == "planning"
        assert transition["reason"] == "plan_created"

    def test_state_updated_after_transition(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        reg.transition_state(state_id=state["state_id"], to_state="planning")
        updated = reg.get_state(state["state_id"])
        assert updated is not None
        assert updated["current_state"] == "planning"
        assert updated["previous_state"] == "created"

    def test_invalid_transition(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.transition_state(
                state_id=state["state_id"], to_state="completed",
            )

    def test_transition_nonexistent_state(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.transition_state(state_id="nope", to_state="planning")

    def test_full_lifecycle(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-lifecycle")
        sid = state["state_id"]
        reg.transition_state(sid, "planning", reason="plan_created")
        reg.transition_state(sid, "executing", reason="execution_started")
        reg.transition_state(sid, "validating", reason="validation_started")
        reg.transition_state(sid, "reviewing", reason="review_started")
        reg.transition_state(sid, "reporting", reason="report_created")
        reg.transition_state(sid, "completed", reason="completed_successfully")
        final = reg.get_state(sid)
        assert final is not None
        assert final["current_state"] == "completed"
        assert final["previous_state"] == "reporting"

    def test_terminal_state_no_transition(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        sid = state["state_id"]
        reg.transition_state(sid, "planning")
        reg.transition_state(sid, "failed", reason="failed_execution")
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.transition_state(sid, "planning")

    def test_repair_loop(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-repair")
        sid = state["state_id"]
        reg.transition_state(sid, "planning")
        reg.transition_state(sid, "executing")
        reg.transition_state(sid, "validating")
        reg.transition_state(sid, "repairing", reason="repair_required")
        reg.transition_state(sid, "validating", reason="validation_started")
        reg.transition_state(sid, "reviewing", reason="review_started")
        final = reg.get_state(sid)
        assert final is not None
        assert final["current_state"] == "reviewing"

    def test_invalid_to_state(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        with pytest.raises(ValueError, match="Invalid to_state"):
            reg.transition_state(
                state_id=state["state_id"], to_state="nonexistent",
            )


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportState:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(
            session_id="sess-export",
            rationale="Test export",
            source="manual",
        )
        md = reg.export_state(state["state_id"])
        assert "# Session State: CREATED" in md
        assert "sess-export" in md
        assert "Test export" in md
        assert "manual" in md

    def test_export_with_transitions(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        reg.transition_state(state["state_id"], "planning", reason="plan_created")
        md = reg.export_state(state["state_id"])
        assert "## Transitions" in md
        assert "created → planning" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_state("nope")


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-ev")
        evidence_dir = reg.write_evidence(state["state_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "session_state_request.json").exists()
        assert (ev_path / "session_state_result.json").exists()
        assert (ev_path / "session_state_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_valid_json(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-json")
        evidence_dir = reg.write_evidence(state["state_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "session_state_request.json",
            "session_state_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_created(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        evidence_dir = reg.write_evidence(state["state_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False
        assert pf["is_terminal"] is False

    def test_pass_fail_completed(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        sid = state["state_id"]
        reg.transition_state(sid, "planning")
        reg.transition_state(sid, "executing")
        reg.transition_state(sid, "validating")
        reg.transition_state(sid, "reviewing")
        reg.transition_state(sid, "reporting")
        reg.transition_state(sid, "completed")
        evidence_dir = reg.write_evidence(sid)
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is True
        assert pf["is_terminal"] is True

    def test_pass_fail_failed(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        state = reg.create_state(session_id="sess-1")
        reg.transition_state(state["state_id"], "failed")
        evidence_dir = reg.write_evidence(state["state_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False
        assert pf["is_terminal"] is True

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_state("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_state("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_state("../etc/passwd")

    def test_symlink_traversal_blocked(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        states_dir = tmp_path / "session_states"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = states_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            reg._safe_state_path("evil-link")

    def test_symlink_skipped_in_list(self, tmp_path: Path) -> None:
        reg = SessionStateMachineRegistry(artifacts_root=str(tmp_path))
        reg.create_state(session_id="real")
        outside = tmp_path / "outside"
        outside.mkdir()
        fake_json = outside / "state.json"
        fake_json.write_text('{"session_id":"evil","current_state":"created"}')
        states_dir = tmp_path / "session_states"
        symlink = states_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        results = reg.list_states()
        sessions = [s["session_id"] for s in results]
        assert "real" in sessions
        assert "evil" not in sessions


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_session_state_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "session-state-create",
            "session-states",
            "session-state-show",
            "session-state-transition",
            "session-state-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_session_state_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-state-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "session_state_request.json" in locations
        assert "session_state_result.json" in locations
        assert "session_state_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/session_state_machine.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_session_state_machine.py"
