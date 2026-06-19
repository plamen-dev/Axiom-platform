"""Tests for the Coding Session Orchestrator v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.coding_session_orchestrator import (
    _STAGE_INDEX,
    _STAGE_ORDER,
    CheckpointKind,
    CodingSessionOrchestrator,
    ObservationSeverity,
    OrchestratorStatus,
    SessionCheckpoint,
    SessionExecutionPlan,
    SessionObservation,
    SessionStage,
    SessionTask,
    SessionTransitionReason,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def orch(tmp_path: Path) -> CodingSessionOrchestrator:
    return CodingSessionOrchestrator(
        artifacts_root=str(tmp_path / "artifacts"),
    )


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_session_task_to_dict(self):
        t = SessionTask(stage="validation", description="Run tests")
        d = t.to_dict()
        assert d["stage"] == "validation"
        assert d["description"] == "Run tests"
        assert d["task_id"]

    def test_session_checkpoint_to_dict(self):
        c = SessionCheckpoint(kind="patch_ready", status="reached")
        d = c.to_dict()
        assert d["kind"] == "patch_ready"
        assert d["status"] == "reached"

    def test_session_observation_to_dict(self):
        o = SessionObservation(severity="warning", message="Missing tests")
        d = o.to_dict()
        assert d["severity"] == "warning"
        assert d["message"] == "Missing tests"

    def test_transition_reason_to_dict(self):
        t = SessionTransitionReason(
            from_stage="initialization",
            to_stage="implementation_planning",
            reason="Ready to plan",
        )
        d = t.to_dict()
        assert d["from_stage"] == "initialization"
        assert d["to_stage"] == "implementation_planning"

    def test_execution_plan_to_dict(self):
        p = SessionExecutionPlan(
            session_id="test-session",
            status="running",
        )
        d = p.to_dict()
        assert d["session_id"] == "test-session"
        assert d["status"] == "running"
        assert "stage_progress" in d

    def test_execution_plan_progress(self):
        p = SessionExecutionPlan(
            completed_stages=["initialization", "implementation_planning"],
        )
        d = p.to_dict()
        progress = d["stage_progress"]
        assert progress["total_stages"] == 9
        assert progress["completed_stages"] == 2
        assert progress["percentage"] == 22


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_session_stage_values(self):
        assert SessionStage.INITIALIZATION.value == "initialization"
        assert SessionStage.SESSION_SUMMARY.value == "session_summary"

    def test_orchestrator_status_values(self):
        assert OrchestratorStatus.RUNNING.value == "running"
        assert OrchestratorStatus.BLOCKED.value == "blocked"

    def test_checkpoint_kind_values(self):
        assert CheckpointKind.PATCH_READY.value == "patch_ready"
        assert CheckpointKind.SESSION_COMPLETE.value == "session_complete"

    def test_observation_severity_values(self):
        assert ObservationSeverity.BLOCKER.value == "blocker"
        assert ObservationSeverity.INFO.value == "info"

    def test_stage_order(self):
        assert len(_STAGE_ORDER) == 9
        assert _STAGE_ORDER[0] == "initialization"
        assert _STAGE_ORDER[-1] == "session_summary"

    def test_stage_index(self):
        assert _STAGE_INDEX["initialization"] == 0
        assert _STAGE_INDEX["session_summary"] == 8


# ---------------------------------------------------------------------------
# Orchestration CRUD tests
# ---------------------------------------------------------------------------


class TestCreateOrchestration:
    def test_create_basic(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        assert plan["session_id"] == "s-001"
        assert plan["status"] == "running"
        assert plan["current_stage"] == "initialization"
        assert len(plan["checkpoints"]) == 5

    def test_create_persists(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        loaded = orch.get_orchestration(plan["plan_id"])
        assert loaded is not None
        assert loaded["session_id"] == "s-001"


class TestGetOrchestration:
    def test_get_existing(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        result = orch.get_orchestration(plan["plan_id"])
        assert result["plan_id"] == plan["plan_id"]

    def test_get_nonexistent(self, orch):
        result = orch.get_orchestration("nonexistent")
        assert result is None

    def test_get_path_traversal_rejected(self, orch):
        with pytest.raises(ValueError, match="must not contain"):
            orch.get_orchestration("../../etc/passwd")


class TestListOrchestrations:
    def test_list_empty(self, orch):
        plans = orch.list_orchestrations()
        assert plans == []

    def test_list_all(self, orch):
        orch.create_orchestration(session_id="s-001")
        orch.create_orchestration(session_id="s-002")
        plans = orch.list_orchestrations()
        assert len(plans) == 2

    def test_list_filter_by_status(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        orch.complete_session(plan["plan_id"])
        orch.create_orchestration(session_id="s-002")
        completed = orch.list_orchestrations(status="completed")
        assert len(completed) == 1


# ---------------------------------------------------------------------------
# Stage advancement tests
# ---------------------------------------------------------------------------


class TestAdvanceStage:
    def test_advance_once(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.advance_stage(plan["plan_id"], reason="Init done")
        assert updated["current_stage"] == "implementation_planning"
        assert "initialization" in updated["completed_stages"]

    def test_advance_multiple(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        for i in range(3):
            plan = orch.advance_stage(plan["plan_id"])
        assert plan["current_stage"] == "impact_analysis"
        assert len(plan["completed_stages"]) == 3

    def test_advance_records_transition(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.advance_stage(plan["plan_id"], reason="Ready")
        assert len(updated["transitions"]) == 1
        assert updated["transitions"][0]["reason"] == "Ready"

    def test_advance_nonexistent(self, orch):
        result = orch.advance_stage("nonexistent")
        assert result is None

    def test_advance_at_last_stage(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        for _ in range(8):
            plan = orch.advance_stage(plan["plan_id"])
        assert plan["current_stage"] == "session_summary"
        same = orch.advance_stage(plan["plan_id"])
        assert same["current_stage"] == "session_summary"

    def test_advance_updates_checkpoint(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        for _ in range(3):
            plan = orch.advance_stage(plan["plan_id"])
        reached = [
            c for c in plan["checkpoints"]
            if c["status"] == "reached"
        ]
        assert len(reached) >= 1


# ---------------------------------------------------------------------------
# Block stage tests
# ---------------------------------------------------------------------------


class TestBlockStage:
    def test_block_current(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        blocked = orch.block_stage(plan["plan_id"], reason="Missing dep")
        assert blocked["status"] == "blocked"
        assert "initialization" in blocked["blocked_stages"]
        assert any(
            o["severity"] == "blocker" for o in blocked["observations"]
        )

    def test_block_nonexistent(self, orch):
        result = orch.block_stage("nonexistent", reason="test")
        assert result is None


# ---------------------------------------------------------------------------
# Observation tests
# ---------------------------------------------------------------------------


class TestAddObservation:
    def test_add_warning(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.add_observation(
            plan["plan_id"], "warning", "Low test coverage",
        )
        assert len(updated["observations"]) == 1
        assert updated["observations"][0]["severity"] == "warning"

    def test_add_uses_current_stage(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.add_observation(
            plan["plan_id"], "info", "Starting init",
        )
        assert updated["observations"][0]["stage"] == "initialization"

    def test_add_nonexistent(self, orch):
        result = orch.add_observation("nonexistent", "info", "test")
        assert result is None


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


class TestAddTask:
    def test_add_task(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.add_task(plan["plan_id"], "Create implementation plan")
        assert len(updated["tasks"]) == 1
        assert updated["tasks"][0]["description"] == "Create implementation plan"

    def test_add_task_nonexistent(self, orch):
        result = orch.add_task("nonexistent", "test")
        assert result is None


# ---------------------------------------------------------------------------
# Link ID tests
# ---------------------------------------------------------------------------


class TestLinkId:
    def test_link_work_item(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        updated = orch.link_id(plan["plan_id"], "work_item_id", "wi-001")
        assert updated["linked_ids"]["work_item_id"] == "wi-001"

    def test_link_nonexistent(self, orch):
        result = orch.link_id("nonexistent", "key", "val")
        assert result is None


# ---------------------------------------------------------------------------
# Complete session tests
# ---------------------------------------------------------------------------


class TestCompleteSession:
    def test_complete(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        completed = orch.complete_session(plan["plan_id"])
        assert completed["status"] == "completed"
        assert len(completed["completed_stages"]) == 9

    def test_complete_marks_checkpoint(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        completed = orch.complete_session(plan["plan_id"])
        session_cp = [
            c for c in completed["checkpoints"]
            if c["kind"] == "session_complete"
        ]
        assert session_cp[0]["status"] == "reached"

    def test_complete_nonexistent(self, orch):
        result = orch.complete_session("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    def test_basic_summary(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        summary = orch.generate_summary(plan["plan_id"])
        assert summary["plan_id"] == plan["plan_id"]
        assert summary["session_id"] == "s-001"
        assert "progress" in summary

    def test_summary_with_observations(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        orch.add_observation(plan["plan_id"], "warning", "Missing coverage")
        summary = orch.generate_summary(plan["plan_id"])
        assert summary["total_observations"] == 1
        assert len(summary["warnings"]) == 1

    def test_summary_nonexistent(self, orch):
        result = orch.generate_summary("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Evidence bundle tests
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    def test_writes_four_files(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        evidence_dir = orch.write_evidence(plan["plan_id"])
        p = Path(evidence_dir)
        assert (p / "orchestration_request.json").exists()
        assert (p / "orchestration_result.json").exists()
        assert (p / "orchestration_summary.md").exists()
        assert (p / "pass_fail.json").exists()

    def test_evidence_valid_json(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        evidence_dir = orch.write_evidence(plan["plan_id"])
        p = Path(evidence_dir)
        for fname in [
            "orchestration_request.json",
            "orchestration_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((p / fname).read_text())
            assert isinstance(data, dict)

    def test_evidence_nonexistent(self, orch):
        with pytest.raises(ValueError, match="Orchestration not found"):
            orch.write_evidence("nonexistent")

    def test_evidence_path_traversal_rejected(self, orch):
        with pytest.raises(ValueError, match="must not contain"):
            orch.write_evidence("../../etc/passwd")

    def test_summary_content(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        evidence_dir = orch.write_evidence(plan["plan_id"])
        summary = (Path(evidence_dir) / "orchestration_summary.md").read_text()
        assert "Coding Session Orchestration Summary" in summary

    def test_pass_fail_structure(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        evidence_dir = orch.write_evidence(plan["plan_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert "passed" in pf
        assert "plan_id" in pf
        assert "timestamp" in pf


# ---------------------------------------------------------------------------
# Path traversal security
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_rejects_dots(self, orch):
        with pytest.raises(ValueError, match="must not contain"):
            orch._validate_id_segment("../../etc", "plan_id")

    def test_rejects_slash(self, orch):
        with pytest.raises(ValueError, match="must not contain"):
            orch._validate_id_segment("a/b", "plan_id")

    def test_rejects_backslash(self, orch):
        with pytest.raises(ValueError, match="must not contain"):
            orch._validate_id_segment("a\\b", "plan_id")


# ---------------------------------------------------------------------------
# Deterministic ordering tests
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_stage_order_preserved(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        stages_visited = [plan["current_stage"]]
        for _ in range(8):
            plan = orch.advance_stage(plan["plan_id"])
            stages_visited.append(plan["current_stage"])
        assert stages_visited == _STAGE_ORDER

    def test_transitions_ordered(self, orch):
        plan = orch.create_orchestration(session_id="s-001")
        for _ in range(4):
            plan = orch.advance_stage(plan["plan_id"])
        transitions = plan["transitions"]
        for i in range(len(transitions) - 1):
            assert transitions[i]["to_stage"] == transitions[i + 1]["from_stage"]
