"""Tests for the Autonomous Coding Session Registry v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.coding_session_registry import (
    ArtifactKind,
    CodingSession,
    CodingSessionRegistry,
    DecisionKind,
    SessionArtifact,
    SessionCostEstimate,
    SessionDecision,
    SessionStatus,
    SessionStep,
    StepKind,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> CodingSessionRegistry:
    return CodingSessionRegistry(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_session_step_to_dict(self):
        step = SessionStep(kind="planning", description="Plan implementation")
        d = step.to_dict()
        assert d["kind"] == "planning"
        assert d["description"] == "Plan implementation"
        assert d["step_id"]
        assert d["started_at"]

    def test_session_artifact_to_dict(self):
        a = SessionArtifact(kind="work_item", reference_id="wi-123")
        d = a.to_dict()
        assert d["kind"] == "work_item"
        assert d["reference_id"] == "wi-123"

    def test_session_decision_to_dict(self):
        d = SessionDecision(kind="proceed", reason="All checks pass")
        result = d.to_dict()
        assert result["kind"] == "proceed"
        assert result["reason"] == "All checks pass"

    def test_session_cost_estimate(self):
        c = SessionCostEstimate(
            total_steps=5, completed_steps=3, artifacts_produced=2,
        )
        d = c.to_dict()
        assert d["total_steps"] == 5
        assert d["completed_steps"] == 3

    def test_coding_session_to_dict(self):
        s = CodingSession(title="Test Session", status="running")
        d = s.to_dict()
        assert d["title"] == "Test Session"
        assert d["status"] == "running"
        assert d["session_id"]
        assert d["created_at"]
        assert "cost_estimate" in d

    def test_coding_session_cost_computed(self):
        s = CodingSession(title="Test")
        s.steps = [
            SessionStep(kind="planning", status="completed"),
            SessionStep(kind="testing", status="blocked"),
            SessionStep(kind="review", status="pending"),
        ]
        d = s.to_dict()
        cost = d["cost_estimate"]
        assert cost["total_steps"] == 3
        assert cost["completed_steps"] == 1
        assert cost["blocked_steps"] == 1
        assert cost["estimated_remaining"] == 2


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_session_status_values(self):
        assert SessionStatus.PENDING.value == "pending"
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.BLOCKED.value == "blocked"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.FAILED.value == "failed"
        assert SessionStatus.CANCELLED.value == "cancelled"

    def test_step_kind_values(self):
        assert StepKind.PLANNING.value == "planning"
        assert StepKind.VALIDATION.value == "validation"

    def test_artifact_kind_values(self):
        assert ArtifactKind.WORK_ITEM.value == "work_item"
        assert ArtifactKind.EVIDENCE_BUNDLE.value == "evidence_bundle"

    def test_decision_kind_values(self):
        assert DecisionKind.PROCEED.value == "proceed"
        assert DecisionKind.ESCALATE.value == "escalate"


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_create_basic(self, registry):
        session = registry.create_session(title="Test Session")
        assert session["title"] == "Test Session"
        assert session["status"] == "pending"
        assert session["session_id"]

    def test_create_with_work_item(self, registry):
        session = registry.create_session(
            title="With WI", work_item_id="wi-001",
        )
        assert session["work_item_id"] == "wi-001"

    def test_create_persists(self, registry):
        session = registry.create_session(title="Persist Test")
        loaded = registry.get_session(session["session_id"])
        assert loaded is not None
        assert loaded["title"] == "Persist Test"


class TestGetSession:
    def test_get_existing(self, registry):
        session = registry.create_session(title="Existing")
        result = registry.get_session(session["session_id"])
        assert result["session_id"] == session["session_id"]

    def test_get_nonexistent(self, registry):
        result = registry.get_session("nonexistent-id")
        assert result is None

    def test_get_path_traversal_rejected(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_session("../../etc/passwd")


class TestListSessions:
    def test_list_empty(self, registry):
        sessions = registry.list_sessions()
        assert sessions == []

    def test_list_all(self, registry):
        registry.create_session(title="A")
        registry.create_session(title="B")
        sessions = registry.list_sessions()
        assert len(sessions) == 2

    def test_list_filter_by_status(self, registry):
        first = registry.create_session(title="A")
        registry.create_session(title="B")
        registry.update_status(first["session_id"], "completed")
        completed = registry.list_sessions(status="completed")
        assert len(completed) == 1
        assert completed[0]["status"] == "completed"

    def test_list_deterministic_ordering(self, registry):
        registry.create_session(title="Pending")
        s2 = registry.create_session(title="Running")
        registry.update_status(s2["session_id"], "running")
        sessions = registry.list_sessions()
        assert sessions[0]["status"] == "running"
        assert sessions[1]["status"] == "pending"


class TestUpdateStatus:
    def test_update_to_running(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.update_status(session["session_id"], "running")
        assert updated["status"] == "running"

    def test_update_nonexistent(self, registry):
        result = registry.update_status("nonexistent", "running")
        assert result is None

    def test_update_persists(self, registry):
        session = registry.create_session(title="Test")
        registry.update_status(session["session_id"], "completed")
        loaded = registry.get_session(session["session_id"])
        assert loaded["status"] == "completed"


# ---------------------------------------------------------------------------
# Step, artifact, decision tests
# ---------------------------------------------------------------------------


class TestAddStep:
    def test_add_step(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.add_step(
            session["session_id"], "planning", "Plan the work",
        )
        assert len(updated["steps"]) == 1
        assert updated["steps"][0]["kind"] == "planning"

    def test_add_multiple_steps(self, registry):
        session = registry.create_session(title="Test")
        registry.add_step(session["session_id"], "planning", "Step 1")
        updated = registry.add_step(
            session["session_id"], "testing", "Step 2",
        )
        assert len(updated["steps"]) == 2

    def test_add_step_nonexistent(self, registry):
        result = registry.add_step("nonexistent", "planning", "Step")
        assert result is None


class TestAddArtifact:
    def test_add_artifact(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.add_artifact(
            session["session_id"],
            kind="work_item",
            reference_id="wi-001",
            description="Work item artifact",
        )
        assert len(updated["artifacts"]) == 1
        assert updated["artifacts"][0]["kind"] == "work_item"

    def test_add_artifact_nonexistent(self, registry):
        result = registry.add_artifact("nonexistent", kind="work_item")
        assert result is None


class TestAddDecision:
    def test_add_decision(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.add_decision(
            session["session_id"], "proceed", "Tests passed",
        )
        assert len(updated["decisions"]) == 1
        assert updated["decisions"][0]["kind"] == "proceed"

    def test_add_decision_nonexistent(self, registry):
        result = registry.add_decision("nonexistent", "proceed", "reason")
        assert result is None


# ---------------------------------------------------------------------------
# Blockers and next actions
# ---------------------------------------------------------------------------


class TestBlockers:
    def test_set_blockers(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.set_blockers(
            session["session_id"], ["Missing credentials"],
        )
        assert updated["blockers"] == ["Missing credentials"]
        assert updated["status"] == "blocked"

    def test_clear_blockers(self, registry):
        session = registry.create_session(title="Test")
        registry.set_blockers(session["session_id"], ["Blocker"])
        updated = registry.set_blockers(session["session_id"], [])
        assert updated["blockers"] == []


class TestNextActions:
    def test_set_next_actions(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.set_next_actions(
            session["session_id"], ["Run tests", "Create PR"],
        )
        assert updated["next_actions"] == ["Run tests", "Create PR"]


# ---------------------------------------------------------------------------
# Link IDs
# ---------------------------------------------------------------------------


class TestLinkId:
    def test_link_work_item(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.link_id(
            session["session_id"], "work_item_id", "wi-001",
        )
        assert updated["work_item_id"] == "wi-001"

    def test_link_patch_proposal(self, registry):
        session = registry.create_session(title="Test")
        updated = registry.link_id(
            session["session_id"], "patch_proposal_id", "pp-001",
        )
        assert updated["patch_proposal_id"] == "pp-001"

    def test_link_invalid_field(self, registry):
        session = registry.create_session(title="Test")
        with pytest.raises(ValueError, match="Invalid field"):
            registry.link_id(session["session_id"], "invalid_field", "x")

    def test_link_nonexistent_session(self, registry):
        result = registry.link_id("nonexistent", "work_item_id", "x")
        assert result is None


# ---------------------------------------------------------------------------
# Evidence bundle tests
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    def test_writes_four_files(self, registry):
        session = registry.create_session(title="Evidence Test")
        evidence_dir = registry.write_evidence(session["session_id"])
        p = Path(evidence_dir)
        assert (p / "session_request.json").exists()
        assert (p / "session_result.json").exists()
        assert (p / "session_summary.md").exists()
        assert (p / "pass_fail.json").exists()

    def test_evidence_valid_json(self, registry):
        session = registry.create_session(title="JSON Test")
        evidence_dir = registry.write_evidence(session["session_id"])
        p = Path(evidence_dir)
        for fname in [
            "session_request.json", "session_result.json", "pass_fail.json",
        ]:
            data = json.loads((p / fname).read_text())
            assert isinstance(data, dict)

    def test_evidence_nonexistent_session(self, registry):
        with pytest.raises(ValueError, match="Session not found"):
            registry.write_evidence("nonexistent-id")

    def test_evidence_path_traversal_rejected(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.write_evidence("../../etc/passwd")

    def test_pass_fail_structure(self, registry):
        session = registry.create_session(title="PF Test")
        evidence_dir = registry.write_evidence(session["session_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert "passed" in pf
        assert "session_id" in pf
        assert "timestamp" in pf

    def test_summary_content(self, registry):
        session = registry.create_session(title="Summary Test")
        evidence_dir = registry.write_evidence(session["session_id"])
        summary = (Path(evidence_dir) / "session_summary.md").read_text()
        assert "Coding Session Summary" in summary
        assert "Summary Test" in summary


# ---------------------------------------------------------------------------
# Path traversal security
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_rejects_dots(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry._validate_id_segment("../../etc", "session_id")

    def test_rejects_slash(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry._validate_id_segment("a/b", "session_id")

    def test_rejects_backslash(self, registry):
        with pytest.raises(ValueError, match="must not contain"):
            registry._validate_id_segment("a\\b", "session_id")
