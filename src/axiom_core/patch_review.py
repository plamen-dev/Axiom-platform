"""Patch Review and Approval Queue v1.

Human review and approval for patch proposals. The approval gate before
Axiom begins applying patches. Read-only: never edits files, never runs
git operations, never applies patches.
"""

from __future__ import annotations

import json
import os
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


class ReviewDecision(str, Enum):
    """Possible decisions for a patch review."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class PatchReviewRow(Base):
    """SQLAlchemy row for a patch review."""

    __tablename__ = "patch_reviews"

    review_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    decision: Mapped[str] = mapped_column(
        String(30), nullable=False, default="proposed",
    )
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=True)
    evidence_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
    )
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)


class PatchReviewHistoryRow(Base):
    """SQLAlchemy row for review history entries."""

    __tablename__ = "patch_review_history"

    entry_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    review_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PatchReviewEvidence:
    """Evidence attached to a review decision."""

    def __init__(
        self,
        description: str = "",
        evidence_type: str = "observation",
        artifact_path: str = "",
    ) -> None:
        self.description = description
        self.evidence_type = evidence_type
        self.artifact_path = artifact_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "evidence_type": self.evidence_type,
            "artifact_path": self.artifact_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchReviewEvidence:
        return cls(
            description=data.get("description", ""),
            evidence_type=data.get("evidence_type", "observation"),
            artifact_path=data.get("artifact_path", ""),
        )


class PatchReviewHistoryEntry:
    """A single entry in a proposal's review history."""

    def __init__(
        self,
        entry_id: str = "",
        proposal_id: str = "",
        review_id: str = "",
        decision: ReviewDecision = ReviewDecision.PROPOSED,
        reason: str = "",
        reviewer: str = "",
        created_at: str | None = None,
    ) -> None:
        self.entry_id = entry_id or str(uuid4())
        self.proposal_id = proposal_id
        self.review_id = review_id
        self.decision = decision
        self.reason = reason
        self.reviewer = reviewer
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "proposal_id": self.proposal_id,
            "review_id": self.review_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "reviewer": self.reviewer,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: PatchReviewHistoryRow) -> PatchReviewHistoryEntry:
        return cls(
            entry_id=row.entry_id,
            proposal_id=row.proposal_id,
            review_id=row.review_id,
            decision=ReviewDecision(row.decision),
            reason=row.reason or "",
            reviewer=row.reviewer or "",
            created_at=row.created_at,
        )


class PatchReview:
    """A review decision for a patch proposal."""

    def __init__(
        self,
        review_id: str = "",
        proposal_id: str = "",
        decision: ReviewDecision = ReviewDecision.PROPOSED,
        reason: str = "",
        reviewer: str = "",
        evidence: list[PatchReviewEvidence] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.review_id = review_id or str(uuid4())
        self.proposal_id = proposal_id
        self.decision = decision
        self.reason = reason
        self.reviewer = reviewer
        self.evidence = evidence or []
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "proposal_id": self.proposal_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "reviewer": self.reviewer,
            "evidence": [e.to_dict() for e in self.evidence],
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: PatchReviewRow) -> PatchReview:
        ev_data = json.loads(row.evidence_json) if row.evidence_json else []
        return cls(
            review_id=row.review_id,
            proposal_id=row.proposal_id,
            decision=ReviewDecision(row.decision),
            reason=row.reason or "",
            reviewer=row.reviewer or "",
            evidence=[PatchReviewEvidence.from_dict(e) for e in ev_data],
            created_at=row.created_at,
        )


# ---------------------------------------------------------------------------
# PatchReviewRegistry — the review engine
# ---------------------------------------------------------------------------


