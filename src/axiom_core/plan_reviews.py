"""Plan Review Queue — governed human-review layer for capability plans.

Axiom can generate structured plans (PR #45), but there is no durable
mechanism to decide whether a plan is approved, rejected, deferred,
needs more evidence, or superseded.

This module creates the human-review layer for plans.

Governance only.  No execution, no automatic approval, no promotion,
no learning, no workflow mutation.

Persistence via SQLAlchemy/SQLite (reuses the Axiom database layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Text
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


class PlanReviewDecision(str, Enum):
    """Deterministic outcome of a plan review."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    SUPERSEDED = "superseded"


class PlanReviewStatus(str, Enum):
    """Lifecycle status of a plan review record."""

    OPEN = "open"
    CLOSED = "closed"


class PlanReviewReason(str, Enum):
    """Categorised reason for a plan review decision."""

    HUMAN_VALIDATION = "human_validation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSAFE = "unsafe"
    CONFLICTING_PLAN = "conflicting_plan"
    DUPLICATE = "duplicate"
    OBSOLETE = "obsolete"
    LOW_CONFIDENCE = "low_confidence"
    FOUNDER_OVERRIDE = "founder_override"
    POLICY_VIOLATION = "policy_violation"
    DEFERRED_PENDING = "deferred_pending"


# Valid enum values as frozensets for documentation/validation
VALID_DECISIONS: frozenset[str] = frozenset(d.value for d in PlanReviewDecision)
VALID_STATUSES: frozenset[str] = frozenset(s.value for s in PlanReviewStatus)
VALID_REASONS: frozenset[str] = frozenset(r.value for r in PlanReviewReason)

# Decision ordering (index 0 = highest priority in deterministic listing)
DECISION_ORDER: list[PlanReviewDecision] = [
    PlanReviewDecision.APPROVED,
    PlanReviewDecision.PROPOSED,
    PlanReviewDecision.DEFERRED,
    PlanReviewDecision.NEEDS_MORE_EVIDENCE,
    PlanReviewDecision.REJECTED,
    PlanReviewDecision.SUPERSEDED,
]


def decision_rank(decision: PlanReviewDecision | str) -> int:
    """Return numeric rank for a decision (lower = higher priority).

    Unknown decisions receive the lowest rank (len(DECISION_ORDER)).
    """
    if isinstance(decision, str):
        try:
            decision = PlanReviewDecision(decision)
        except ValueError:
            return len(DECISION_ORDER)
    try:
        return DECISION_ORDER.index(decision)
    except ValueError:
        return len(DECISION_ORDER)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class PlanReviewRow(Base):
    """Persisted plan review record."""

    __tablename__ = "plan_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_name: Mapped[str] = mapped_column(String(300), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    superseded_by: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class PlanReviewEventRow(Base):
    """Event log for plan review lifecycle changes (history)."""

    __tablename__ = "plan_review_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PlanReviewEvidence:
    """Evidence supporting a plan review decision."""

    def __init__(
        self,
        evidence_type: str = "",
        evidence_path: str = "",
        description: str = "",
        timestamp: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.evidence_path = evidence_path
        self.description = description
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "evidence_path": self.evidence_path,
            "description": self.description,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanReviewEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            evidence_path=data.get("evidence_path", ""),
            description=data.get("description", ""),
            timestamp=data.get("timestamp"),
        )


