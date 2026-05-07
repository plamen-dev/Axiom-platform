"""Tests for the SQLite-backed persistence layer."""

from uuid import uuid4

import pytest
from axiom_core.persistence import ExecutionTrace, Storage
from axiom_core.schemas import (
    Job,
    JobStatus,
    JobType,
    NormalizedJob,
    Plan,
    PlanStatus,
    QAReport,
    QAStatus,
    ScopeBoxDef,
    StepStatus,
    ToolResult,
    ToolStep,
    ViewRequirement,
)


@pytest.fixture
def store(tmp_path):
    """Create a fresh Storage instance backed by a temp SQLite file."""
    db_path = str(tmp_path / "test_axiom.db")
    return Storage(db_path=db_path)


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_job(store):
    job = Job(
        job_type=JobType.PROJECT_SETUP,
        firm_id="firm_a",
        source="EXCEL",
        raw_inputs={"key": "value"},
    )
    store.save_job(job)

    retrieved = store.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id
    assert retrieved.firm_id == "firm_a"
    assert retrieved.raw_inputs == {"key": "value"}
    assert retrieved.status == JobStatus.PENDING


def test_get_nonexistent_job(store):
    assert store.get_job(uuid4()) is None


def test_update_job_status(store):
    job = Job(job_type=JobType.PROJECT_SETUP, firm_id="firm_b")
    store.save_job(job)

    updated = store.update_job_status(job.job_id, JobStatus.COMPLETED)
    assert updated is not None
    assert updated.status == JobStatus.COMPLETED

    retrieved = store.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.status == JobStatus.COMPLETED


def test_update_nonexistent_job_status(store):
    assert store.update_job_status(uuid4(), JobStatus.FAILED) is None


def test_list_jobs(store):
    for i in range(5):
        store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id=f"firm_{i}"))

    jobs = store.list_jobs()
    assert len(jobs) == 5


def test_list_jobs_filter_by_status(store):
    j1 = Job(job_type=JobType.PROJECT_SETUP, firm_id="f")
    j2 = Job(job_type=JobType.PROJECT_SETUP, firm_id="f")
    store.save_job(j1)
    store.save_job(j2)
    store.update_job_status(j1.job_id, JobStatus.COMPLETED)

    completed = store.list_jobs(status=JobStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0].job_id == j1.job_id


def test_list_jobs_filter_by_firm(store):
    store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="alpha"))
    store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="beta"))

    alpha_jobs = store.list_jobs(firm_id="alpha")
    assert len(alpha_jobs) == 1
    assert alpha_jobs[0].firm_id == "alpha"


def test_list_jobs_limit(store):
    for _ in range(10):
        store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="f"))

    assert len(store.list_jobs(limit=3)) == 3


# ---------------------------------------------------------------------------
# Normalized Job CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_normalized_job(store):
    nj = NormalizedJob(
        job_id=uuid4(),
        job_type=JobType.PROJECT_SETUP,
        firm_id="firm_x",
        source="EXCEL",
        project_number="2024-001",
        project_name="Test Project",
        revit_version=2023,
        is_acc_project=True,
        views_required=[
            ViewRequirement(view_type_code="E - General"),
            ViewRequirement(view_type_code="M - HVAC"),
        ],
        scope_boxes=[
            ScopeBoxDef(name="Building A", copy_from_arch=True),
        ],
        engineer_stamps=["John Doe", "Jane Smith"],
    )
    store.save_normalized_job(nj)

    retrieved = store.get_normalized_job(nj.job_id)
    assert retrieved is not None
    assert retrieved.project_number == "2024-001"
    assert retrieved.revit_version == 2023
    assert retrieved.is_acc_project is True
    assert len(retrieved.views_required) == 2
    assert retrieved.views_required[0].view_type_code == "E - General"
    assert len(retrieved.scope_boxes) == 1
    assert retrieved.scope_boxes[0].name == "Building A"
    assert retrieved.engineer_stamps == ["John Doe", "Jane Smith"]


def test_get_nonexistent_normalized_job(store):
    assert store.get_normalized_job(uuid4()) is None


# ---------------------------------------------------------------------------
# Plan CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_plan(store):
    job_id = uuid4()
    plan = Plan(
        job_id=job_id,
        steps=[
            ToolStep(sequence=0, tool_name="CreateProject", args={"name": "P1"}),
            ToolStep(sequence=1, tool_name="CreateViews", args={"view_type_code": "E - General"}),
        ],
    )
    store.save_plan(plan)

    retrieved = store.get_plan(plan.plan_id)
    assert retrieved is not None
    assert retrieved.job_id == job_id
    assert retrieved.status == PlanStatus.DRAFT
    assert len(retrieved.steps) == 2
    assert retrieved.steps[0].tool_name == "CreateProject"


def test_get_plan_for_job(store):
    job_id = uuid4()
    plan = Plan(job_id=job_id, steps=[])
    store.save_plan(plan)

    retrieved = store.get_plan_for_job(job_id)
    assert retrieved is not None
    assert retrieved.plan_id == plan.plan_id


