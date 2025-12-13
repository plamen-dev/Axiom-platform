"""Tests for core schemas."""

from uuid import uuid4

from axiom_core.schemas import (
    Job,
    JobStatus,
    JobType,
    NormalizedJob,
    Plan,
    PlanStatus,
    ScopeBoxDef,
    StepStatus,
    ToolStep,
    ViewRequirement,
)


def test_job_creation():
    """Test creating a Job."""
    job = Job(
        job_type=JobType.PROJECT_SETUP,
        firm_id="test_firm",
        source="EXCEL",
        raw_inputs={"project_name": "Test Project"},
    )

    assert job.job_id is not None
    assert job.job_type == JobType.PROJECT_SETUP
    assert job.firm_id == "test_firm"
    assert job.status == JobStatus.PENDING


def test_normalized_job_creation():
    """Test creating a NormalizedJob."""
    job = NormalizedJob(
        job_id=uuid4(),
        job_type=JobType.PROJECT_SETUP,
        firm_id="test_firm",
        source="EXCEL",
        project_number="2024-001",
        project_name="Test Project",
        revit_version=2023,
        is_acc_project=False,
        views_required=[
            ViewRequirement(view_type_code="E - General"),
            ViewRequirement(view_type_code="M - HVAC"),
        ],
        scope_boxes=[
            ScopeBoxDef(name="Building A", copy_from_arch=True),
        ],
    )

    assert job.project_number == "2024-001"
    assert job.revit_version == 2023
    assert len(job.views_required) == 2
    assert len(job.scope_boxes) == 1


def test_plan_creation():
    """Test creating a Plan with steps."""
    job_id = uuid4()
    plan = Plan(
        job_id=job_id,
        steps=[
            ToolStep(
                sequence=0,
                tool_name="CreateProject",
                args={"project_name": "Test"},
            ),
            ToolStep(
                sequence=1,
                tool_name="CreateViews",
                args={"view_type_code": "E - General"},
            ),
        ],
    )

    assert plan.job_id == job_id
    assert plan.status == PlanStatus.DRAFT
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "CreateProject"
    assert plan.steps[0].status == StepStatus.PENDING


def test_tool_step_defaults():
    """Test ToolStep default values."""
    step = ToolStep(
        sequence=0,
        tool_name="TestTool",
        args={},
    )

    assert step.step_id is not None
    assert step.requires_approval is False
    assert step.timeout_ms == 60000
    assert step.status == StepStatus.PENDING
