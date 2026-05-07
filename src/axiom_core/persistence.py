"""Persistence Layer - SQLite-backed storage for jobs, plans, and results.

Uses SQLAlchemy ORM with WAL-mode SQLite for durable, concurrent-safe
storage. The public interface is identical to the original in-memory
implementation so existing callers (CLI, orchestrator) require no changes.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import (
    ExecutionTraceRow,
    JobRow,
    NormalizedJobRow,
    PlanRow,
    QAReportRow,
    ResultsRow,
)
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
    ToolResult,
    ToolStep,
    ViewRequirement,
    Violation,
)

# ---------------------------------------------------------------------------
# ExecutionTrace Pydantic model (kept here for backward-compat)
# ---------------------------------------------------------------------------


class ExecutionTrace(BaseModel):
    """Complete trace of a job execution."""

    trace_id: UUID
    job_id: UUID
    plan_id: UUID
    results: list[ToolResult] = Field(default_factory=list)
    qa_report: Optional[QAReport] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"


# ---------------------------------------------------------------------------
# Pydantic <-> ORM converters
# ---------------------------------------------------------------------------


def _str_uuid(u: UUID) -> str:
    return str(u)


def _to_uuid(s: str) -> UUID:
    return UUID(s)


def _job_to_row(job: Job) -> JobRow:
    row = JobRow(
        job_id=_str_uuid(job.job_id),
        job_type=job.job_type.value,
        firm_id=job.firm_id,
        source=job.source,
        created_at=job.created_at,
        status=job.status.value,
    )
    row.set_raw_inputs(job.raw_inputs)
    return row


def _row_to_job(row: JobRow) -> Job:
    return Job(
        job_id=_to_uuid(row.job_id),
        job_type=JobType(row.job_type),
        firm_id=row.firm_id,
        source=row.source,
        raw_inputs=row.get_raw_inputs(),
        created_at=row.created_at,
        status=JobStatus(row.status),
    )


def _normalized_job_to_row(nj: NormalizedJob) -> NormalizedJobRow:
    return NormalizedJobRow(
        job_id=_str_uuid(nj.job_id),
        job_type=nj.job_type.value,
        firm_id=nj.firm_id,
        source=nj.source,
        project_number=nj.project_number,
        project_name=nj.project_name,
        revit_version=nj.revit_version,
        is_acc_project=nj.is_acc_project,
        template_path=nj.template_path,
        arch_link_paths_json=json.dumps(nj.arch_link_paths),
        scope_boxes_json=json.dumps([sb.model_dump() for sb in nj.scope_boxes]),
        views_required_json=json.dumps([vr.model_dump() for vr in nj.views_required]),
        sheet_list_path=nj.sheet_list_path,
        engineer_stamps_json=json.dumps(nj.engineer_stamps),
        team_assignments=nj.team_assignments,
        bep_path=nj.bep_path,
        phase_scope=nj.phase_scope,
        additional_comments=nj.additional_comments,
        created_at=nj.created_at,
        normalized_at=nj.normalized_at,
    )


def _row_to_normalized_job(row: NormalizedJobRow) -> NormalizedJob:
    return NormalizedJob(
        job_id=_to_uuid(row.job_id),
        job_type=JobType(row.job_type),
        firm_id=row.firm_id,
        source=row.source,
        project_number=row.project_number,
        project_name=row.project_name,
        revit_version=row.revit_version,
        is_acc_project=row.is_acc_project,
        template_path=row.template_path,
        arch_link_paths=json.loads(row.arch_link_paths_json),
        scope_boxes=[ScopeBoxDef(**sb) for sb in json.loads(row.scope_boxes_json)],
        views_required=[ViewRequirement(**vr) for vr in json.loads(row.views_required_json)],
        sheet_list_path=row.sheet_list_path,
        engineer_stamps=json.loads(row.engineer_stamps_json),
        team_assignments=row.team_assignments,
        bep_path=row.bep_path,
        phase_scope=row.phase_scope,
        additional_comments=row.additional_comments,
        created_at=row.created_at,
        normalized_at=row.normalized_at,
    )


def _plan_to_row(plan: Plan) -> PlanRow:
    return PlanRow(
        plan_id=_str_uuid(plan.plan_id),
        job_id=_str_uuid(plan.job_id),
        version=plan.version,
        steps_json=json.dumps([s.model_dump(mode="json") for s in plan.steps]),
        status=plan.status.value,
        created_at=plan.created_at,
    )


def _row_to_plan(row: PlanRow) -> Plan:
    raw_steps = json.loads(row.steps_json)
    steps = [ToolStep(**s) for s in raw_steps]
    return Plan(
        plan_id=_to_uuid(row.plan_id),
        job_id=_to_uuid(row.job_id),
        version=row.version,
        steps=steps,
        status=PlanStatus(row.status),
        created_at=row.created_at,
    )


def _results_to_row(plan_id: UUID, results: list[ToolResult]) -> ResultsRow:
    return ResultsRow(
        plan_id=_str_uuid(plan_id),
        results_json=json.dumps([r.model_dump(mode="json") for r in results]),
    )


def _row_to_results(row: ResultsRow) -> list[ToolResult]:
    return [ToolResult(**r) for r in json.loads(row.results_json)]


def _qa_report_to_row(report: QAReport) -> QAReportRow:
    return QAReportRow(
        report_id=_str_uuid(report.report_id),
        plan_id=_str_uuid(report.plan_id),
        job_id=_str_uuid(report.job_id),
        status=report.status.value,
        score=report.score,
        violations_json=json.dumps([v.model_dump(mode="json") for v in report.violations]),
        recommendations_json=json.dumps(report.recommendations),
        created_at=report.created_at,
    )


def _row_to_qa_report(row: QAReportRow) -> QAReport:
    return QAReport(
        report_id=_to_uuid(row.report_id),
        plan_id=_to_uuid(row.plan_id),
        job_id=_to_uuid(row.job_id),
        status=QAStatus(row.status),
        score=row.score,
        violations=[Violation(**v) for v in json.loads(row.violations_json)],
        recommendations=json.loads(row.recommendations_json),
        created_at=row.created_at,
    )


def _trace_to_row(trace: ExecutionTrace) -> ExecutionTraceRow:
    return ExecutionTraceRow(
        trace_id=_str_uuid(trace.trace_id),
        job_id=_str_uuid(trace.job_id),
        plan_id=_str_uuid(trace.plan_id),
        results_json=json.dumps([r.model_dump(mode="json") for r in trace.results]),
        qa_report_json=(
            json.dumps(trace.qa_report.model_dump(mode="json")) if trace.qa_report else None
        ),
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        status=trace.status,
    )


def _row_to_trace(row: ExecutionTraceRow) -> ExecutionTrace:
    qa_report = None
    if row.qa_report_json:
        qa_report = QAReport(**json.loads(row.qa_report_json))

    return ExecutionTrace(
        trace_id=_to_uuid(row.trace_id),
        job_id=_to_uuid(row.job_id),
        plan_id=_to_uuid(row.plan_id),
        results=[ToolResult(**r) for r in json.loads(row.results_json)],
        qa_report=qa_report,
        started_at=row.started_at,
        completed_at=row.completed_at,
        status=row.status,
    )


# ---------------------------------------------------------------------------
# Storage class -- same public API as the original in-memory version
# ---------------------------------------------------------------------------


class Storage:
    """SQLite-backed storage for Axiom data.

    Drop-in replacement for the original in-memory Storage class.
    Data survives application restarts and is stored in a local SQLite
    database with WAL mode enabled for concurrent access.
    """

    def __init__(self, db_path: str | None = None):
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    # -- Jobs ---------------------------------------------------------------

    def save_job(self, job: Job) -> Job:
        """Save a job to storage."""
        with get_session(self._session_factory) as session:
            row = _job_to_row(job)
            session.merge(row)
        return job

    def get_job(self, job_id: UUID) -> Optional[Job]:
        """Get a job by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(JobRow, _str_uuid(job_id))
            return _row_to_job(row) if row else None

    def update_job_status(self, job_id: UUID, status: JobStatus) -> Optional[Job]:
        """Update a job's status."""
        with get_session(self._session_factory) as session:
            row = session.get(JobRow, _str_uuid(job_id))
            if row:
                row.status = status.value
                return _row_to_job(row)
            return None

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        firm_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs with optional filtering."""
        with get_session(self._session_factory) as session:
            query = session.query(JobRow)
            if status:
                query = query.filter(JobRow.status == status.value)
            if firm_id:
                query = query.filter(JobRow.firm_id == firm_id)
            query = query.order_by(JobRow.created_at.desc()).limit(limit)
            return [_row_to_job(r) for r in query.all()]

    # -- Normalized Jobs ----------------------------------------------------

    def save_normalized_job(self, normalized_job: NormalizedJob) -> NormalizedJob:
        """Save a normalized job to storage."""
        with get_session(self._session_factory) as session:
            row = _normalized_job_to_row(normalized_job)
            session.merge(row)
        return normalized_job

    def get_normalized_job(self, job_id: UUID) -> Optional[NormalizedJob]:
        """Get a normalized job by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(NormalizedJobRow, _str_uuid(job_id))
            return _row_to_normalized_job(row) if row else None

    # -- Plans --------------------------------------------------------------

    def save_plan(self, plan: Plan) -> Plan:
        """Save a plan to storage."""
        with get_session(self._session_factory) as session:
            row = _plan_to_row(plan)
            session.merge(row)
        return plan

    def get_plan(self, plan_id: UUID) -> Optional[Plan]:
        """Get a plan by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(PlanRow, _str_uuid(plan_id))
            return _row_to_plan(row) if row else None

    def get_plan_for_job(self, job_id: UUID) -> Optional[Plan]:
        """Get the plan for a job."""
        with get_session(self._session_factory) as session:
            row = session.query(PlanRow).filter(PlanRow.job_id == _str_uuid(job_id)).first()
            return _row_to_plan(row) if row else None

    def update_plan_status(self, plan_id: UUID, status: PlanStatus) -> Optional[Plan]:
        """Update a plan's status."""
        with get_session(self._session_factory) as session:
            row = session.get(PlanRow, _str_uuid(plan_id))
            if row:
                row.status = status.value
                return _row_to_plan(row)
            return None

    def list_plans(
        self,
        status: Optional[PlanStatus] = None,
        limit: int = 100,
    ) -> list[Plan]:
        """List plans with optional filtering."""
        with get_session(self._session_factory) as session:
            query = session.query(PlanRow)
            if status:
                query = query.filter(PlanRow.status == status.value)
            query = query.order_by(PlanRow.created_at.desc()).limit(limit)
            return [_row_to_plan(r) for r in query.all()]

    # -- Results ------------------------------------------------------------

    def save_results(self, plan_id: UUID, results: list[ToolResult]) -> None:
        """Save execution results for a plan."""
        with get_session(self._session_factory) as session:
            row = _results_to_row(plan_id, results)
            session.merge(row)

    def get_results(self, plan_id: UUID) -> Optional[list[ToolResult]]:
        """Get execution results for a plan."""
        with get_session(self._session_factory) as session:
            row = session.get(ResultsRow, _str_uuid(plan_id))
            return _row_to_results(row) if row else None

    # -- QA Reports ---------------------------------------------------------

    def save_qa_report(self, report: QAReport) -> QAReport:
        """Save a QA report."""
        with get_session(self._session_factory) as session:
            row = _qa_report_to_row(report)
            session.merge(row)
        return report

    def get_qa_report(self, report_id: UUID) -> Optional[QAReport]:
        """Get a QA report by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(QAReportRow, _str_uuid(report_id))
            return _row_to_qa_report(row) if row else None

    def get_qa_report_for_plan(self, plan_id: UUID) -> Optional[QAReport]:
        """Get the QA report for a plan."""
        with get_session(self._session_factory) as session:
            row = (
                session.query(QAReportRow).filter(QAReportRow.plan_id == _str_uuid(plan_id)).first()
            )
            return _row_to_qa_report(row) if row else None

    # -- Traces -------------------------------------------------------------

    def save_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        """Save an execution trace."""
        with get_session(self._session_factory) as session:
            row = _trace_to_row(trace)
            session.merge(row)
        return trace

    def get_trace(self, trace_id: UUID) -> Optional[ExecutionTrace]:
        """Get an execution trace by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(ExecutionTraceRow, _str_uuid(trace_id))
            return _row_to_trace(row) if row else None

    def get_trace_for_job(self, job_id: UUID) -> Optional[ExecutionTrace]:
        """Get the execution trace for a job."""
        with get_session(self._session_factory) as session:
            row = (
                session.query(ExecutionTraceRow)
                .filter(ExecutionTraceRow.job_id == _str_uuid(job_id))
                .first()
            )
            return _row_to_trace(row) if row else None

    # -- Statistics ---------------------------------------------------------

    def get_statistics(self) -> dict[str, Any]:
        """Get storage statistics."""
        with get_session(self._session_factory) as session:
            total_jobs = session.query(JobRow).count()
            total_plans = session.query(PlanRow).count()
            total_qa = session.query(QAReportRow).count()

            jobs_by_status: dict[str, int] = {}
            for row in session.query(JobRow.status).all():
                jobs_by_status[row[0]] = jobs_by_status.get(row[0], 0) + 1

            plans_by_status: dict[str, int] = {}
            for row in session.query(PlanRow.status).all():
                plans_by_status[row[0]] = plans_by_status.get(row[0], 0) + 1

        return {
            "total_jobs": total_jobs,
            "total_plans": total_plans,
            "total_qa_reports": total_qa,
            "jobs_by_status": jobs_by_status,
            "plans_by_status": plans_by_status,
        }

    def clear(self) -> None:
        """Clear all data from storage."""
        with get_session(self._session_factory) as session:
            session.query(ExecutionTraceRow).delete()
            session.query(QAReportRow).delete()
            session.query(ResultsRow).delete()
            session.query(PlanRow).delete()
            session.query(NormalizedJobRow).delete()
            session.query(JobRow).delete()


# ---------------------------------------------------------------------------
# Module-level singleton (drop-in replacement)
# ---------------------------------------------------------------------------

storage = Storage()