def test_update_plan_status(store):
    plan = Plan(job_id=uuid4(), steps=[])
    store.save_plan(plan)

    updated = store.update_plan_status(plan.plan_id, PlanStatus.APPROVED)
    assert updated is not None
    assert updated.status == PlanStatus.APPROVED


def test_list_plans(store):
    for _ in range(4):
        store.save_plan(Plan(job_id=uuid4(), steps=[]))

    assert len(store.list_plans()) == 4


def test_list_plans_filter_by_status(store):
    p1 = Plan(job_id=uuid4(), steps=[])
    p2 = Plan(job_id=uuid4(), steps=[])
    store.save_plan(p1)
    store.save_plan(p2)
    store.update_plan_status(p1.plan_id, PlanStatus.COMPLETED)

    completed = store.list_plans(status=PlanStatus.COMPLETED)
    assert len(completed) == 1


# ---------------------------------------------------------------------------
# Results CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_results(store):
    plan_id = uuid4()
    results = [
        ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=["obj_1"],
            duration_ms=150,
            output_data={"key": "val"},
        ),
        ToolResult(
            step_id=uuid4(),
            status=StepStatus.WARNING,
            warnings=["minor issue"],
            duration_ms=200,
        ),
    ]
    store.save_results(plan_id, results)

    retrieved = store.get_results(plan_id)
    assert retrieved is not None
    assert len(retrieved) == 2
    assert retrieved[0].status == StepStatus.SUCCESS
    assert retrieved[0].created_ids == ["obj_1"]
    assert retrieved[1].warnings == ["minor issue"]


def test_get_nonexistent_results(store):
    assert store.get_results(uuid4()) is None


# ---------------------------------------------------------------------------
# QA Report CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_qa_report(store):
    report = QAReport(
        plan_id=uuid4(),
        job_id=uuid4(),
        status=QAStatus.PASS,
        score=95.0,
        recommendations=["Check wiring"],
    )
    store.save_qa_report(report)

    retrieved = store.get_qa_report(report.report_id)
    assert retrieved is not None
    assert retrieved.status == QAStatus.PASS
    assert retrieved.score == 95.0
    assert retrieved.recommendations == ["Check wiring"]


def test_get_qa_report_for_plan(store):
    plan_id = uuid4()
    report = QAReport(plan_id=plan_id, job_id=uuid4(), status=QAStatus.WARN, score=80.0)
    store.save_qa_report(report)

    retrieved = store.get_qa_report_for_plan(plan_id)
    assert retrieved is not None
    assert retrieved.report_id == report.report_id


# ---------------------------------------------------------------------------
# Execution Trace CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_trace(store):
    trace = ExecutionTrace(
        trace_id=uuid4(),
        job_id=uuid4(),
        plan_id=uuid4(),
        results=[],
        status="COMPLETED",
    )
    store.save_trace(trace)

    retrieved = store.get_trace(trace.trace_id)
    assert retrieved is not None
    assert retrieved.status == "COMPLETED"


def test_get_trace_for_job(store):
    job_id = uuid4()
    trace = ExecutionTrace(trace_id=uuid4(), job_id=job_id, plan_id=uuid4())
    store.save_trace(trace)

    retrieved = store.get_trace_for_job(job_id)
    assert retrieved is not None
    assert retrieved.trace_id == trace.trace_id


# ---------------------------------------------------------------------------
# Statistics and clear
# ---------------------------------------------------------------------------


def test_statistics(store):
    store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="f"))
    store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="f"))
    store.save_plan(Plan(job_id=uuid4(), steps=[]))

    stats = store.get_statistics()
    assert stats["total_jobs"] == 2
    assert stats["total_plans"] == 1
    assert stats["total_qa_reports"] == 0
    assert "PENDING" in stats["jobs_by_status"]


def test_clear(store):
    store.save_job(Job(job_type=JobType.PROJECT_SETUP, firm_id="f"))
    store.save_plan(Plan(job_id=uuid4(), steps=[]))

    store.clear()

    assert store.list_jobs() == []
    assert store.list_plans() == []
    assert store.get_statistics()["total_jobs"] == 0


# ---------------------------------------------------------------------------
# Data persistence across Storage instances
# ---------------------------------------------------------------------------


def test_data_persists_across_instances(tmp_path):
    """Verify data survives when a new Storage instance is created."""
    db_path = str(tmp_path / "persist_test.db")

    store1 = Storage(db_path=db_path)
    job = Job(job_type=JobType.PROJECT_SETUP, firm_id="persist_firm")
    store1.save_job(job)

    store2 = Storage(db_path=db_path)
    retrieved = store2.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.firm_id == "persist_firm"


# ---------------------------------------------------------------------------
# WAL mode verification
# ---------------------------------------------------------------------------


def test_wal_mode_enabled(tmp_path):
    """Verify that WAL journal mode is active."""
    db_path = str(tmp_path / "wal_test.db")
    s = Storage(db_path=db_path)

    from sqlalchemy import text

    with s._session_factory() as session:
        result = session.execute(text("PRAGMA journal_mode")).scalar()
        assert result == "wal"