class PatchReviewRegistry:
    """Creates and manages reviews for patch proposals.

    Read-only with respect to source files: never edits code, never runs
    git operations, never applies patches.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        engine = create_db_engine(self._db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)
        self._proposal_registry: Any = None

    def create_review(
        self,
        proposal_id: str,
        decision: ReviewDecision,
        reason: str = "",
        reviewer: str = "",
        evidence: list[PatchReviewEvidence] | None = None,
    ) -> PatchReview:
        """Create a review for a patch proposal.

        Validates the proposal exists via the PatchProposalRegistry.
        Raises ValueError if the proposal is not found.
        """
        self._validate_proposal_exists(proposal_id)

        review = PatchReview(
            proposal_id=proposal_id,
            decision=decision,
            reason=reason,
            reviewer=reviewer,
            evidence=evidence,
        )

        self._persist_review_and_history(review)
        self._sync_proposal_status(proposal_id, decision)

        return review

    def get_review(self, review_id: str) -> PatchReview | None:
        with get_session(self._session_factory) as session:
            row = session.get(PatchReviewRow, review_id)
            if row is None:
                return None
            return PatchReview.from_row(row)

    def get_latest_review(self, proposal_id: str) -> PatchReview | None:
        with get_session(self._session_factory) as session:
            row = (
                session.query(PatchReviewRow)
                .filter(PatchReviewRow.proposal_id == proposal_id)
                .order_by(PatchReviewRow.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return PatchReview.from_row(row)

    def list_reviews(
        self,
        proposal_id: str | None = None,
        decision: ReviewDecision | None = None,
    ) -> list[PatchReview]:
        with get_session(self._session_factory) as session:
            query = session.query(PatchReviewRow)
            if proposal_id is not None:
                query = query.filter(
                    PatchReviewRow.proposal_id == proposal_id,
                )
            if decision is not None:
                query = query.filter(
                    PatchReviewRow.decision == decision.value,
                )
            query = query.order_by(PatchReviewRow.created_at.desc())
            return [PatchReview.from_row(row) for row in query.all()]

    def get_history(self, proposal_id: str) -> list[PatchReviewHistoryEntry]:
        with get_session(self._session_factory) as session:
            rows = (
                session.query(PatchReviewHistoryRow)
                .filter(PatchReviewHistoryRow.proposal_id == proposal_id)
                .order_by(PatchReviewHistoryRow.created_at.asc())
                .all()
            )
            return [PatchReviewHistoryEntry.from_row(r) for r in rows]

    # -- persistence --------------------------------------------------------

    def _persist_review_and_history(self, review: PatchReview) -> None:
        with get_session(self._session_factory) as session:
            row = PatchReviewRow(
                review_id=review.review_id,
                proposal_id=review.proposal_id,
                decision=review.decision.value,
                reason=review.reason,
                reviewer=review.reviewer,
                evidence_json=json.dumps(
                    [e.to_dict() for e in review.evidence],
                ),
                created_at=review.created_at,
            )
            entry = PatchReviewHistoryRow(
                entry_id=str(uuid4()),
                proposal_id=review.proposal_id,
                review_id=review.review_id,
                decision=review.decision.value,
                reason=review.reason,
                reviewer=review.reviewer,
                created_at=review.created_at,
            )
            session.add(row)
            session.add(entry)

    def _get_proposal_registry(self) -> Any:
        if self._proposal_registry is None:
            from axiom_core.patch_proposal import PatchProposalRegistry

            self._proposal_registry = PatchProposalRegistry(
                db_path=self._db_path,
            )
        return self._proposal_registry

    def _validate_proposal_exists(self, proposal_id: str) -> None:
        proposal = self._get_proposal_registry().get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Patch proposal not found: {proposal_id}")

    def _sync_proposal_status(
        self,
        proposal_id: str,
        decision: ReviewDecision,
    ) -> None:
        from axiom_core.patch_proposal import PatchStatus

        decision_to_status = {
            ReviewDecision.APPROVED: PatchStatus.APPROVED,
            ReviewDecision.REJECTED: PatchStatus.REJECTED,
            ReviewDecision.DEPRECATED: PatchStatus.SUPERSEDED,
        }
        new_status = decision_to_status.get(decision)
        if new_status is not None:
            self._get_proposal_registry().update_status(
                proposal_id, new_status,
            )
