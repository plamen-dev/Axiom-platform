"""Tests for the orchestrator."""

from uuid import uuid4

from axiom_core.mcp_layer import MCPLayer
from axiom_core.orchestrator import Orchestrator
from axiom_core.schemas import (
    JobType,
    NormalizedJob,
    PlanStatus,
    StepStatus,
    ViewRequirement,
)


def test_generate_plan_project_setup():
    """Test generating a plan for PROJECT_SETUP job."""
    job = NormalizedJob(
        job_id=uuid4(),
        job_type=JobType.PROJECT_SETUP,
        firm_id="test_firm",
        source="EXCEL",
        project_number="2024-001",
        project_name="Test Project",
        revit_version=2023,
        views_required=[
            ViewRequirement(view_type_code="E - General"),
            ViewRequirement(view_type_code="M - HVAC"),
        ],
    )

    orchestrator = Orchestrator()
    plan = orchestrator.generate_plan(job)

    assert plan.job_id == job.job_id
    assert plan.status == PlanStatus.DRAFT
    assert len(plan.steps) > 0

    tool_names = [step.tool_name for step in plan.steps]
    assert "ValidateInputs" in tool_names
    assert "CreateProject" in tool_names
    assert "CreateViews" in tool_names


def test_simulate_plan():
    """Test simulating a plan."""
    job = NormalizedJob(
        job_id=uuid4(),
        job_type=JobType.PROJECT_SETUP,
        firm_id="test_firm",
        source="EXCEL",
        project_number="2024-001",
        project_name="Test Project",
        revit_version=2023,
        views_required=[ViewRequirement(view_type_code="E - General")],
    )

    mcp = MCPLayer(revit_version=2023)
    orchestrator = Orchestrator(mcp_layer=mcp)

    plan = orchestrator.generate_plan(job)
    plan, results = orchestrator.simulate_plan(plan)

    assert plan.status == PlanStatus.SIMULATION_PASSED
    assert len(results) == len(plan.steps)
    assert all(r.status == StepStatus.SUCCESS for r in results)


def test_evaluate_results():
    """Test evaluating execution results."""
    job = NormalizedJob(
        job_id=uuid4(),
        job_type=JobType.PROJECT_SETUP,
        firm_id="test_firm",
        source="EXCEL",
        project_number="2024-001",
        project_name="Test Project",
        revit_version=2023,
        views_required=[ViewRequirement(view_type_code="E - General")],
    )

    mcp = MCPLayer(revit_version=2023)
    orchestrator = Orchestrator(mcp_layer=mcp)

    plan = orchestrator.generate_plan(job)
    plan, results = orchestrator.simulate_plan(plan)
    qa_report = orchestrator.evaluate_results(plan, results)

    assert qa_report.plan_id == plan.plan_id
    assert qa_report.job_id == job.job_id
    assert qa_report.score == 100.0
