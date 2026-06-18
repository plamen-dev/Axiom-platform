"""Plan-to-Validation Request Generator — transforms approved plans into work.

Current chain:
    Knowledge → Plan → Plan Review → **Validation Request**

Approved plan reviews (PR #51) become structured validation requests
describing what must be validated, what evidence is required, and what
blockers exist — without executing anything.

Governance only.  No execution, no retries, no promotion, no learning.

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
# Enums
# ---------------------------------------------------------------------------


class ValidationRequestStatus(str, Enum):
    """Lifecycle states for a validation request."""

    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BlockerType(str, Enum):
    """Classification of blockers preventing validation."""

    MISSING_CAPABILITY = "missing_capability"
    MISSING_EVIDENCE = "missing_evidence"
    UNSAFE_PROCEDURE = "unsafe_procedure"
    PREREQUISITE_FAILED = "prerequisite_failed"
    DEPENDENCY_UNMET = "dependency_unmet"
    POLICY_VIOLATION = "policy_violation"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class ValidationRequestRow(Base):
    """SQLAlchemy row for persisted validation requests."""

    __tablename__ = "validation_requests"

    request_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    plan_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    required_capabilities_json: Mapped[str] = mapped_column(Text, nullable=True)
    steps_json: Mapped[str] = mapped_column(Text, nullable=True)
    dependencies_json: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    blockers_json: Mapped[str] = mapped_column(Text, nullable=True)
    prerequisites_json: Mapped[str] = mapped_column(Text, nullable=True)
    known_risks_json: Mapped[str] = mapped_column(Text, nullable=True)
    expected_outputs_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class ValidationRequestEventRow(Base):
    """Audit log for validation request lifecycle events."""

    __tablename__ = "validation_request_events"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ValidationRequestStep:
    """A single validation step within a request."""

    def __init__(
        self,
        step_id: str = "",
        sequence: int = 0,
        title: str = "",
        description: str | None = None,
        validation_procedure: str | None = None,
        required_capabilities: list[str] | None = None,
        expected_evidence: list[str] | None = None,
        safety_level: str = "safe",
    ) -> None:
        self.step_id = step_id or str(uuid4())
        self.sequence = sequence
        self.title = title
        self.description = description
        self.validation_procedure = validation_procedure
        self.required_capabilities = required_capabilities if required_capabilities is not None else []
        self.expected_evidence = expected_evidence if expected_evidence is not None else []
        self.safety_level = safety_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence": self.sequence,
            "title": self.title,
            "description": self.description,
            "validation_procedure": self.validation_procedure,
            "required_capabilities": self.required_capabilities,
            "expected_evidence": self.expected_evidence,
            "safety_level": self.safety_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRequestStep:
        return cls(
            step_id=data.get("step_id", ""),
            sequence=data.get("sequence", 0),
            title=data.get("title", ""),
            description=data.get("description"),
            validation_procedure=data.get("validation_procedure"),
            required_capabilities=data.get("required_capabilities"),
            expected_evidence=data.get("expected_evidence"),
            safety_level=data.get("safety_level", "safe"),
        )


class ValidationRequestDependency:
    """A dependency between validation steps."""

    def __init__(
        self,
        dependency_id: str = "",
        from_step_id: str = "",
        to_step_id: str = "",
        dependency_type: str = "requires",
        description: str | None = None,
    ) -> None:
        self.dependency_id = dependency_id or str(uuid4())
        self.from_step_id = from_step_id
        self.to_step_id = to_step_id
        self.dependency_type = dependency_type
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "from_step_id": self.from_step_id,
            "to_step_id": self.to_step_id,
            "dependency_type": self.dependency_type,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRequestDependency:
        return cls(
            dependency_id=data.get("dependency_id", ""),
            from_step_id=data.get("from_step_id", ""),
            to_step_id=data.get("to_step_id", ""),
            dependency_type=data.get("dependency_type", "requires"),
            description=data.get("description"),
        )


class ValidationRequestEvidence:
    """Evidence requirement for a validation request."""

    def __init__(
        self,
        evidence_type: str = "",
        description: str | None = None,
        required: bool = True,
        source: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.description = description
        self.required = required
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "description": self.description,
            "required": self.required,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRequestEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            description=data.get("description"),
            required=data.get("required", True),
            source=data.get("source"),
        )


class ValidationRequestBlocker:
    """A blocker preventing validation from proceeding."""

    def __init__(
        self,
        blocker_id: str = "",
        blocker_type: BlockerType | str = BlockerType.DEPENDENCY_UNMET,
        description: str = "",
        resolution: str | None = None,
        blocking_step_id: str | None = None,
    ) -> None:
        self.blocker_id = blocker_id or str(uuid4())
        if isinstance(blocker_type, str):
            try:
                self.blocker_type = BlockerType(blocker_type)
            except ValueError:
                self.blocker_type = BlockerType.DEPENDENCY_UNMET
        else:
            self.blocker_type = blocker_type
        self.description = description
        self.resolution = resolution
        self.blocking_step_id = blocking_step_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "blocker_type": self.blocker_type.value,
            "description": self.description,
            "resolution": self.resolution,
            "blocking_step_id": self.blocking_step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationRequestBlocker:
        return cls(
            blocker_id=data.get("blocker_id", ""),
            blocker_type=data.get("blocker_type", "dependency_unmet"),
            description=data.get("description", ""),
            resolution=data.get("resolution"),
            blocking_step_id=data.get("blocking_step_id"),
        )


class ValidationRequest:
    """A structured validation request generated from an approved plan."""

    def __init__(
        self,
        request_id: str = "",
        plan_id: str = "",
        plan_name: str = "",
        status: ValidationRequestStatus | str = ValidationRequestStatus.PENDING,
        required_capabilities: list[str] | None = None,
        steps: list[ValidationRequestStep] | None = None,
        dependencies: list[ValidationRequestDependency] | None = None,
        evidence: list[ValidationRequestEvidence] | None = None,
        blockers: list[ValidationRequestBlocker] | None = None,
        prerequisites: list[str] | None = None,
        known_risks: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.request_id = request_id or str(uuid4())
        self.plan_id = plan_id
        self.plan_name = plan_name
        if isinstance(status, str):
            try:
                self.status = ValidationRequestStatus(status)
            except ValueError:
                self.status = ValidationRequestStatus.PENDING
        else:
            self.status = status
        self.required_capabilities = required_capabilities if required_capabilities is not None else []
        self.steps = steps if steps is not None else []
        self.dependencies = dependencies if dependencies is not None else []
        self.evidence = evidence if evidence is not None else []
        self.blockers = blockers if blockers is not None else []
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.known_risks = known_risks if known_risks is not None else []
        self.expected_outputs = expected_outputs if expected_outputs is not None else []
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "status": self.status.value,
            "required_capabilities": self.required_capabilities,
            "steps": [s.to_dict() for s in self.steps],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "evidence": [e.to_dict() for e in self.evidence],
            "blockers": [b.to_dict() for b in self.blockers],
            "prerequisites": self.prerequisites,
            "known_risks": self.known_risks,
            "expected_outputs": self.expected_outputs,
            "metadata": self.metadata,
            "step_count": len(self.steps),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ---------------------------------------------------------------------------
# ValidationRequestGenerator
# ---------------------------------------------------------------------------


class ValidationRequestGenerator:
    """Transforms approved plan reviews into structured validation requests.

    Consumes:
        - Approved Plan Reviews (PR #51)
        - Validation Registry
        - Capability State
        - Command Registry
        - Failure Classification
        - Promotion Decisions

    Governance only.  No execution, no retries, no promotion, no learning.
    """

    def __init__(self, db_path: str | None = None) -> None:
        engine = create_db_engine(db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    def _record_event(
        self, session: Any, request_id: str, event_type: str, details: dict[str, Any] | None = None
    ) -> None:
        row = ValidationRequestEventRow(
            event_id=str(uuid4()),
            request_id=request_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details_json=json.dumps(details, default=str) if details else None,
        )
        session.add(row)

    def _row_to_request(self, row: ValidationRequestRow) -> ValidationRequest:
        steps = []
        if row.steps_json:
            for s in json.loads(row.steps_json):
                steps.append(ValidationRequestStep.from_dict(s))

        dependencies = []
        if row.dependencies_json:
            for d in json.loads(row.dependencies_json):
                dependencies.append(ValidationRequestDependency.from_dict(d))

        evidence = []
        if row.evidence_json:
            for e in json.loads(row.evidence_json):
                evidence.append(ValidationRequestEvidence.from_dict(e))

        blockers = []
        if row.blockers_json:
            for b in json.loads(row.blockers_json):
                blockers.append(ValidationRequestBlocker.from_dict(b))

        return ValidationRequest(
            request_id=row.request_id,
            plan_id=row.plan_id,
            plan_name=row.plan_name,
            status=row.status,
            required_capabilities=json.loads(row.required_capabilities_json) if row.required_capabilities_json else [],
            steps=steps,
            dependencies=dependencies,
            evidence=evidence,
            blockers=blockers,
            prerequisites=json.loads(row.prerequisites_json) if row.prerequisites_json else [],
            known_risks=json.loads(row.known_risks_json) if row.known_risks_json else [],
            expected_outputs=json.loads(row.expected_outputs_json) if row.expected_outputs_json else [],
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # --- public API --------------------------------------------------------

    def create_request(self, request: ValidationRequest) -> ValidationRequest:
        """Persist a new validation request.

        Raises ValueError if plan_id or plan_name is empty.
        """
        if not request.plan_id:
            raise ValueError("plan_id must not be empty")
        if not request.plan_name:
            raise ValueError("plan_name must not be empty")

        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = ValidationRequestRow(
                request_id=request.request_id,
                plan_id=request.plan_id,
                plan_name=request.plan_name,
                status=request.status.value,
                required_capabilities_json=(
                    json.dumps(request.required_capabilities, default=str)
                    if request.required_capabilities
                    else None
                ),
                steps_json=(
                    json.dumps([s.to_dict() for s in request.steps], default=str)
                    if request.steps
                    else None
                ),
                dependencies_json=(
                    json.dumps([d.to_dict() for d in request.dependencies], default=str)
                    if request.dependencies
                    else None
                ),
                evidence_json=(
                    json.dumps([e.to_dict() for e in request.evidence], default=str)
                    if request.evidence
                    else None
                ),
                blockers_json=(
                    json.dumps([b.to_dict() for b in request.blockers], default=str)
                    if request.blockers
                    else None
                ),
                prerequisites_json=(
                    json.dumps(request.prerequisites, default=str)
                    if request.prerequisites
                    else None
                ),
                known_risks_json=(
                    json.dumps(request.known_risks, default=str)
                    if request.known_risks
                    else None
                ),
                expected_outputs_json=(
                    json.dumps(request.expected_outputs, default=str)
                    if request.expected_outputs
                    else None
                ),
                metadata_json=(
                    json.dumps(request.metadata, default=str)
                    if request.metadata
                    else None
                ),
                step_count=len(request.steps),
                created_at=request.created_at,
                updated_at=now,
            )
            session.add(row)
            self._record_event(session, request.request_id, "created")
            return self._row_to_request(row)

    def get_request(self, request_id: str) -> ValidationRequest | None:
        """Retrieve a single validation request by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(ValidationRequestRow, request_id)
            if row is None:
                return None
            return self._row_to_request(row)

    def get_requests_for_plan(self, plan_id: str) -> list[ValidationRequest]:
        """Retrieve all validation requests for a given plan ID."""
        with get_session(self._session_factory) as session:
            rows = (
                session.query(ValidationRequestRow)
                .filter(ValidationRequestRow.plan_id == plan_id)
                .order_by(ValidationRequestRow.created_at.desc())
                .all()
            )
            return [self._row_to_request(r) for r in rows]

    def list_requests(
        self,
        status_filter: ValidationRequestStatus | None = None,
        plan_id_filter: str | None = None,
    ) -> list[ValidationRequest]:
        """List validation requests with optional filters.

        Ordered by status priority then created_at desc.
        """
        with get_session(self._session_factory) as session:
            q = session.query(ValidationRequestRow)
            if status_filter is not None:
                q = q.filter(ValidationRequestRow.status == status_filter.value)
            if plan_id_filter is not None:
                q = q.filter(ValidationRequestRow.plan_id == plan_id_filter)
            q = q.order_by(
                ValidationRequestRow.status,
                ValidationRequestRow.created_at.desc(),
            )
            return [self._row_to_request(r) for r in q.all()]

    def update_status(self, request_id: str, new_status: ValidationRequestStatus) -> bool:
        """Update the status of a validation request. Returns True on success."""
        with get_session(self._session_factory) as session:
            row = session.get(ValidationRequestRow, request_id)
            if row is None:
                return False
            row.status = new_status.value
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(session, request_id, "status_changed", {"new_status": new_status.value})
            return True

    def request_count(self) -> int:
        """Total number of validation requests."""
        with get_session(self._session_factory) as session:
            return session.query(ValidationRequestRow).count()

    def generate_from_plan(
        self,
        plan_id: str,
        plan_name: str,
        steps: list[ValidationRequestStep] | None = None,
        dependencies: list[ValidationRequestDependency] | None = None,
        evidence: list[ValidationRequestEvidence] | None = None,
        blockers: list[ValidationRequestBlocker] | None = None,
        prerequisites: list[str] | None = None,
        known_risks: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationRequest:
        """Generate and persist a validation request from plan data.

        This is the main entry point for the generator.
        It determines status based on blockers presence.
        """
        effective_steps = steps if steps is not None else []
        effective_blockers = blockers if blockers is not None else []

        status = ValidationRequestStatus.BLOCKED if effective_blockers else ValidationRequestStatus.READY

        # Collect required capabilities from steps if not explicit
        effective_capabilities = list(required_capabilities) if required_capabilities is not None else []
        if not effective_capabilities:
            seen: set[str] = set()
            for step in effective_steps:
                for cap in step.required_capabilities:
                    if cap not in seen:
                        seen.add(cap)
                        effective_capabilities.append(cap)

        request = ValidationRequest(
            plan_id=plan_id,
            plan_name=plan_name,
            status=status,
            required_capabilities=effective_capabilities,
            steps=effective_steps,
            dependencies=dependencies,
            evidence=evidence,
            blockers=effective_blockers,
            prerequisites=prerequisites,
            known_risks=known_risks,
            expected_outputs=expected_outputs,
            metadata=metadata,
        )
        return self.create_request(request)