class PlanReview:
    """A governed review decision for a capability plan."""

    def __init__(
        self,
        review_id: str = "",
        plan_id: str = "",
        plan_name: str = "",
        decision: PlanReviewDecision | str = PlanReviewDecision.PROPOSED,
        reason: PlanReviewReason | str = PlanReviewReason.HUMAN_VALIDATION,
        status: PlanReviewStatus | str = PlanReviewStatus.OPEN,
        reviewer: str | None = None,
        notes: str | None = None,
        evidence: list[PlanReviewEvidence] | None = None,
        metadata: dict[str, Any] | None = None,
        superseded_by: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.review_id = review_id or str(uuid4())
        self.plan_id = plan_id
        self.plan_name = plan_name
        self.decision = (
            decision if isinstance(decision, PlanReviewDecision) else PlanReviewDecision(decision)
        )
        self.reason = reason if isinstance(reason, PlanReviewReason) else PlanReviewReason(reason)
        self.status = status if isinstance(status, PlanReviewStatus) else PlanReviewStatus(status)
        self.reviewer = reviewer
        self.notes = notes
        self.evidence = evidence if evidence is not None else []
        self.metadata = metadata if metadata is not None else {}
        self.superseded_by = superseded_by
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "decision": self.decision.value,
            "reason": self.reason.value,
            "status": self.status.value,
            "reviewer": self.reviewer,
            "notes": self.notes,
            "evidence": [e.to_dict() for e in self.evidence],
            "metadata": self.metadata,
            "superseded_by": self.superseded_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PlanReviewHistory:
    """Complete review history for a single plan."""

    def __init__(self, plan_id: str, reviews: list[PlanReview]) -> None:
        self.plan_id = plan_id
        self.reviews = reviews

    @property
    def latest_decision(self) -> PlanReviewDecision | None:
        """Most recent decision for this plan."""
        if not self.reviews:
            return None
        return self.reviews[-1].decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "review_count": len(self.reviews),
            "latest_decision": self.latest_decision.value if self.latest_decision else None,
            "reviews": [r.to_dict() for r in self.reviews],
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards and the escape char in user-supplied filter strings."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _coerce_enum(value: str, enum_cls: type[Enum]) -> Enum | str:
    """Coerce a string to an enum member, returning the raw string on failure."""
    try:
        return enum_cls(value)
    except ValueError:
        return value


class PlanReviewRegistry:
    """Governed registry of plan review and approval decisions.

    Backed by SQLite via SQLAlchemy.  Supports create, get, list, close,
    supersede, history retrieval, and deterministic ordering.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    def create_review(self, review: PlanReview) -> PlanReview:
        """Create a new plan review record.

        Returns a new PlanReview reflecting the persisted state.
        Raises ValueError if plan_id is empty.
        """
        if not review.plan_id:
            raise ValueError("plan_id must not be empty")
        if not review.plan_name:
            raise ValueError("plan_name must not be empty")

        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = PlanReviewRow(
                review_id=review.review_id,
                plan_id=review.plan_id,
                plan_name=review.plan_name,
                decision=review.decision.value,
                reason=review.reason.value,
                status=review.status.value,
                reviewer=review.reviewer,
                notes=review.notes,
                evidence_json=(
                    json.dumps([e.to_dict() for e in review.evidence], default=str)
                    if review.evidence
                    else None
                ),
                metadata_json=(
                    json.dumps(review.metadata, default=str)
                    if review.metadata
                    else None
                ),
                superseded_by=review.superseded_by,
                created_at=review.created_at,
                updated_at=now,
            )
            session.add(row)
            self._record_event(session, review.review_id, "created")
            return self._row_to_review(row)

    def get_review(self, review_id: str) -> PlanReview | None:
        """Get a single review by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(PlanReviewRow, review_id)
            if row is None:
                return None
            return self._row_to_review(row)

    def get_reviews_for_plan(self, plan_id: str) -> list[PlanReview]:
        """Get all reviews for a specific plan (history), oldest first."""
        with get_session(self._session_factory) as session:
            rows = (
                session.query(PlanReviewRow)
                .filter(PlanReviewRow.plan_id == plan_id)
                .order_by(PlanReviewRow.created_at)
                .all()
            )
            return [self._row_to_review(r) for r in rows]

    def get_history(self, plan_id: str) -> PlanReviewHistory:
        """Get the full review history for a plan."""
        reviews = self.get_reviews_for_plan(plan_id)
        return PlanReviewHistory(plan_id=plan_id, reviews=reviews)

    def list_reviews(
        self,
        name_filter: str | None = None,
        decision_filter: PlanReviewDecision | None = None,
        status_filter: PlanReviewStatus | None = None,
    ) -> list[PlanReview]:
        """List reviews, ordered by decision priority then plan name."""
        with get_session(self._session_factory) as session:
            query = session.query(PlanReviewRow)
            if decision_filter is not None:
                query = query.filter(PlanReviewRow.decision == decision_filter.value)
            if status_filter is not None:
                query = query.filter(PlanReviewRow.status == status_filter.value)
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    PlanReviewRow.plan_name.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(PlanReviewRow.plan_name).all()
            results = [self._row_to_review(r) for r in rows]
            results.sort(key=lambda r: (decision_rank(r.decision), r.plan_name))
            return results

    def close_review(self, review_id: str) -> bool:
        """Close a review (mark as closed)."""
        with get_session(self._session_factory) as session:
            row = session.get(PlanReviewRow, review_id)
            if row is None:
                return False
            prior_decision = row.decision
            prior_status = row.status
            row.status = PlanReviewStatus.CLOSED.value
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(
                session,
                review_id,
                "closed",
                details=f"prior_decision={prior_decision}, prior_status={prior_status}",
            )
            return True

    def supersede_review(self, old_id: str, new_id: str) -> bool:
        """Mark old review as superseded by new review.

        Sets the superseded_by field on old record and marks it closed.
        Both records must exist.  Self-supersession is rejected.
        """
        if old_id == new_id:
            return False
        with get_session(self._session_factory) as session:
            old_row = session.get(PlanReviewRow, old_id)
            new_row = session.get(PlanReviewRow, new_id)
            if old_row is None or new_row is None:
                return False
            now = datetime.now(timezone.utc).isoformat()
            old_row.decision = PlanReviewDecision.SUPERSEDED.value
            old_row.status = PlanReviewStatus.CLOSED.value
            old_row.superseded_by = new_id
            old_row.updated_at = now
            self._record_event(
                session, old_id, "superseded", details=f"superseded_by={new_id}"
            )
            return True

    def review_count(self) -> int:
        """Return total number of plan review records."""
        with get_session(self._session_factory) as session:
            return session.query(PlanReviewRow).count()

    def to_json(
        self,
        name_filter: str | None = None,
        decision_filter: PlanReviewDecision | None = None,
        status_filter: PlanReviewStatus | None = None,
    ) -> str:
        """Return reviews as JSON string."""
        reviews = self.list_reviews(
            name_filter=name_filter,
            decision_filter=decision_filter,
            status_filter=status_filter,
        )
        return json.dumps([r.to_dict() for r in reviews], indent=2, default=str)

    # --- Internal ---

    def _record_event(
        self, session: Any, review_id: str, event_type: str, details: str | None = None
    ) -> None:
        event = PlanReviewEventRow(
            event_id=str(uuid4()),
            review_id=review_id,
            event_type=event_type,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            details=details,
        )
        session.add(event)

    @staticmethod
    def _row_to_review(row: PlanReviewRow) -> PlanReview:
        decision = _coerce_enum(row.decision, PlanReviewDecision)
        reason = _coerce_enum(row.reason, PlanReviewReason)
        status = _coerce_enum(row.status, PlanReviewStatus)

        evidence: list[PlanReviewEvidence] = []
        if row.evidence_json is not None:
            try:
                raw = json.loads(row.evidence_json)
                evidence = [PlanReviewEvidence.from_dict(e) for e in raw]
            except (json.JSONDecodeError, TypeError):
                evidence = []

        metadata: dict[str, Any] = {}
        if row.metadata_json is not None:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        return PlanReview(
            review_id=row.review_id,
            plan_id=row.plan_id,
            plan_name=row.plan_name,
            decision=decision,
            reason=reason,
            status=status,
            reviewer=row.reviewer,
            notes=row.notes,
            evidence=evidence,
            metadata=metadata,
            superseded_by=row.superseded_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
