"""Tests for the Session Plan Registry v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_plan_registry import (
    GoalPriority,
    PlanStatus,
    SessionAssumption,
    SessionConstraint,
    SessionGoal,
    SessionPlan,
    SessionPlanRegistry,
    SessionPlanStep,
    StepCategory,
    StepStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> SessionPlanRegistry:
    return SessionPlanRegistry(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_plan_status_values(self):
        assert PlanStatus.DRAFT.value == "draft"
        assert PlanStatus.ACTIVE.value == "active"
        assert PlanStatus.COMPLETED.value == "completed"
        assert PlanStatus.SUPERSEDED.value == "superseded"
        assert PlanStatus.CANCELLED.value == "cancelled"

    def test_step_status_values(self):
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.IN_PROGRESS.value == "in_progress"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.BLOCKED.value == "blocked"

    def test_step_category_values(self):
        assert StepCategory.ANALYSIS.value == "analysis"
        assert StepCategory.IMPLEMENTATION.value == "implementation"
        assert StepCategory.TESTING.value == "testing"
        assert StepCategory.REVIEW.value == "review"
        assert StepCategory.VALIDATION.value == "validation"
        assert StepCategory.EVIDENCE.value == "evidence"
        assert StepCategory.DOCUMENTATION.value == "documentation"

    def test_goal_priority_values(self):
        assert GoalPriority.CRITICAL.value == "critical"
        assert GoalPriority.HIGH.value == "high"
        assert GoalPriority.MEDIUM.value == "medium"
        assert GoalPriority.LOW.value == "low"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_session_goal_defaults(self):
        g = SessionGoal(description="Test goal")
        assert g.goal_id
        assert g.description == "Test goal"
        assert g.priority == "medium"
        assert g.linked_work_item_id == ""

    def test_session_goal_to_dict(self):
        g = SessionGoal(description="G1", priority="high")
        d = g.to_dict()
        assert d["description"] == "G1"
        assert d["priority"] == "high"
        assert "goal_id" in d

    def test_session_assumption_defaults(self):
        a = SessionAssumption(description="Assume X")
        assert a.assumption_id
        assert a.description == "Assume X"
        assert a.verified is False
        assert a.source == ""

    def test_session_assumption_to_dict(self):
        a = SessionAssumption(description="A1", verified=True, source="docs")
        d = a.to_dict()
        assert d["verified"] is True
        assert d["source"] == "docs"

    def test_session_constraint_defaults(self):
        c = SessionConstraint(description="No network")
        assert c.constraint_id
        assert c.description == "No network"
        assert c.category == ""

    def test_session_constraint_to_dict(self):
        c = SessionConstraint(description="C1", category="security")
        d = c.to_dict()
        assert d["category"] == "security"

    def test_session_plan_step_defaults(self):
        s = SessionPlanStep(description="Do thing")
        assert s.step_id
        assert s.order == 0
        assert s.category == "implementation"
        assert s.status == "pending"
        assert s.dependencies == []
        assert s.linked_ids == []
        assert s.created_at

    def test_session_plan_step_to_dict(self):
        s = SessionPlanStep(
            order=1,
            category="testing",
            description="Run tests",
            rationale="Safety",
            dependencies=["step-1"],
        )
        d = s.to_dict()
        assert d["order"] == 1
        assert d["category"] == "testing"
        assert d["dependencies"] == ["step-1"]
        assert d["rationale"] == "Safety"

    def test_session_plan_defaults(self):
        p = SessionPlan(title="Test Plan")
        assert p.plan_id
        assert p.title == "Test Plan"
        assert p.status == "draft"
        assert p.goals == []
        assert p.assumptions == []
        assert p.constraints == []
        assert p.steps == []
        assert p.created_at
        assert p.updated_at

    def test_session_plan_to_dict(self):
        p = SessionPlan(title="P1", rationale="Because")
        d = p.to_dict()
        assert d["title"] == "P1"
        assert d["rationale"] == "Because"
        assert d["step_summary"]["total"] == 0
        assert d["step_summary"]["remaining"] == 0

    def test_session_plan_step_summary(self):
        p = SessionPlan(
            title="P2",
            steps=[
                SessionPlanStep(order=1, description="A", status="completed"),
                SessionPlanStep(order=2, description="B", status="pending"),
                SessionPlanStep(order=3, description="C", status="blocked"),
            ],
        )
        d = p.to_dict()
        s = d["step_summary"]
        assert s["total"] == 3
        assert s["completed"] == 1
        assert s["pending"] == 1
        assert s["blocked"] == 1
        assert s["remaining"] == 2


# ---------------------------------------------------------------------------
# Registry — create plan
# ---------------------------------------------------------------------------


class TestCreatePlan:
    def test_create_minimal(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Minimal Plan")
        assert plan["title"] == "Minimal Plan"
        assert plan["status"] == "draft"
        assert plan["plan_id"]
        assert plan["step_summary"]["total"] == 0

    def test_create_with_all_fields(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Full Plan",
            session_id="sess-1",
            work_item_id="wi-1",
            implementation_plan_id="ip-1",
            rationale="Testing all fields",
            goals=[
                {"description": "Goal 1", "priority": "critical"},
                {"description": "Goal 2", "priority": "low"},
            ],
            assumptions=[
                {"description": "Assume A", "verified": True, "source": "docs"},
            ],
            constraints=[
                {"description": "No network", "category": "security"},
            ],
            steps=[
                {"category": "analysis", "description": "Analyze"},
                {"category": "implementation", "description": "Implement"},
                {"category": "testing", "description": "Test"},
            ],
        )
        assert plan["session_id"] == "sess-1"
        assert plan["work_item_id"] == "wi-1"
        assert plan["implementation_plan_id"] == "ip-1"
        assert plan["rationale"] == "Testing all fields"
        assert len(plan["goals"]) == 2
        assert plan["goals"][0]["priority"] == "critical"
        assert len(plan["assumptions"]) == 1
        assert plan["assumptions"][0]["verified"] is True
        assert len(plan["constraints"]) == 1
        assert plan["constraints"][0]["category"] == "security"
        assert len(plan["steps"]) == 3
        assert plan["steps"][0]["order"] == 1
        assert plan["steps"][1]["order"] == 2
        assert plan["steps"][2]["order"] == 3

    def test_create_persists_to_disk(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Persisted")
        plan_path = registry._plans_dir / plan["plan_id"] / "plan.json"
        assert plan_path.exists()
        data = json.loads(plan_path.read_text())
        assert data["title"] == "Persisted"

    def test_step_order_is_sequential(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Ordered",
            steps=[
                {"description": "Step A"},
                {"description": "Step B"},
                {"description": "Step C"},
            ],
        )
        orders = [s["order"] for s in plan["steps"]]
        assert orders == [1, 2, 3]


# ---------------------------------------------------------------------------
# Registry — get plan
# ---------------------------------------------------------------------------


class TestGetPlan:
    def test_get_existing(self, registry: SessionPlanRegistry):
        created = registry.create_plan(title="Fetchable")
        fetched = registry.get_plan(created["plan_id"])
        assert fetched is not None
        assert fetched["title"] == "Fetchable"

    def test_get_nonexistent(self, registry: SessionPlanRegistry):
        result = registry.get_plan("nonexistent-id")
        assert result is None

    def test_get_empty_id_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_plan("")

    def test_get_path_traversal_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("../etc/passwd")

    def test_get_slash_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("foo/bar")

    def test_get_backslash_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("foo\\bar")


# ---------------------------------------------------------------------------
# Registry — list plans
# ---------------------------------------------------------------------------


class TestListPlans:
    def test_list_empty(self, registry: SessionPlanRegistry):
        plans = registry.list_plans()
        assert plans == []

    def test_list_multiple(self, registry: SessionPlanRegistry):
        registry.create_plan(title="Plan A")
        registry.create_plan(title="Plan B")
        plans = registry.list_plans()
        assert len(plans) == 2

    def test_list_filter_by_status(self, registry: SessionPlanRegistry):
        p1 = registry.create_plan(title="Draft")
        registry.create_plan(title="Active")
        registry.update_status(p1["plan_id"], "active")
        drafts = registry.list_plans(status="draft")
        assert len(drafts) == 1
        assert drafts[0]["title"] == "Active"

    def test_list_deterministic_ordering(self, registry: SessionPlanRegistry):
        p1 = registry.create_plan(title="Will be active")
        registry.create_plan(title="Stays draft")
        registry.update_status(p1["plan_id"], "active")
        plans = registry.list_plans()
        assert plans[0]["status"] == "active"
        assert plans[1]["status"] == "draft"


# ---------------------------------------------------------------------------
# Registry — update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Updatable")
        updated = registry.update_status(plan["plan_id"], "active")
        assert updated is not None
        assert updated["status"] == "active"

    def test_update_status_persists(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Persist Status")
        registry.update_status(plan["plan_id"], "completed")
        fetched = registry.get_plan(plan["plan_id"])
        assert fetched is not None
        assert fetched["status"] == "completed"

    def test_update_nonexistent_returns_none(self, registry: SessionPlanRegistry):
        result = registry.update_status("nonexistent", "active")
        assert result is None

    def test_update_invalid_status_raises(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Invalid")
        with pytest.raises(ValueError, match="Invalid status"):
            registry.update_status(plan["plan_id"], "bogus")

    def test_update_updates_timestamp(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Timestamp")
        original_updated = plan["updated_at"]
        updated = registry.update_status(plan["plan_id"], "active")
        assert updated is not None
        assert updated["updated_at"] >= original_updated


# ---------------------------------------------------------------------------
# Registry — add step
# ---------------------------------------------------------------------------


class TestAddStep:
    def test_add_step(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="With Steps")
        updated = registry.add_step(
            plan["plan_id"],
            category="analysis",
            description="Analyze code",
            rationale="Understand scope",
        )
        assert updated is not None
        assert len(updated["steps"]) == 1
        assert updated["steps"][0]["category"] == "analysis"
        assert updated["steps"][0]["order"] == 1

    def test_add_multiple_steps_sequential_order(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Multi Step")
        registry.add_step(plan["plan_id"], description="Step 1")
        updated = registry.add_step(plan["plan_id"], description="Step 2")
        assert updated is not None
        assert len(updated["steps"]) == 2
        assert updated["steps"][0]["order"] == 1
        assert updated["steps"][1]["order"] == 2

    def test_add_step_with_dependencies(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Deps")
        registry.add_step(plan["plan_id"], description="Step 1")
        fetched = registry.get_plan(plan["plan_id"])
        assert fetched is not None
        step1_id = fetched["steps"][0]["step_id"]
        updated = registry.add_step(
            plan["plan_id"],
            description="Step 2",
            dependencies=[step1_id],
        )
        assert updated is not None
        assert updated["steps"][1]["dependencies"] == [step1_id]

    def test_add_step_nonexistent_returns_none(self, registry: SessionPlanRegistry):
        result = registry.add_step("nonexistent", description="X")
        assert result is None

    def test_add_step_updates_step_summary(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Summary")
        updated = registry.add_step(plan["plan_id"], description="S1")
        assert updated is not None
        assert updated["step_summary"]["total"] == 1
        assert updated["step_summary"]["pending"] == 1


# ---------------------------------------------------------------------------
# Registry — add goal
# ---------------------------------------------------------------------------


class TestAddGoal:
    def test_add_goal(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Goals")
        updated = registry.add_goal(
            plan["plan_id"],
            description="Ship feature",
            priority="high",
        )
        assert updated is not None
        assert len(updated["goals"]) == 1
        assert updated["goals"][0]["priority"] == "high"

    def test_add_goal_nonexistent_returns_none(self, registry: SessionPlanRegistry):
        result = registry.add_goal("nonexistent", description="G")
        assert result is None


# ---------------------------------------------------------------------------
# Registry — add assumption
# ---------------------------------------------------------------------------


class TestAddAssumption:
    def test_add_assumption(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Assumptions")
        updated = registry.add_assumption(
            plan["plan_id"],
            description="API is stable",
            verified=True,
            source="docs",
        )
        assert updated is not None
        assert len(updated["assumptions"]) == 1
        assert updated["assumptions"][0]["verified"] is True

    def test_add_assumption_nonexistent_returns_none(self, registry: SessionPlanRegistry):
        result = registry.add_assumption("nonexistent", description="A")
        assert result is None


# ---------------------------------------------------------------------------
# Registry — add constraint
# ---------------------------------------------------------------------------


class TestAddConstraint:
    def test_add_constraint(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Constraints")
        updated = registry.add_constraint(
            plan["plan_id"],
            description="No network",
            category="security",
            source="policy",
        )
        assert updated is not None
        assert len(updated["constraints"]) == 1
        assert updated["constraints"][0]["category"] == "security"

    def test_add_constraint_nonexistent_returns_none(self, registry: SessionPlanRegistry):
        result = registry.add_constraint("nonexistent", description="C")
        assert result is None


# ---------------------------------------------------------------------------
# Registry — export plan
# ---------------------------------------------------------------------------


class TestExportPlan:
    def test_export_markdown(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Export Test",
            rationale="Test export",
            goals=[{"description": "Goal 1", "priority": "high"}],
            assumptions=[{"description": "Assume X", "verified": True}],
            constraints=[{"description": "No mutation", "category": "safety"}],
            steps=[
                {"category": "analysis", "description": "Analyze", "rationale": "Scope"},
                {"category": "testing", "description": "Test"},
            ],
        )
        md = registry.export_plan(plan["plan_id"])
        assert "# Session Plan: Export Test" in md
        assert "## Rationale" in md
        assert "## Goals" in md
        assert "[high] Goal 1" in md
        assert "## Assumptions" in md
        assert "[verified] Assume X" in md
        assert "## Constraints" in md
        assert "[safety] No mutation" in md
        assert "## Steps" in md
        assert "1. [analysis] Analyze" in md
        assert "Rationale: Scope" in md
        assert "2. [testing] Test" in md

    def test_export_nonexistent_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="Plan not found"):
            registry.export_plan("nonexistent")

    def test_export_with_step_dependencies(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Deps Export",
            steps=[
                {"description": "A"},
                {"description": "B", "dependencies": ["step-1"]},
            ],
        )
        md = registry.export_plan(plan["plan_id"])
        assert "(depends: step-1)" in md


# ---------------------------------------------------------------------------
# Registry — evidence writing
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_write_evidence_creates_four_files(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Evidence")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        evidence_path = Path(evidence_dir)
        assert (evidence_path / "session_plan_request.json").exists()
        assert (evidence_path / "session_plan_result.json").exists()
        assert (evidence_path / "session_plan.md").exists()
        assert (evidence_path / "pass_fail.json").exists()

    def test_evidence_request_json_valid(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Valid JSON")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        data = json.loads(
            (Path(evidence_dir) / "session_plan_request.json").read_text(),
        )
        assert data["plan_id"] == plan["plan_id"]
        assert data["title"] == "Valid JSON"

    def test_evidence_result_json_valid(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Result JSON")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        data = json.loads(
            (Path(evidence_dir) / "session_plan_result.json").read_text(),
        )
        assert data["plan_id"] == plan["plan_id"]
        assert "step_summary" in data

    def test_evidence_pass_fail_json(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Pass Fail")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        data = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert data["passed"] is True
        assert data["plan_id"] == plan["plan_id"]
        assert data["status"] == "draft"

    def test_evidence_pass_fail_cancelled(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="Cancelled")
        registry.update_status(plan["plan_id"], "cancelled")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        data = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert data["passed"] is False

    def test_evidence_markdown_matches_export(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(title="MD Match")
        evidence_dir = registry.write_evidence(plan["plan_id"])
        md_from_evidence = (Path(evidence_dir) / "session_plan.md").read_text()
        md_from_export = registry.export_plan(plan["plan_id"])
        assert md_from_evidence == md_from_export

    def test_evidence_nonexistent_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="Plan not found"):
            registry.write_evidence("nonexistent")


# ---------------------------------------------------------------------------
# Registry — ID validation
# ---------------------------------------------------------------------------


class TestIDValidation:
    def test_empty_id_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_plan("")

    def test_whitespace_only_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_plan("   ")

    def test_dotdot_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("a..b")

    def test_slash_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("a/b")

    def test_backslash_raises(self, registry: SessionPlanRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_plan("a\\b")


# ---------------------------------------------------------------------------
# Registry — step summary recomputation
# ---------------------------------------------------------------------------


class TestStepSummaryRecomputation:
    def test_recompute_on_add_step(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Recompute",
            steps=[{"description": "S1"}, {"description": "S2"}],
        )
        assert plan["step_summary"]["total"] == 2
        assert plan["step_summary"]["pending"] == 2
        updated = registry.add_step(plan["plan_id"], description="S3")
        assert updated is not None
        assert updated["step_summary"]["total"] == 3

    def test_recompute_on_status_update(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Recompute Status",
            steps=[{"description": "S1"}],
        )
        updated = registry.update_status(plan["plan_id"], "active")
        assert updated is not None
        assert updated["step_summary"]["total"] == 1


# ---------------------------------------------------------------------------
# Registry — deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_plans_sorted_by_status_rank(self, registry: SessionPlanRegistry):
        registry.create_plan(title="Draft")
        p_active = registry.create_plan(title="Active")
        registry.update_status(p_active["plan_id"], "active")
        plans = registry.list_plans()
        assert plans[0]["status"] == "active"
        assert plans[1]["status"] == "draft"

    def test_plans_same_status_sorted_by_created(self, registry: SessionPlanRegistry):
        registry.create_plan(title="First")
        registry.create_plan(title="Second")
        plans = registry.list_plans()
        assert plans[0]["created_at"] <= plans[1]["created_at"]

    def test_steps_preserve_order(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Step Order",
            steps=[
                {"description": "First"},
                {"description": "Second"},
                {"description": "Third"},
            ],
        )
        orders = [s["order"] for s in plan["steps"]]
        assert orders == [1, 2, 3]

    def test_goals_sorted_by_priority_in_export(self, registry: SessionPlanRegistry):
        plan = registry.create_plan(
            title="Goal Order",
            goals=[
                {"description": "Low", "priority": "low"},
                {"description": "Critical", "priority": "critical"},
                {"description": "Medium", "priority": "medium"},
            ],
        )
        md = registry.export_plan(plan["plan_id"])
        crit_pos = md.index("[critical]")
        med_pos = md.index("[medium]")
        low_pos = md.index("[low]")
        assert crit_pos < med_pos < low_pos


# ---------------------------------------------------------------------------
# Command registry tests
# ---------------------------------------------------------------------------


class TestCommandRegistrySpecs:
    def test_session_plan_commands_registered(self):
        from axiom_core.runner.command_registry import get_command

        commands = [
            "session-plan-create",
            "session-plans",
            "session-plan-show",
            "session-plan-export",
        ]
        for cmd_name in commands:
            cmd = get_command(cmd_name)
            assert cmd is not None, f"Command {cmd_name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_session_plan_create_has_evidence_outputs(self):
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-plan-create")
        assert cmd is not None
        names = [e.location for e in cmd.evidence_outputs]
        assert "session_plan_request.json" in names
        assert "session_plan_result.json" in names
        assert "session_plan.md" in names
        assert "pass_fail.json" in names


# ---------------------------------------------------------------------------
# Test selection engine mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_session_plan_registry_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST.get("src/axiom_core/session_plan_registry.py")
            == "tests/test_session_plan_registry.py"
        )
