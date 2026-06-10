"""Learning Candidate Engine — identifies patterns worth learning.

Does NOT learn them.  Does NOT mutate registries.  Does NOT execute
workflows.  Produces suggested candidates only.

Consumes:
- capability state
- evidence bundles
- failure classifications
- workflow registry

Strategic purpose: bridge between static knowledge and future
self-improvement.
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


class CandidateType(str, Enum):
    """Type of learning candidate."""

    REPEATED_SUCCESS = "repeated_success"
    REPEATED_FAILURE = "repeated_failure"
    REPEATED_WORKFLOW = "repeated_workflow"
    RECURRING_PARAMETER_USAGE = "recurring_parameter_usage"
    RECURRING_VALIDATION_PATTERN = "recurring_validation_pattern"


class CandidateStrength(str, Enum):
    """Confidence/strength of a candidate."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    SPECULATIVE = "speculative"


class CandidateStatus(str, Enum):
    """Lifecycle status of a candidate."""

    ACTIVE = "active"
    MERGED = "merged"
    DISMISSED = "dismissed"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class LearningCandidateRow(Base):
    """Persisted learning candidate."""

    __tablename__ = "learning_candidates"

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    source_json: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CandidateSource:
    """Where a candidate was observed."""

    def __init__(
        self,
        source_type: str = "",
        source_id: str = "",
        source_name: str = "",
        observation_timestamp: str | None = None,
    ) -> None:
        self.source_type = source_type
        self.source_id = source_id
        self.source_name = source_name
        self.observation_timestamp = observation_timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "observation_timestamp": self.observation_timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateSource:
        return cls(
            source_type=data.get("source_type", ""),
            source_id=data.get("source_id", ""),
            source_name=data.get("source_name", ""),
            observation_timestamp=data.get("observation_timestamp"),
        )


class CandidateEvidence:
    """Evidence supporting a candidate."""

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
    def from_dict(cls, data: dict[str, Any]) -> CandidateEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            evidence_path=data.get("evidence_path", ""),
            description=data.get("description", ""),
            timestamp=data.get("timestamp"),
        )


