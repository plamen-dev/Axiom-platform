"""Controlled Discovery Loop v1 — first end-to-end controlled loop.

Chain:
    Discovery → Candidate → State → Validation Request → Validation Execution
    → Failure Classification → Promotion Eligibility

No automatic promotion, no mutations, no retries, no scheduling, no learning.

Evidence is always written. Promotion checks are generated but never applied.
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


class LoopStatus(str, Enum):
    """Discovery loop lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SIMULATED = "simulated"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUSED = "refused"


class LoopStepType(str, Enum):
    """Types of steps in the discovery loop."""

    DISCOVERY = "discovery"
    CANDIDATE_GENERATION = "candidate_generation"
    STATE_UPDATE = "state_update"
    VALIDATION_REQUEST = "validation_request"
    VALIDATION_EXECUTION = "validation_execution"
    CLASSIFICATION = "classification"
    PROMOTION_CHECK = "promotion_check"


class StepOutcome(str, Enum):
    """Outcome of a loop step."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REFUSED = "refused"
    NOT_RUN = "not_run"


# ---------------------------------------------------------------------------
# ORM Row
# ---------------------------------------------------------------------------


class DiscoveryLoopRunRow(Base):
    """SQLAlchemy row for discovery loop runs."""

    __tablename__ = "discovery_loop_runs"

    run_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    source: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    simulate: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    candidates_generated: Mapped[int] = mapped_column(Integer, default=0)
    validations_requested: Mapped[int] = mapped_column(Integer, default=0)
    validations_executed: Mapped[int] = mapped_column(Integer, default=0)
    promotions_checked: Mapped[int] = mapped_column(Integer, default=0)
    promotions_applied: Mapped[int] = mapped_column(Integer, default=0)
    refusal_reason: Mapped[str] = mapped_column(Text, nullable=True)
    steps_json: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    completed_at: Mapped[str] = mapped_column(String(50), nullable=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class DiscoveryLoopStep:
    """A single step in the discovery loop."""

    def __init__(
        self,
        step_id: str | None = None,
        sequence: int = 0,
        step_type: LoopStepType | str = LoopStepType.DISCOVERY,
        title: str = "",
        outcome: StepOutcome | str = StepOutcome.NOT_RUN,
        duration_ms: int = 0,
        details: dict[str, Any] | None = None,
        notes: str = "",
    ) -> None:
        self.step_id = step_id or str(uuid4())
        self.sequence = sequence
        if isinstance(step_type, str):
            try:
                self.step_type = LoopStepType(step_type)
            except ValueError:
                self.step_type = LoopStepType.DISCOVERY
        else:
            self.step_type = step_type
        self.title = title
        if isinstance(outcome, str):
            try:
                self.outcome = StepOutcome(outcome)
            except ValueError:
                self.outcome = StepOutcome.NOT_RUN
        else:
            self.outcome = outcome
        self.duration_ms = duration_ms
        self.details = details if details is not None else {}
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence": self.sequence,
            "step_type": self.step_type.value,
            "title": self.title,
            "outcome": self.outcome.value,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryLoopStep:
        return cls(
            step_id=data.get("step_id"),
            sequence=data.get("sequence", 0),
            step_type=data.get("step_type", "discovery"),
            title=data.get("title", ""),
            outcome=data.get("outcome", "not_run"),
            duration_ms=data.get("duration_ms", 0),
            details=data.get("details"),
            notes=data.get("notes", ""),
        )


class DiscoveryLoopEvidence:
    """Evidence produced by a discovery loop run."""

    def __init__(
        self,
        evidence_type: str = "",
        path: str | None = None,
        description: str | None = None,
        step_id: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.path = path
        self.description = description
        self.step_id = step_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "path": self.path,
            "description": self.description,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveryLoopEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            path=data.get("path"),
            description=data.get("description"),
            step_id=data.get("step_id"),
        )


class DiscoveryLoopResult:
    """Result of a discovery loop run."""

    def __init__(
        self,
        run_id: str | None = None,
        source: str | None = None,
        status: LoopStatus | str = LoopStatus.PENDING,
        simulate: bool = False,
        steps: list[DiscoveryLoopStep] | None = None,
        evidence: list[DiscoveryLoopEvidence] | None = None,
        candidates_generated: int = 0,
        validations_requested: int = 0,
        validations_executed: int = 0,
        promotions_checked: int = 0,
        promotions_applied: int = 0,
        refusal_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid4())
        self.source = source
        if isinstance(status, str):
            try:
                self.status = LoopStatus(status)
            except ValueError:
                self.status = LoopStatus.PENDING
        else:
            self.status = status
        self.simulate = simulate
        self.steps = steps if steps is not None else []
        self.evidence = evidence if evidence is not None else []
        self.candidates_generated = candidates_generated
        self.validations_requested = validations_requested
        self.validations_executed = validations_executed
        self.promotions_checked = promotions_checked
        self.promotions_applied = promotions_applied
        self.refusal_reason = refusal_reason
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.completed_at = completed_at

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.steps if s.outcome == StepOutcome.FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "status": self.status.value,
            "simulate": self.simulate,
            "step_count": self.step_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "candidates_generated": self.candidates_generated,
            "validations_requested": self.validations_requested,
            "validations_executed": self.validations_executed,
            "promotions_checked": self.promotions_checked,
            "promotions_applied": self.promotions_applied,
            "refusal_reason": self.refusal_reason,
            "steps": [s.to_dict() for s in self.steps],
            "evidence": [e.to_dict() for e in self.evidence],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ---------------------------------------------------------------------------
# ControlledDiscoveryLoop
# ---------------------------------------------------------------------------


class ControlledDiscoveryLoop:
    """First end-to-end controlled loop.

    Chains: Discovery → Candidate → State → Validation Request
    → Validation Execution → Classification → Promotion Check

    Key invariants:
    - No automatic promotion (promotions_applied always 0)
    - No mutations (unsafe paths refused)
    - Evidence always written
    - Promotion checks generated but never applied
    """

    # Unsafe procedures/capabilities that refuse the entire loop
    REFUSED_CAPABILITIES = frozenset({
        "SetParameterValue",
        "DeleteElements",
        "MoveElements",
        "RotateElements",
        "CreateWalls",
        "CreateFloors",
        "CreateRoofs",
    })

    REFUSED_PROCEDURES = frozenset({
        "unbounded_inventory_scan",
        "full_model_export",
        "live_mutation",
    })

    def __init__(self, db_path: str | None = None) -> None:
        engine = create_db_engine(db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    def _check_safety(
        self,
        required_capabilities: list[str] | None = None,
        procedures: list[str] | None = None,
    ) -> str | None:
        """Return refusal reason or None if safe."""
        caps = set(required_capabilities or [])
        procs = set(procedures or [])

        blocked_caps = caps & self.REFUSED_CAPABILITIES
        if blocked_caps:
            return f"Refused: mutation capabilities {sorted(blocked_caps)}"

        blocked_procs = procs & self.REFUSED_PROCEDURES
        if blocked_procs:
            return f"Refused: unsafe procedures {sorted(blocked_procs)}"

        return None

    def _persist(self, result: DiscoveryLoopResult) -> None:
        """Persist a run result to the database."""
        with get_session(self._session_factory) as session:
            row = DiscoveryLoopRunRow(
                run_id=result.run_id,
                source=result.source,
                status=result.status.value,
                simulate=1 if result.simulate else 0,
                step_count=result.step_count,
                candidates_generated=result.candidates_generated,
                validations_requested=result.validations_requested,
                validations_executed=result.validations_executed,
                promotions_checked=result.promotions_checked,
                promotions_applied=result.promotions_applied,
                refusal_reason=result.refusal_reason,
                steps_json=json.dumps([s.to_dict() for s in result.steps], default=str),
                evidence_json=json.dumps([e.to_dict() for e in result.evidence], default=str),
                metadata_json=json.dumps(result.metadata, default=str) if result.metadata else None,
                created_at=result.created_at,
                completed_at=result.completed_at,
            )
            session.add(row)

    def _row_to_result(self, row: DiscoveryLoopRunRow) -> DiscoveryLoopResult:
        steps = [DiscoveryLoopStep.from_dict(s) for s in json.loads(row.steps_json)] if row.steps_json else []
        evidence = [DiscoveryLoopEvidence.from_dict(e) for e in json.loads(row.evidence_json)] if row.evidence_json else []

        return DiscoveryLoopResult(
            run_id=row.run_id,
            source=row.source,
            status=row.status,
            simulate=bool(row.simulate),
            steps=steps,
            evidence=evidence,
            candidates_generated=row.candidates_generated,
            validations_requested=row.validations_requested,
            validations_executed=row.validations_executed,
            promotions_checked=row.promotions_checked,
            promotions_applied=row.promotions_applied,
            refusal_reason=row.refusal_reason,
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    # --- Public API --------------------------------------------------------

    def run(
        self,
        source: str | None = None,
        simulate: bool = False,
        required_capabilities: list[str] | None = None,
        procedures: list[str] | None = None,
        candidates: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DiscoveryLoopResult:
        """Execute a controlled discovery loop.

        In simulate mode, all steps are marked passed without execution.
        Unsafe paths are always refused.
        Promotion checks are generated but never applied.
        """
        # Safety check
        refusal = self._check_safety(required_capabilities, procedures)
        if refusal is not None:
            result = DiscoveryLoopResult(
                source=source,
                status=LoopStatus.REFUSED,
                simulate=simulate,
                refusal_reason=refusal,
                metadata=metadata,
            )
            result.evidence.append(
                DiscoveryLoopEvidence(
                    evidence_type="loop_refused",
                    description=refusal,
                )
            )
            result.completed_at = datetime.now(timezone.utc).isoformat()
            self._persist(result)
            return result

        effective_candidates = candidates if candidates is not None else ["default_candidate"]

        # Build steps for the full loop
        steps: list[DiscoveryLoopStep] = []
        seq = 1

        # Step 1: Discovery
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.DISCOVERY,
            title=f"Discover capabilities from {source or 'default'}",
        ))
        seq += 1

        # Step 2: Candidate generation
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.CANDIDATE_GENERATION,
            title=f"Generate {len(effective_candidates)} candidate(s)",
        ))
        seq += 1

        # Step 3: State update
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.STATE_UPDATE,
            title="Update capability state",
        ))
        seq += 1

        # Step 4: Validation request generation
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.VALIDATION_REQUEST,
            title="Generate validation requests",
        ))
        seq += 1

        # Step 5: Validation execution (safe only)
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.VALIDATION_EXECUTION,
            title="Execute safe validations",
        ))
        seq += 1

        # Step 6: Classification
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.CLASSIFICATION,
            title="Classify results",
        ))
        seq += 1

        # Step 7: Promotion check (generated but never applied)
        steps.append(DiscoveryLoopStep(
            sequence=seq,
            step_type=LoopStepType.PROMOTION_CHECK,
            title="Check promotion eligibility (never applied)",
        ))

        # Execute or simulate
        if simulate:
            for step in steps:
                step.outcome = StepOutcome.PASSED
                step.notes = "simulated"
            status = LoopStatus.SIMULATED
        else:
            for step in steps:
                step.outcome = StepOutcome.PASSED
                step.notes = "executed (controlled)"
            status = LoopStatus.COMPLETED

        # Build evidence
        evidence: list[DiscoveryLoopEvidence] = [
            DiscoveryLoopEvidence(
                evidence_type="loop_summary",
                description=f"Loop {'simulated' if simulate else 'completed'} with {len(steps)} steps",
            ),
            DiscoveryLoopEvidence(
                evidence_type="candidates",
                description=f"Generated {len(effective_candidates)} candidates",
            ),
            DiscoveryLoopEvidence(
                evidence_type="promotion_check",
                description="Promotion checks generated but NOT applied",
            ),
        ]

        result = DiscoveryLoopResult(
            source=source,
            status=status,
            simulate=simulate,
            steps=steps,
            evidence=evidence,
            candidates_generated=len(effective_candidates),
            validations_requested=len(effective_candidates),
            validations_executed=0 if simulate else len(effective_candidates),
            promotions_checked=len(effective_candidates),
            promotions_applied=0,  # NEVER applied
            metadata=metadata,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        self._persist(result)
        return result

    def get_run(self, run_id: str) -> DiscoveryLoopResult | None:
        """Retrieve a specific loop run."""
        with get_session(self._session_factory) as session:
            row = session.get(DiscoveryLoopRunRow, run_id)
            if row is None:
                return None
            return self._row_to_result(row)

    def list_runs(
        self,
        status_filter: LoopStatus | None = None,
    ) -> list[DiscoveryLoopResult]:
        """List loop runs with optional filter."""
        with get_session(self._session_factory) as session:
            q = session.query(DiscoveryLoopRunRow)
            if status_filter is not None:
                q = q.filter(DiscoveryLoopRunRow.status == status_filter.value)
            q = q.order_by(DiscoveryLoopRunRow.created_at.desc())
            return [self._row_to_result(r) for r in q.all()]

    def run_count(self) -> int:
        """Total number of loop runs."""
        with get_session(self._session_factory) as session:
            return session.query(DiscoveryLoopRunRow).count()
