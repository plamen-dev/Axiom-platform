"""Persistence Layer - In-memory storage for jobs, plans, and results.

This is a proof-of-concept implementation using in-memory storage.
Data will be lost when the application restarts.
For production, this would be replaced with SQLite or a cloud database.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from axiom_core.schemas import (
    Job,
    JobStatus,
    NormalizedJob,
    Plan,
    PlanStatus,
    QAReport,
    ToolResult,
)


class ExecutionTrace(BaseModel):
    """Complete trace of a job execution."""

    trace_id: UUID
    job_id: UUID
    plan_id: UUID
    results: list[ToolResult] = Field(default_factory=list)
    qa_report: Optional[QAReport] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"


class Storage:
    """In-memory storage for Axiom data.

    Note: This is a proof-of-concept implementation.
    Data will be lost when the application restarts.
    """

    def __init__(self):
        self.jobs: dict[UUID, Job] = {}
        self.normalized_jobs: dict[UUID, NormalizedJob] = {}
        self.plans: dict[UUID, Plan] = {}
        self.results: dict[UUID, list[ToolResult]] = {}
        self.qa_reports: dict[UUID, QAReport] = {}
        self.traces: dict[UUID, ExecutionTrace] = {}
        self.job_to_plan: dict[UUID, UUID] = {}

    def save_job(self, job: Job) -> Job:
        """Save a job to storage."""
        self.jobs[job.job_id] = job
        return job

    def get_job(self, job_id: UUID) -> Optional[Job]:
        """Get a job by ID."""
        return self.jobs.get(job_id)

    def update_job_status(self, job_id: UUID, status: JobStatus) -> Optional[Job]:
        """Update a job's status."""
        job = self.jobs.get(job_id)
        if job:
            job.status = status
        return job

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        firm_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Job]:
        """List jobs with optional filtering."""
        jobs = list(self.jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]
        if firm_id:
            jobs = [j for j in jobs if j.firm_id == firm_id]

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def save_normalized_job(self, normalized_job: NormalizedJob) -> NormalizedJob:
        """Save a normalized job to storage."""
        self.normalized_jobs[normalized_job.job_id] = normalized_job
        return normalized_job

    def get_normalized_job(self, job_id: UUID) -> Optional[NormalizedJob]:
        """Get a normalized job by ID."""
        return self.normalized_jobs.get(job_id)

    def save_plan(self, plan: Plan) -> Plan:
        """Save a plan to storage."""
        self.plans[plan.plan_id] = plan
        self.job_to_plan[plan.job_id] = plan.plan_id
        return plan

    def get_plan(self, plan_id: UUID) -> Optional[Plan]:
        """Get a plan by ID."""
        return self.plans.get(plan_id)

    def get_plan_for_job(self, job_id: UUID) -> Optional[Plan]:
        """Get the plan for a job."""
        plan_id = self.job_to_plan.get(job_id)
        if plan_id:
            return self.plans.get(plan_id)
        return None

    def update_plan_status(self, plan_id: UUID, status: PlanStatus) -> Optional[Plan]:
        """Update a plan's status."""
        plan = self.plans.get(plan_id)
        if plan:
            plan.status = status
        return plan

    def list_plans(
        self,
        status: Optional[PlanStatus] = None,
        limit: int = 100,
    ) -> list[Plan]:
        """List plans with optional filtering."""
        plans = list(self.plans.values())

        if status:
            plans = [p for p in plans if p.status == status]

        plans.sort(key=lambda p: p.created_at, reverse=True)
        return plans[:limit]

    def save_results(self, plan_id: UUID, results: list[ToolResult]) -> None:
        """Save execution results for a plan."""
        self.results[plan_id] = results

    def get_results(self, plan_id: UUID) -> Optional[list[ToolResult]]:
        """Get execution results for a plan."""
        return self.results.get(plan_id)

    def save_qa_report(self, report: QAReport) -> QAReport:
        """Save a QA report."""
        self.qa_reports[report.report_id] = report
        return report

    def get_qa_report(self, report_id: UUID) -> Optional[QAReport]:
        """Get a QA report by ID."""
        return self.qa_reports.get(report_id)

    def get_qa_report_for_plan(self, plan_id: UUID) -> Optional[QAReport]:
        """Get the QA report for a plan."""
        for report in self.qa_reports.values():
            if report.plan_id == plan_id:
                return report
        return None

    def save_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        """Save an execution trace."""
        self.traces[trace.trace_id] = trace
        return trace

    def get_trace(self, trace_id: UUID) -> Optional[ExecutionTrace]:
        """Get an execution trace by ID."""
        return self.traces.get(trace_id)

    def get_trace_for_job(self, job_id: UUID) -> Optional[ExecutionTrace]:
        """Get the execution trace for a job."""
        for trace in self.traces.values():
            if trace.job_id == job_id:
                return trace
        return None

    def get_statistics(self) -> dict[str, Any]:
        """Get storage statistics."""
        return {
            "total_jobs": len(self.jobs),
            "total_plans": len(self.plans),
            "total_qa_reports": len(self.qa_reports),
            "jobs_by_status": self._count_by_status(self.jobs, "status"),
            "plans_by_status": self._count_by_status(self.plans, "status"),
        }

    def _count_by_status(
        self, items: dict[UUID, Any], status_field: str
    ) -> dict[str, int]:
        """Count items by status."""
        counts: dict[str, int] = {}
        for item in items.values():
            status = getattr(item, status_field, None)
            if status:
                status_str = status.value if hasattr(status, "value") else str(status)
                counts[status_str] = counts.get(status_str, 0) + 1
        return counts

    def clear(self) -> None:
        """Clear all data from storage."""
        self.jobs.clear()
        self.normalized_jobs.clear()
        self.plans.clear()
        self.results.clear()
        self.qa_reports.clear()
        self.traces.clear()
        self.job_to_plan.clear()


storage = Storage()
