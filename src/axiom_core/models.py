"""SQLAlchemy ORM models for the Axiom platform.

Maps to the existing Pydantic schemas in axiom_core.schemas, storing
all data in a local SQLite database.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    """Declarative base for all Axiom ORM models."""


class JobRow(Base):
    """Raw job as submitted by a user."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    firm_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="EXCEL")
    raw_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", index=True)

    # ---- helpers to convert to/from Pydantic ----

    def set_raw_inputs(self, data: dict[str, Any]) -> None:
        self.raw_inputs_json = json.dumps(data, default=str)

    def get_raw_inputs(self) -> dict[str, Any]:
        return json.loads(self.raw_inputs_json) if self.raw_inputs_json else {}


class NormalizedJobRow(Base):
    """Validated and normalized job ready for planning."""

    __tablename__ = "normalized_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    firm_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    project_number: Mapped[str] = mapped_column(String(100), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    revit_version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_acc_project: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    template_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    arch_link_paths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scope_boxes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    views_required_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sheet_list_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    engineer_stamps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    team_assignments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bep_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phase_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    additional_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class PlanRow(Base):
    """Execution plan generated from a job."""

    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ResultsRow(Base):
    """Execution results for a plan (stored as JSON blob)."""

    __tablename__ = "results"

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class QAReportRow(Base):
    """QA/QC evaluation report."""

    __tablename__ = "qa_reports"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    violations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recommendations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ExecutionTraceRow(Base):
    """Complete trace of a job execution."""

    __tablename__ = "execution_traces"

    trace_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    qa_report_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING")


class PromptExecutionRow(Base):
    """Prompt execution record — one row per prompt run.

    Captures all fields required by the Capability Framework v1 spec:
    timestamp, original prompt, resolved capability, resolved parameters,
    assumptions, simulate vs execute, status, created count/IDs,
    errors, warnings, and duration.
    """

    __tablename__ = "prompt_executions"

    execution_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    capability: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def set_parameters(self, data: dict) -> None:
        self.parameters_json = json.dumps(data, default=str)

    def get_parameters(self) -> dict:
        return json.loads(self.parameters_json) if self.parameters_json else {}

    def set_assumptions(self, data: list) -> None:
        self.assumptions_json = json.dumps(data)

    def set_created_ids(self, data: list) -> None:
        self.created_ids_json = json.dumps(data)

    def set_errors(self, data: list) -> None:
        self.errors_json = json.dumps(data)

    def set_warnings(self, data: list) -> None:
        self.warnings_json = json.dumps(data)


class InventoryElementRow(Base):
    """One row per inventoried element."""

    __tablename__ = "inventory_elements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_model: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    element_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    unique_id: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    class_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    family_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    type_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    level_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    level_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workset_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_type: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class InventoryParameterRow(Base):
    """One row per parameter on an inventoried element."""

    __tablename__ = "inventory_parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    element_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    param_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", index=True)
    storage_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    value_string: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value_number: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_integer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    built_in_parameter_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_instance_param: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parameter_group: Mapped[str] = mapped_column(String(255), nullable=False, default="")


# ---------------------------------------------------------------------------
# Discovery Harness v1 registries (PR #20)
#
# These tables persist *interpreted* facts derived from existing InventoryModel
# exports. DiscoveryHarness never extracts/scans; it reads InventoryModel output
# and upserts the rows below using the same SQLite/SQLAlchemy patterns as PR #1.
# ---------------------------------------------------------------------------


class ProductObjectRow(Base):
    """A discovered product object category (ProductObjectRegistry)."""

    __tablename__ = "product_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(String(50), nullable=False, default="revit", index=True)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    built_in_category: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    category_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ProductPropertyRow(Base):
    """A discovered product property/parameter (ProductPropertyRegistry).

    Keyed by (adapter, category, parameter_name, instance_parameter) so that a
    parameter observed as both an instance and a type parameter is recorded as
    two correctly-labeled rows.
    """

    __tablename__ = "product_properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(String(50), nullable=False, default="revit", index=True)
    category: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    parameter_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", index=True)
    storage_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instance_parameter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    built_in_parameter_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # ---- value contract metadata (where available from InventoryModel export) ----
    spec_type_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit_type_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    display_unit: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    format_options_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    has_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sample_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_input_format: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    safely_settable_by_axiom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_run_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class CandidateCapabilityRow(Base):
    """A generated (never executed) candidate capability definition."""

    __tablename__ = "candidate_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    capability: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String(50), nullable=False, default="revit")
    category: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    parameter_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    storage_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    instance_parameter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    spec_type_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit_type_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    expected_input_format: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    safely_settable_by_axiom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="candidate")
    source_run_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ValidationProcedureRow(Base):
    """A persisted Capability Validation Registry definition (PR #23).

    Stores the governance contract for how a capability is validated: identity,
    procedure steps, input/environment requirements, evidence contract,
    pass/failure criteria, retry policy, and promotion-eligibility contract.
    This is metadata only — persisting a row never executes a validation.

    Keyed (uniquely upserted) by ``capability_name``. List/enum/nested fields
    are stored as JSON text, mirroring the existing JSON-column pattern.
    """

    __tablename__ = "validation_procedures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    capability_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String(50), nullable=False, default="revit", index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    validation_procedure_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    validation_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    validation_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    optional_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    environment_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    pass_conditions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_conditions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retry_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    promotion_eligibility_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
