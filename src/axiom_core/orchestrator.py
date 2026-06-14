"""Orchestration Layer - Converts jobs into plans and coordinates execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from axiom_core.mcp_layer import MCPLayer
    from axiom_core.persistence import Storage

from axiom_core.schemas import (
    JobType,
    NormalizedJob,
    Plan,
    PlanStatus,
    QAReport,
    QAStatus,
    StepStatus,
    ToolResult,
    ToolStep,
)


class PlanTemplate:
    """Template for generating plans from jobs."""

    @staticmethod
    def get_project_setup_steps(job: NormalizedJob) -> list[ToolStep]:
        """Generate steps for a PROJECT_SETUP job."""
        steps = []
        sequence = 0

        steps.append(
            ToolStep(
                sequence=sequence,
                tool_name="ValidateInputs",
                args={"job_id": str(job.job_id)},
                preconditions=[],
                expected_outputs=["validation_result"],
                requires_approval=False,
                timeout_ms=5000,
            )
        )
        sequence += 1

        steps.append(
            ToolStep(
                sequence=sequence,
                tool_name="CreateProject",
                args={
                    "project_name": job.project_name,
                    "project_number": job.project_number,
                    "revit_version": job.revit_version,
                    "template_path": job.template_path,
                },
                preconditions=["ValidateInputs.success"],
                expected_outputs=["project_path", "document_id"],
                requires_approval=False,
                timeout_ms=60000,
            )
        )
        sequence += 1

        if job.arch_link_paths:
            for i, link_path in enumerate(job.arch_link_paths):
                steps.append(
                    ToolStep(
                        sequence=sequence,
                        tool_name="LoadArchLink",
                        args={
                            "link_path": link_path,
                            "link_index": i,
                        },
                        preconditions=["CreateProject.success"],
                        expected_outputs=["link_id", "link_name"],
                        requires_approval=False,
                        timeout_ms=120000,
                    )
                )
                sequence += 1

        steps.append(
            ToolStep(
                sequence=sequence,
                tool_name="SetCoordinates",
                args={
                    "coordinate_mode": "shared" if job.is_acc_project else "project",
                },
                preconditions=["CreateProject.success"],
                expected_outputs=["coordinate_status"],
                requires_approval=False,
                timeout_ms=30000,
            )
        )
        sequence += 1

        if job.scope_boxes:
            for scope_box in job.scope_boxes:
                steps.append(
                    ToolStep(
                        sequence=sequence,
                        tool_name="CreateScopeBox",
                        args={
                            "name": scope_box.name,
                            "copy_from_arch": scope_box.copy_from_arch,
                            "levels": scope_box.levels,
                        },
                        preconditions=["SetCoordinates.success"],
                        expected_outputs=["scope_box_id"],
                        requires_approval=False,
                        timeout_ms=30000,
                    )
                )
                sequence += 1

        for view_req in job.views_required:
            steps.append(
                ToolStep(
                    sequence=sequence,
                    tool_name="CreateViews",
                    args={
                        "view_type_code": view_req.view_type_code,
                        "levels": view_req.levels,
                    },
                    preconditions=["SetCoordinates.success"],
                    expected_outputs=["view_ids"],
                    requires_approval=False,
                    timeout_ms=60000,
                )
            )
            sequence += 1

        if job.sheet_list_path:
            steps.append(
                ToolStep(
                    sequence=sequence,
                    tool_name="CreateSheets",
                    args={
                        "sheet_list_path": job.sheet_list_path,
                    },
                    preconditions=["CreateViews.success"],
                    expected_outputs=["sheet_ids"],
                    requires_approval=False,
                    timeout_ms=120000,
                )
            )
            sequence += 1

        steps.append(
            ToolStep(
                sequence=sequence,
                tool_name="RunBackgroundDiagnostic",
                args={},
                preconditions=["CreateProject.success"],
                expected_outputs=["diagnostic_view_id", "anomalies"],
                requires_approval=False,
                timeout_ms=180000,
            )
        )
        sequence += 1

        steps.append(
            ToolStep(
                sequence=sequence,
                tool_name="GenerateReport",
                args={"job_id": str(job.job_id)},
                preconditions=[],
                expected_outputs=["report"],
                requires_approval=False,
                timeout_ms=10000,
            )
        )

        return steps


class Orchestrator:
    """Central coordinator for job execution."""

    def __init__(
        self,
        mcp_layer: Optional["MCPLayer"] = None,
        storage: Optional["Storage"] = None,
    ):
        self.mcp_layer = mcp_layer
        self.storage = storage
        self.plans: dict[UUID, Plan] = {}
        self.results: dict[UUID, list[ToolResult]] = {}

    def generate_plan(self, job: NormalizedJob) -> Plan:
        """Generate an execution plan from a normalized job."""
        if job.job_type == JobType.PROJECT_SETUP:
            steps = PlanTemplate.get_project_setup_steps(job)
        else:
            steps = []

        plan = Plan(
            job_id=job.job_id,
            steps=steps,
            status=PlanStatus.DRAFT,
        )

        self.plans[plan.plan_id] = plan
        return plan

    def simulate_plan(self, plan: Plan) -> tuple[Plan, list[ToolResult]]:
        """Simulate plan execution in sandbox mode."""
        plan.status = PlanStatus.SIMULATING
        results = []

        for step in plan.steps:
            if self.mcp_layer:
                result = self.mcp_layer.execute_tool(step.tool_name, step.args, simulate=True)
            else:
                result = ToolResult(
                    step_id=step.step_id,
                    status=StepStatus.SUCCESS,
                    duration_ms=100,
                    output_data={"simulated": True},
                )

            results.append(result)
            step.status = result.status

            if result.status == StepStatus.FAILED:
                plan.status = PlanStatus.SIMULATION_FAILED
                break

        if plan.status == PlanStatus.SIMULATING:
            plan.status = PlanStatus.SIMULATION_PASSED

        self.results[plan.plan_id] = results
        if self.storage is not None:
            self.storage.save_plan(plan)
        return plan, results

    def execute_plan(self, plan: Plan) -> tuple[Plan, list[ToolResult]]:
        """Execute plan against production."""
        if plan.status != PlanStatus.SIMULATION_PASSED:
            raise ValueError("Plan must pass simulation before execution")

        plan.status = PlanStatus.EXECUTING
        results = []

        for step in plan.steps:
            step.status = StepStatus.RUNNING

            if self.mcp_layer:
                result = self.mcp_layer.execute_tool(step.tool_name, step.args, simulate=False)
            else:
                result = ToolResult(
                    step_id=step.step_id,
                    status=StepStatus.SUCCESS,
                    duration_ms=100,
                    output_data={"executed": True},
                )

            results.append(result)
            step.status = result.status

            if result.status == StepStatus.FAILED:
                plan.status = PlanStatus.FAILED
                break

        if plan.status == PlanStatus.EXECUTING:
            plan.status = PlanStatus.COMPLETED

        self.results[plan.plan_id] = results
        if self.storage is not None:
            self.storage.save_plan(plan)
        return plan, results

    def evaluate_results(self, plan: Plan, results: list[ToolResult]) -> QAReport:
        """Evaluate execution results and produce QA report."""
        violations = []
        score = 100.0

        failed_steps = [r for r in results if r.status == StepStatus.FAILED]
        warning_steps = [r for r in results if r.status == StepStatus.WARNING]

        score -= len(failed_steps) * 20
        score -= len(warning_steps) * 5

        if failed_steps:
            status = QAStatus.FAIL
        elif warning_steps:
            status = QAStatus.WARN
        else:
            status = QAStatus.PASS

        return QAReport(
            plan_id=plan.plan_id,
            job_id=plan.job_id,
            status=status,
            score=max(0, score),
            violations=violations,
            recommendations=[],
        )

    def get_plan(self, plan_id: UUID) -> Optional[Plan]:
        """Get a plan by ID."""
        return self.plans.get(plan_id)

    def get_results(self, plan_id: UUID) -> Optional[list[ToolResult]]:
        """Get results for a plan."""
        return self.results.get(plan_id)
