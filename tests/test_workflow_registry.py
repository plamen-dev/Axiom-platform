"""Tests for Workflow Knowledge Registry (PR #39).

Tests proving:
- workflows persist
- step ordering deterministic
- inputs and outputs captured
- cycles handled safely
"""

from __future__ import annotations

import json
import pathlib

import pytest
from axiom_core.workflow_registry import (
    WorkflowDefinition,
    WorkflowInput,
    WorkflowKnowledgeRegistry,
    WorkflowOutput,
    WorkflowRule,
    WorkflowStatus,
    WorkflowStep,
)


@pytest.fixture()
def db_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "test_workflows.db")


@pytest.fixture()
def registry(db_path: str) -> WorkflowKnowledgeRegistry:
    return WorkflowKnowledgeRegistry(db_path=db_path)


# ---------------------------------------------------------------------------
# Test: Workflows Persist
# ---------------------------------------------------------------------------


class TestWorkflowPersistence:
    """Workflow definitions roundtrip through SQLite correctly."""

    def test_register_and_retrieve(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="wf_001",
            workflow_name="MEP Load Calculation",
            description="Calculate electrical loads from room data",
            version="2.0",
            metadata={"domain": "electrical"},
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("wf_001")
        assert retrieved is not None
        assert retrieved.workflow_name == "MEP Load Calculation"
        assert retrieved.description == "Calculate electrical loads from room data"
        assert retrieved.version == "2.0"
        assert retrieved.status == WorkflowStatus.ACTIVE
        assert retrieved.metadata == {"domain": "electrical"}

    def test_update_existing(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="wf_up",
            workflow_name="Original Name",
        )
        registry.register_workflow(wf)

        wf.workflow_name = "Updated Name"
        wf.version = "3.0"
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("wf_up")
        assert retrieved is not None
        assert retrieved.workflow_name == "Updated Name"
        assert retrieved.version == "3.0"

    def test_removed_steps_deleted_on_update(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="stale_wf",
            workflow_name="Stale Test",
            steps=[
                WorkflowStep(step_id="s1", step_name="A", step_order=1),
                WorkflowStep(step_id="s2", step_name="B", step_order=2),
                WorkflowStep(step_id="s3", step_name="C", step_order=3),
            ],
            rules=[
                WorkflowRule(rule_id="r1", rule_name="R1", condition="x", action="y"),
                WorkflowRule(rule_id="r2", rule_name="R2", condition="a", action="b"),
            ],
        )
        registry.register_workflow(wf)

        # Re-register with fewer steps and rules
        wf.steps = [WorkflowStep(step_id="s1", step_name="A", step_order=1)]
        wf.rules = [WorkflowRule(rule_id="r1", rule_name="R1", condition="x", action="y")]
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("stale_wf")
        assert len(retrieved.steps) == 1
        assert retrieved.steps[0].step_id == "s1"
        assert len(retrieved.rules) == 1
        assert retrieved.rules[0].rule_id == "r1"

    def test_all_steps_removed_on_update(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="empty_up",
            workflow_name="Empty Steps",
            steps=[WorkflowStep(step_id="x1", step_name="X", step_order=1)],
        )
        registry.register_workflow(wf)

        wf.steps = []
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("empty_up")
        assert len(retrieved.steps) == 0

    def test_multiple_workflows(self, registry: WorkflowKnowledgeRegistry):
        for i in range(5):
            registry.register_workflow(WorkflowDefinition(
                workflow_id=f"wf_{i}",
                workflow_name=f"Workflow {i}",
            ))
        assert registry.workflow_count() == 5

    def test_unknown_id_returns_none(self, registry: WorkflowKnowledgeRegistry):
        assert registry.get_workflow("nonexistent") is None

    def test_empty_name_rejected(self, registry: WorkflowKnowledgeRegistry):
        with pytest.raises(ValueError, match="workflow_name must not be empty"):
            registry.register_workflow(WorkflowDefinition(
                workflow_id="bad",
                workflow_name="",
            ))

    def test_deprecate_workflow(self, registry: WorkflowKnowledgeRegistry):
        registry.register_workflow(WorkflowDefinition(
            workflow_id="dep_wf",
            workflow_name="Old Workflow",
        ))
        result = registry.deprecate("dep_wf")
        assert result is True

        # Excluded from default listing
        workflows = registry.list_workflows()
        ids = [w.workflow_id for w in workflows]
        assert "dep_wf" not in ids

        # Included with flag
        workflows = registry.list_workflows(include_deprecated=True)
        ids = [w.workflow_id for w in workflows]
        assert "dep_wf" in ids


# ---------------------------------------------------------------------------
# Test: Step Ordering Deterministic
# ---------------------------------------------------------------------------


class TestStepOrdering:
    """Steps are returned in deterministic order."""

    def test_steps_ordered_by_step_order(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="ordered",
            workflow_name="Grid Layout Workflow",
            steps=[
                WorkflowStep(step_id="s3", step_name="Sheets", step_order=3),
                WorkflowStep(step_id="s1", step_name="Grid Layout", step_order=1),
                WorkflowStep(step_id="s2", step_name="Levels", step_order=2),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("ordered")
        assert retrieved is not None
        step_names = [s.step_name for s in retrieved.steps]
        assert step_names == ["Grid Layout", "Levels", "Sheets"]

    def test_repeated_retrieval_deterministic(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="det",
            workflow_name="Deterministic Workflow",
            steps=[
                WorkflowStep(step_id="d1", step_name="Step A", step_order=1),
                WorkflowStep(step_id="d2", step_name="Step B", step_order=2),
                WorkflowStep(step_id="d3", step_name="Step C", step_order=3),
            ],
        )
        registry.register_workflow(wf)

        r1 = registry.get_workflow("det")
        r2 = registry.get_workflow("det")
        assert [s.step_id for s in r1.steps] == [s.step_id for s in r2.steps]

    def test_list_workflows_ordered_by_name(self, registry: WorkflowKnowledgeRegistry):
        registry.register_workflow(WorkflowDefinition(
            workflow_id="z", workflow_name="Zebra Workflow",
        ))
        registry.register_workflow(WorkflowDefinition(
            workflow_id="a", workflow_name="Apple Workflow",
        ))
        registry.register_workflow(WorkflowDefinition(
            workflow_id="m", workflow_name="Mango Workflow",
        ))

        workflows = registry.list_workflows()
        names = [w.workflow_name for w in workflows]
        assert names == ["Apple Workflow", "Mango Workflow", "Zebra Workflow"]


# ---------------------------------------------------------------------------
# Test: Inputs and Outputs Captured
# ---------------------------------------------------------------------------


class TestInputsOutputs:
    """Workflow steps correctly persist inputs and outputs."""

    def test_inputs_roundtrip(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="io_1",
            workflow_name="Input Test",
            steps=[
                WorkflowStep(
                    step_id="io_s1",
                    step_name="Load Calculation",
                    step_order=1,
                    inputs=[
                        WorkflowInput(name="room_name", description="Room identifier", required=True),
                        WorkflowInput(name="area_sqft", description="Room area", required=False),
                    ],
                    outputs=[
                        WorkflowOutput(name="lighting_load", description="Watts for lighting"),
                        WorkflowOutput(name="receptacle_load", description="Watts for receptacles"),
                    ],
                ),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("io_1")
        step = retrieved.steps[0]
        assert len(step.inputs) == 2
        assert step.inputs[0].name == "room_name"
        assert step.inputs[0].required is True
        assert step.inputs[1].name == "area_sqft"
        assert step.inputs[1].required is False
        assert len(step.outputs) == 2
        assert step.outputs[0].name == "lighting_load"
        assert step.outputs[1].name == "receptacle_load"

    def test_empty_inputs_outputs(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="io_empty",
            workflow_name="No IO Step",
            steps=[
                WorkflowStep(step_id="empty_s", step_name="Simple Step", step_order=1),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("io_empty")
        step = retrieved.steps[0]
        assert step.inputs == []
        assert step.outputs == []

    def test_depends_on_captured(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="dep_chain",
            workflow_name="Dependency Chain",
            steps=[
                WorkflowStep(step_id="dc_1", step_name="First", step_order=1),
                WorkflowStep(step_id="dc_2", step_name="Second", step_order=2, depends_on=["dc_1"]),
                WorkflowStep(step_id="dc_3", step_name="Third", step_order=3, depends_on=["dc_1", "dc_2"]),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("dep_chain")
        assert retrieved.steps[0].depends_on == []
        assert retrieved.steps[1].depends_on == ["dc_1"]
        assert retrieved.steps[2].depends_on == ["dc_1", "dc_2"]


# ---------------------------------------------------------------------------
# Test: Cycles Handled Safely
# ---------------------------------------------------------------------------


class TestCyclesSafe:
    """Circular step dependencies do not crash the system."""

    def test_self_reference_dependency(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="self_ref",
            workflow_name="Self Reference",
            steps=[
                WorkflowStep(step_id="sr_1", step_name="Self", step_order=1, depends_on=["sr_1"]),
            ],
        )
        # Should not crash — metadata only, no execution
        registry.register_workflow(wf)
        retrieved = registry.get_workflow("self_ref")
        assert retrieved is not None
        assert retrieved.steps[0].depends_on == ["sr_1"]

    def test_mutual_cycle_dependency(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="mutual",
            workflow_name="Mutual Cycle",
            steps=[
                WorkflowStep(step_id="mc_a", step_name="Step A", step_order=1, depends_on=["mc_b"]),
                WorkflowStep(step_id="mc_b", step_name="Step B", step_order=2, depends_on=["mc_a"]),
            ],
        )
        registry.register_workflow(wf)
        retrieved = registry.get_workflow("mutual")
        assert retrieved is not None
        assert retrieved.steps[0].depends_on == ["mc_b"]
        assert retrieved.steps[1].depends_on == ["mc_a"]

    def test_triangle_cycle_dependency(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="triangle",
            workflow_name="Triangle Cycle",
            steps=[
                WorkflowStep(step_id="t_a", step_name="A", step_order=1, depends_on=["t_c"]),
                WorkflowStep(step_id="t_b", step_name="B", step_order=2, depends_on=["t_a"]),
                WorkflowStep(step_id="t_c", step_name="C", step_order=3, depends_on=["t_b"]),
            ],
        )
        registry.register_workflow(wf)
        retrieved = registry.get_workflow("triangle")
        assert retrieved is not None
        assert len(retrieved.steps) == 3


# ---------------------------------------------------------------------------
# Test: Rules
# ---------------------------------------------------------------------------


class TestWorkflowRules:
    """Workflow rules persist and are ordered by priority."""

    def test_rules_persist(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="rules_wf",
            workflow_name="Rules Workflow",
            rules=[
                WorkflowRule(
                    rule_id="r1", rule_name="Min Area Check",
                    condition="area_sqft < 50", action="warn_small_room",
                    priority=1, notes="Flag unusually small rooms",
                ),
                WorkflowRule(
                    rule_id="r2", rule_name="Max Load Check",
                    condition="total_load > 5000", action="require_review",
                    priority=2,
                ),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("rules_wf")
        assert len(retrieved.rules) == 2
        assert retrieved.rules[0].rule_name == "Min Area Check"
        assert retrieved.rules[0].condition == "area_sqft < 50"
        assert retrieved.rules[0].action == "warn_small_room"
        assert retrieved.rules[0].priority == 1
        assert retrieved.rules[0].notes == "Flag unusually small rooms"
        assert retrieved.rules[1].rule_name == "Max Load Check"
        assert retrieved.rules[1].priority == 2

    def test_rules_ordered_by_priority(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="priority_wf",
            workflow_name="Priority Rules",
            rules=[
                WorkflowRule(rule_id="p3", rule_name="Low Priority", condition="x", action="y", priority=3),
                WorkflowRule(rule_id="p1", rule_name="High Priority", condition="a", action="b", priority=1),
                WorkflowRule(rule_id="p2", rule_name="Mid Priority", condition="c", action="d", priority=2),
            ],
        )
        registry.register_workflow(wf)

        retrieved = registry.get_workflow("priority_wf")
        priorities = [r.priority for r in retrieved.rules]
        assert priorities == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test: JSON Output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON serialization is valid and complete."""

    def test_workflow_json_valid(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="json_wf",
            workflow_name="JSON Test",
            steps=[WorkflowStep(step_id="js1", step_name="Step 1", step_order=1)],
            rules=[WorkflowRule(rule_id="jr1", rule_name="Rule 1", condition="x", action="y")],
        )
        registry.register_workflow(wf)

        output = registry.to_json()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert "workflow_id" in data[0]
        assert "steps" in data[0]
        assert "rules" in data[0]

    def test_to_dict_complete(self, registry: WorkflowKnowledgeRegistry):
        wf = WorkflowDefinition(
            workflow_id="dict_wf",
            workflow_name="Dict Test",
            description="Test description",
            steps=[
                WorkflowStep(
                    step_id="ds1", step_name="S1", step_order=1,
                    inputs=[WorkflowInput(name="in1")],
                    outputs=[WorkflowOutput(name="out1")],
                ),
            ],
        )
        d = wf.to_dict()
        required_fields = [
            "workflow_id", "workflow_name", "description", "status",
            "version", "created_at", "updated_at", "metadata", "steps", "rules",
        ]
        for f in required_fields:
            assert f in d, f"Missing field: {f}"
        assert d["steps"][0]["inputs"][0]["name"] == "in1"
        assert d["steps"][0]["outputs"][0]["name"] == "out1"

    def test_name_filter_works(self, registry: WorkflowKnowledgeRegistry):
        registry.register_workflow(WorkflowDefinition(
            workflow_id="nf_1", workflow_name="Grid Layout Workflow",
        ))
        registry.register_workflow(WorkflowDefinition(
            workflow_id="nf_2", workflow_name="MEP Load Workflow",
        ))

        results = registry.list_workflows(name_filter="Grid")
        assert len(results) == 1
        assert results[0].workflow_id == "nf_1"

    def test_name_filter_sql_wildcard_escaped(self, registry: WorkflowKnowledgeRegistry):
        registry.register_workflow(WorkflowDefinition(
            workflow_id="wc_1", workflow_name="100% Complete Flow",
        ))
        registry.register_workflow(WorkflowDefinition(
            workflow_id="wc_2", workflow_name="Other Flow",
        ))

        results = registry.list_workflows(name_filter="%")
        assert len(results) == 1
        assert results[0].workflow_id == "wc_1"
