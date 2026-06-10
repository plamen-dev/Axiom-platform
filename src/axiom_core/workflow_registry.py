"""Workflow Knowledge Registry — captures engineering workflows as knowledge.

Transforms founder expertise into structured knowledge.  Workflows are
sequences of steps with inputs, outputs, and rules that encode
engineering decision processes.

Metadata and governance only.  No execution, no planners, no automation,
no learning.

Persistence via SQLAlchemy/SQLite (reuses the Axiom database layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

# ---------------------------------------------------------------------------
# Workflow status
# ---------------------------------------------------------------------------


class WorkflowStatus(str, Enum):
    """Lifecycle status of a workflow definition."""

    ACTIVE = "active"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class WorkflowDefinitionRow(Base):
    """Persisted workflow definition."""

    __tablename__ = "workflow_definitions"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class WorkflowStepRow(Base):
    """Persisted workflow step."""

    __tablename__ = "workflow_steps"

    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_name: Mapped[str] = mapped_column(String(200), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=True)
    outputs_json: Mapped[str] = mapped_column(Text, nullable=True)
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=True)


class WorkflowRuleRow(Base):
    """Persisted workflow rule."""

    __tablename__ = "workflow_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class WorkflowInput:
    """Input specification for a workflow step."""

    def __init__(self, name: str, description: str = "", required: bool = True) -> None:
        self.name = name
        self.description = description
        self.required = required

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "required": self.required}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowInput:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            required=data.get("required", True),
        )


class WorkflowOutput:
    """Output specification for a workflow step."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowOutput:
        return cls(name=data.get("name", ""), description=data.get("description", ""))


class WorkflowStep:
    """A single step in a workflow."""

    def __init__(
        self,
        step_id: str = "",
        workflow_id: str = "",
        step_name: str = "",
        step_order: int = 0,
        description: str | None = None,
        inputs: list[WorkflowInput] | None = None,
        outputs: list[WorkflowOutput] | None = None,
        depends_on: list[str] | None = None,
    ) -> None:
        self.step_id = step_id or str(uuid4())
        self.workflow_id = workflow_id
        self.step_name = step_name
        self.step_order = step_order
        self.description = description
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.depends_on = depends_on or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "workflow_id": self.workflow_id,
            "step_name": self.step_name,
            "step_order": self.step_order,
            "description": self.description,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "depends_on": self.depends_on,
        }


class WorkflowRule:
    """A rule governing workflow behavior."""

    def __init__(
        self,
        rule_id: str = "",
        workflow_id: str = "",
        rule_name: str = "",
        condition: str = "",
        action: str = "",
        priority: int = 0,
        notes: str | None = None,
    ) -> None:
        self.rule_id = rule_id or str(uuid4())
        self.workflow_id = workflow_id
        self.rule_name = rule_name
        self.condition = condition
        self.action = action
        self.priority = priority
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "workflow_id": self.workflow_id,
            "rule_name": self.rule_name,
            "condition": self.condition,
            "action": self.action,
            "priority": self.priority,
            "notes": self.notes,
        }