class LearningCandidate:
    """A pattern identified as worth learning."""

    def __init__(
        self,
        candidate_id: str = "",
        candidate_name: str = "",
        candidate_type: CandidateType | str = CandidateType.REPEATED_SUCCESS,
        strength: CandidateStrength | str = CandidateStrength.WEAK,
        status: CandidateStatus | str = CandidateStatus.ACTIVE,
        confidence_score: int = 0,
        observation_count: int = 1,
        description: str | None = None,
        sources: list[CandidateSource] | None = None,
        evidence: list[CandidateEvidence] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.candidate_id = candidate_id or str(uuid4())
        self.candidate_name = candidate_name
        self.candidate_type = (
            candidate_type
            if isinstance(candidate_type, CandidateType)
            else CandidateType(candidate_type)
        )
        self.strength = (
            strength if isinstance(strength, CandidateStrength) else CandidateStrength(strength)
        )
        self.status = status if isinstance(status, CandidateStatus) else CandidateStatus(status)
        self.confidence_score = confidence_score
        self.observation_count = observation_count
        self.description = description
        self.sources = sources or []
        self.evidence = evidence or []
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "candidate_type": self.candidate_type.value,
            "strength": self.strength.value,
            "status": self.status.value,
            "confidence_score": self.confidence_score,
            "observation_count": self.observation_count,
            "description": self.description,
            "sources": [s.to_dict() for s in self.sources],
            "evidence": [e.to_dict() for e in self.evidence],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _coerce_enum(value: str, enum_cls: type[Enum]) -> Enum | str:
    """Coerce a string to an enum member, returning the raw string on failure."""
    try:
        return enum_cls(value)
    except ValueError:
        return value


def _merge_json_list(existing_json: str | None, new_items: list[dict[str, Any]]) -> str:
    """Merge new dicts into an existing JSON-encoded list."""
    existing: list[dict[str, Any]] = []
    if existing_json:
        try:
            existing = json.loads(existing_json)
        except (json.JSONDecodeError, TypeError):
            existing = []
    existing.extend(new_items)
    return json.dumps(existing, default=str)


# Confidence ordering: strength → score mapping for deterministic sorting
STRENGTH_ORDER: dict[CandidateStrength, int] = {
    CandidateStrength.STRONG: 4,
    CandidateStrength.MODERATE: 3,
    CandidateStrength.WEAK: 2,
    CandidateStrength.SPECULATIVE: 1,
}


class LearningCandidateRegistry:
    """Governed registry of learning candidates.

    Identifies patterns worth learning.  Does not learn them.
    Backed by SQLite via SQLAlchemy.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    def register_candidate(self, candidate: LearningCandidate) -> LearningCandidate:
        """Register a new learning candidate or merge with existing duplicate."""
        if not candidate.candidate_name:
            raise ValueError("candidate_name must not be empty")

        with get_session(self._session_factory) as session:
            now = datetime.now(timezone.utc).isoformat()

            # Check for existing duplicate (same name + type)
            existing_row = (
                session.query(LearningCandidateRow)
                .filter(
                    LearningCandidateRow.candidate_name == candidate.candidate_name,
                    LearningCandidateRow.candidate_type == candidate.candidate_type.value,
                    LearningCandidateRow.status == CandidateStatus.ACTIVE.value,
                )
                .first()
            )

            if existing_row:
                # Merge: increment observation, add new sources/evidence
                existing_row.observation_count += 1
                existing_row.updated_at = now

                existing_row.source_json = _merge_json_list(
                    existing_row.source_json,
                    [s.to_dict() for s in candidate.sources],
                )
                existing_row.evidence_json = _merge_json_list(
                    existing_row.evidence_json,
                    [e.to_dict() for e in candidate.evidence],
                )

                # Update confidence based on observations
                existing_row.confidence_score = min(
                    100, existing_row.confidence_score + candidate.confidence_score
                )

                # Upgrade strength if warranted
                if existing_row.observation_count >= 5:
                    existing_row.strength = CandidateStrength.STRONG.value
                elif existing_row.observation_count >= 3:
                    existing_row.strength = CandidateStrength.MODERATE.value

                # Return merged candidate
                return self._row_to_candidate(existing_row)
            else:
                row = LearningCandidateRow(
                    candidate_id=candidate.candidate_id,
                    candidate_name=candidate.candidate_name,
                    candidate_type=candidate.candidate_type.value,
                    strength=candidate.strength.value,
                    status=candidate.status.value,
                    confidence_score=candidate.confidence_score,
                    observation_count=candidate.observation_count,
                    description=candidate.description,
                    source_json=(
                        json.dumps([s.to_dict() for s in candidate.sources], default=str)
                        if candidate.sources is not None
                        else None
                    ),
                    evidence_json=(
                        json.dumps([e.to_dict() for e in candidate.evidence], default=str)
                        if candidate.evidence is not None
                        else None
                    ),
                    metadata_json=(
                        json.dumps(candidate.metadata, default=str)
                        if candidate.metadata is not None
                        else None
                    ),
                    created_at=candidate.created_at,
                    updated_at=now,
                )
                session.add(row)
                candidate.updated_at = now
                return candidate

    def get_candidate(self, candidate_id: str) -> LearningCandidate | None:
        """Get a candidate by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(LearningCandidateRow, candidate_id)
            if row is None:
                return None
            return self._row_to_candidate(row)

    def list_candidates(
        self,
        name_filter: str | None = None,
        candidate_type: CandidateType | None = None,
        include_dismissed: bool = False,
    ) -> list[LearningCandidate]:
        """List candidates ordered by confidence (strongest first)."""
        with get_session(self._session_factory) as session:
            query = session.query(LearningCandidateRow)
            if not include_dismissed:
                query = query.filter(
                    LearningCandidateRow.status != CandidateStatus.DISMISSED.value
                )
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    LearningCandidateRow.candidate_name.ilike(f"%{escaped}%", escape="\\")
                )
            if candidate_type is not None:
                query = query.filter(
                    LearningCandidateRow.candidate_type == candidate_type.value
                )

            rows = query.order_by(
                LearningCandidateRow.confidence_score.desc(),
                LearningCandidateRow.candidate_name,
            ).all()

            return [self._row_to_candidate(r) for r in rows]

    def dismiss(self, candidate_id: str) -> bool:
        """Mark a candidate as dismissed."""
        with get_session(self._session_factory) as session:
            row = session.get(LearningCandidateRow, candidate_id)
            if row is None:
                return False
            row.status = CandidateStatus.DISMISSED.value
            row.updated_at = datetime.now(timezone.utc).isoformat()
            return True

    def candidate_count(self) -> int:
        """Total number of candidates (including dismissed)."""
        with get_session(self._session_factory) as session:
            return session.query(LearningCandidateRow).count()

    def to_json(
        self,
        name_filter: str | None = None,
        candidate_type: CandidateType | None = None,
        include_dismissed: bool = False,
    ) -> str:
        """Return candidates as JSON string."""
        candidates = self.list_candidates(
            name_filter=name_filter,
            candidate_type=candidate_type,
            include_dismissed=include_dismissed,
        )
        return json.dumps([c.to_dict() for c in candidates], indent=2, default=str)

    # --- Internal ---

    @staticmethod
    def _row_to_candidate(row: LearningCandidateRow) -> LearningCandidate:
        ctype = _coerce_enum(row.candidate_type, CandidateType)
        strength = _coerce_enum(row.strength, CandidateStrength)
        status = _coerce_enum(row.status, CandidateStatus)

        sources: list[CandidateSource] = []
        if row.source_json:
            try:
                sources = [CandidateSource.from_dict(d) for d in json.loads(row.source_json)]
            except (json.JSONDecodeError, TypeError):
                sources = []

        evidence: list[CandidateEvidence] = []
        if row.evidence_json:
            try:
                evidence = [CandidateEvidence.from_dict(d) for d in json.loads(row.evidence_json)]
            except (json.JSONDecodeError, TypeError):
                evidence = []

        metadata: dict[str, Any] = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        return LearningCandidate(
            candidate_id=row.candidate_id,
            candidate_name=row.candidate_name,
            candidate_type=ctype,
            strength=strength,
            status=status,
            confidence_score=row.confidence_score,
            observation_count=row.observation_count,
            description=row.description,
            sources=sources,
            evidence=evidence,
            metadata=metadata,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
