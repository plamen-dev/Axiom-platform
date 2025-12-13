"""Core data schemas for the Axiom platform."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobType(str, Enum):
    """Types of jobs that can be submitted."""

    PROJECT_SETUP = "PROJECT_SETUP"
    DEVICE_PLACEMENT = "DEVICE_PLACEMENT"
    VIEW_CREATION = "VIEW_CREATION"
    SHEET_CREATION = "SHEET_CREATION"


class JobStatus(str, Enum):
    """Status of a job through its lifecycle."""

    PENDING = "PENDING"
    NORMALIZING = "NORMALIZING"
    PLANNING = "PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    SIMULATING = "SIMULATING"
    QA_REVIEW = "QA_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Job(BaseModel):
    """Raw job as submitted by user."""

    job_id: UUID = Field(default_factory=uuid4)
    job_type: JobType
    firm_id: str
    source: str = "EXCEL"
    raw_inputs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: JobStatus = JobStatus.PENDING


class ScopeBoxDef(BaseModel):
    """Definition for a scope box to create."""

    name: str
    copy_from_arch: bool = True
    levels: list[str] = Field(default_factory=list)


class ViewRequirement(BaseModel):
    """A view type requirement."""

    view_type_code: str
    levels: list[str] = Field(default_factory=list)


class NormalizedJob(BaseModel):
    """Validated and normalized job ready for planning."""

    job_id: UUID
    job_type: JobType
    firm_id: str
    source: str

    project_number: str
    project_name: str
    revit_version: int
    is_acc_project: bool = False

    template_path: Optional[str] = None
    arch_link_paths: list[str] = Field(default_factory=list)
    scope_boxes: list[ScopeBoxDef] = Field(default_factory=list)
    views_required: list[ViewRequirement] = Field(default_factory=list)
    sheet_list_path: Optional[str] = None

    engineer_stamps: list[str] = Field(default_factory=list)
    team_assignments: Optional[str] = None
    bep_path: Optional[str] = None
    phase_scope: bool = False
    additional_comments: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    normalized_at: datetime = Field(default_factory=datetime.utcnow)


class StepStatus(str, Enum):
    """Status of a tool step."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ToolStep(BaseModel):
    """A single step in an execution plan."""

    step_id: UUID = Field(default_factory=uuid4)
    sequence: int
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    timeout_ms: int = 60000
    status: StepStatus = StepStatus.PENDING


class PlanStatus(str, Enum):
    """Status of an execution plan."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SIMULATING = "SIMULATING"
    SIMULATION_PASSED = "SIMULATION_PASSED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Plan(BaseModel):
    """Execution plan generated from a job."""

    plan_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    version: str = "1.0.0"
    steps: list[ToolStep] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ToolResult(BaseModel):
    """Result of executing a tool step."""

    step_id: UUID
    status: StepStatus
    created_ids: list[str] = Field(default_factory=list)
    modified_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    output_data: dict[str, Any] = Field(default_factory=dict)


class Severity(str, Enum):
    """Severity level for violations and anomalies."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class Violation(BaseModel):
    """A rule violation detected during QA."""

    rule_id: str
    element_ids: list[str] = Field(default_factory=list)
    severity: Severity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class QAStatus(str, Enum):
    """Overall QA status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class QAReport(BaseModel):
    """QA/QC evaluation report."""

    report_id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    job_id: UUID
    status: QAStatus
    score: float = 100.0
    violations: list[Violation] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AnomalyType(str, Enum):
    """Types of anomalies detected in background analysis."""

    WRONG_CATEGORY = "WRONG_CATEGORY"
    WRONG_WORKSET = "WRONG_WORKSET"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    DUPLICATE_ELEMENT = "DUPLICATE_ELEMENT"
    NAMING_ISSUE = "NAMING_ISSUE"
    DESIGN_OPTION_ISSUE = "DESIGN_OPTION_ISSUE"


class Anomaly(BaseModel):
    """An anomaly detected in the model background."""

    anomaly_id: UUID = Field(default_factory=uuid4)
    anomaly_type: AnomalyType
    severity: Severity
    element_ids: list[str] = Field(default_factory=list)
    category: str
    description: str
    suggested_action: Optional[str] = None