class WorkflowDefinition:
    """A workflow definition capturing engineering expertise."""

    def __init__(
        self,
        workflow_id: str = "",
        workflow_name: str = "",
        description: str | None = None,
        status: WorkflowStatus | str = WorkflowStatus.ACTIVE,
        version: str = "1.0",
        created_at: str | None = None,
        updated_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        steps: list[WorkflowStep] | None = None,
        rules: list[WorkflowRule] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.workflow_id = workflow_id or str(uuid4())
        self.workflow_name = workflow_name
        self.description = description
        self.status = status if isinstance(status, WorkflowStatus) else WorkflowStatus(status)
        self.version = version
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.metadata = metadata if metadata is not None else {}
        self.steps = steps or []
        self.rules = rules or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "description": self.description,
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "steps": [s.to_dict() for s in self.steps],
            "rules": [r.to_dict() for r in self.rules],
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards (% and _) and the escape char (\\) in user-supplied filter strings."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class WorkflowKnowledgeRegistry:
    """Governed registry of workflow knowledge.

    Backed by SQLite via SQLAlchemy.  Supports register, list, get
    (with steps/rules), and deprecation.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    def register_workflow(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """Register or update a workflow definition with its steps and rules."""
        if not workflow.workflow_name:
            raise ValueError("workflow_name must not be empty")

        with get_session(self._session_factory) as session:
            now = datetime.now(timezone.utc).isoformat()
            existing = session.get(WorkflowDefinitionRow, workflow.workflow_id)

            if existing:
                existing.workflow_name = workflow.workflow_name
                existing.description = workflow.description
                existing.status = workflow.status.value
                existing.version = workflow.version
                existing.updated_at = now
                existing.metadata_json = (
                    json.dumps(workflow.metadata, default=str)
                    if workflow.metadata is not None
                    else None
                )
                workflow.updated_at = now
            else:
                row = WorkflowDefinitionRow(
                    workflow_id=workflow.workflow_id,
                    workflow_name=workflow.workflow_name,
                    description=workflow.description,
                    status=workflow.status.value,
                    version=workflow.version,
                    created_at=workflow.created_at,
                    updated_at=workflow.updated_at,
                    metadata_json=(
                        json.dumps(workflow.metadata, default=str)
                        if workflow.metadata is not None
                        else None
                    ),
                )
                session.add(row)

            # Replace steps: delete removed, upsert current
            current_step_ids = {s.step_id for s in workflow.steps}
            if current_step_ids:
                session.query(WorkflowStepRow).filter(
                    WorkflowStepRow.workflow_id == workflow.workflow_id,
                    ~WorkflowStepRow.step_id.in_(current_step_ids),
                ).delete(synchronize_session="fetch")
            else:
                session.query(WorkflowStepRow).filter(
                    WorkflowStepRow.workflow_id == workflow.workflow_id,
                ).delete(synchronize_session="fetch")

            for step in workflow.steps:
                step.workflow_id = workflow.workflow_id
                existing_step = session.get(WorkflowStepRow, step.step_id)
                if existing_step:
                    existing_step.step_name = step.step_name
                    existing_step.step_order = step.step_order
                    existing_step.description = step.description
                    existing_step.inputs_json = json.dumps([i.to_dict() for i in step.inputs]) if step.inputs else None
                    existing_step.outputs_json = json.dumps([o.to_dict() for o in step.outputs]) if step.outputs else None
                    existing_step.depends_on_json = json.dumps(step.depends_on) if step.depends_on else None
                else:
                    step_row = WorkflowStepRow(
                        step_id=step.step_id,
                        workflow_id=workflow.workflow_id,
                        step_name=step.step_name,
                        step_order=step.step_order,
                        description=step.description,
                        inputs_json=json.dumps([i.to_dict() for i in step.inputs]) if step.inputs else None,
                        outputs_json=json.dumps([o.to_dict() for o in step.outputs]) if step.outputs else None,
                        depends_on_json=json.dumps(step.depends_on) if step.depends_on else None,
                    )
                    session.add(step_row)

            # Replace rules: delete removed, upsert current
            current_rule_ids = {r.rule_id for r in workflow.rules}
            if current_rule_ids:
                session.query(WorkflowRuleRow).filter(
                    WorkflowRuleRow.workflow_id == workflow.workflow_id,
                    ~WorkflowRuleRow.rule_id.in_(current_rule_ids),
                ).delete(synchronize_session="fetch")
            else:
                session.query(WorkflowRuleRow).filter(
                    WorkflowRuleRow.workflow_id == workflow.workflow_id,
                ).delete(synchronize_session="fetch")

            for rule in workflow.rules:
                rule.workflow_id = workflow.workflow_id
                existing_rule = session.get(WorkflowRuleRow, rule.rule_id)
                if existing_rule:
                    existing_rule.rule_name = rule.rule_name
                    existing_rule.condition = rule.condition
                    existing_rule.action = rule.action
                    existing_rule.priority = rule.priority
                    existing_rule.notes = rule.notes
                else:
                    rule_row = WorkflowRuleRow(
                        rule_id=rule.rule_id,
                        workflow_id=workflow.workflow_id,
                        rule_name=rule.rule_name,
                        condition=rule.condition,
                        action=rule.action,
                        priority=rule.priority,
                        notes=rule.notes,
                    )
                    session.add(rule_row)

        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        """Get a workflow with its steps and rules."""
        with get_session(self._session_factory) as session:
            row = session.get(WorkflowDefinitionRow, workflow_id)
            if row is None:
                return None

            step_rows = (
                session.query(WorkflowStepRow)
                .filter(WorkflowStepRow.workflow_id == workflow_id)
                .order_by(WorkflowStepRow.step_order)
                .all()
            )
            rule_rows = (
                session.query(WorkflowRuleRow)
                .filter(WorkflowRuleRow.workflow_id == workflow_id)
                .order_by(WorkflowRuleRow.priority)
                .all()
            )

            return self._assemble_workflow(row, step_rows, rule_rows)

    def list_workflows(
        self,
        name_filter: str | None = None,
        include_deprecated: bool = False,
    ) -> list[WorkflowDefinition]:
        """List workflow definitions, ordered by name."""
        with get_session(self._session_factory) as session:
            query = session.query(WorkflowDefinitionRow)
            if not include_deprecated:
                query = query.filter(WorkflowDefinitionRow.status != WorkflowStatus.DEPRECATED.value)
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    WorkflowDefinitionRow.workflow_name.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(WorkflowDefinitionRow.workflow_name).all()

            results = []
            for row in rows:
                step_rows = (
                    session.query(WorkflowStepRow)
                    .filter(WorkflowStepRow.workflow_id == row.workflow_id)
                    .order_by(WorkflowStepRow.step_order)
                    .all()
                )
                rule_rows = (
                    session.query(WorkflowRuleRow)
                    .filter(WorkflowRuleRow.workflow_id == row.workflow_id)
                    .order_by(WorkflowRuleRow.priority)
                    .all()
                )
                results.append(self._assemble_workflow(row, step_rows, rule_rows))
            return results

    def deprecate(self, workflow_id: str) -> bool:
        """Mark a workflow as deprecated."""
        with get_session(self._session_factory) as session:
            row = session.get(WorkflowDefinitionRow, workflow_id)
            if row is None:
                return False
            row.status = WorkflowStatus.DEPRECATED.value
            row.updated_at = datetime.now(timezone.utc).isoformat()
            return True

    def workflow_count(self) -> int:
        """Return total number of workflows (including deprecated)."""
        with get_session(self._session_factory) as session:
            return session.query(WorkflowDefinitionRow).count()

    def to_json(
        self,
        name_filter: str | None = None,
        include_deprecated: bool = False,
    ) -> str:
        """Return workflows as JSON string."""
        workflows = self.list_workflows(
            name_filter=name_filter, include_deprecated=include_deprecated
        )
        return json.dumps([w.to_dict() for w in workflows], indent=2, default=str)

    # --- Internal ---

    @staticmethod
    def _assemble_workflow(
        row: WorkflowDefinitionRow,
        step_rows: list[WorkflowStepRow],
        rule_rows: list[WorkflowRuleRow],
    ) -> WorkflowDefinition:
        try:
            status = WorkflowStatus(row.status)
        except ValueError:
            status = row.status  # type: ignore[assignment]

        metadata: dict[str, Any] = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        steps = []
        for sr in step_rows:
            inputs = []
            if sr.inputs_json:
                try:
                    inputs = [WorkflowInput.from_dict(d) for d in json.loads(sr.inputs_json)]
                except (json.JSONDecodeError, TypeError):
                    inputs = []
            outputs = []
            if sr.outputs_json:
                try:
                    outputs = [WorkflowOutput.from_dict(d) for d in json.loads(sr.outputs_json)]
                except (json.JSONDecodeError, TypeError):
                    outputs = []
            depends_on = []
            if sr.depends_on_json:
                try:
                    depends_on = json.loads(sr.depends_on_json)
                except (json.JSONDecodeError, TypeError):
                    depends_on = []

            steps.append(WorkflowStep(
                step_id=sr.step_id,
                workflow_id=sr.workflow_id,
                step_name=sr.step_name,
                step_order=sr.step_order,
                description=sr.description,
                inputs=inputs,
                outputs=outputs,
                depends_on=depends_on,
            ))

        rules = []
        for rr in rule_rows:
            rules.append(WorkflowRule(
                rule_id=rr.rule_id,
                workflow_id=rr.workflow_id,
                rule_name=rr.rule_name,
                condition=rr.condition,
                action=rr.action,
                priority=rr.priority,
                notes=rr.notes,
            ))

        return WorkflowDefinition(
            workflow_id=row.workflow_id,
            workflow_name=row.workflow_name,
            description=row.description,
            status=status,
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            metadata=metadata,
            steps=steps,
            rules=rules,
        )
