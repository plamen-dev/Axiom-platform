"""Knowledge Provenance & Trust Engine — provenance and trust for knowledge.

Knowledge without provenance is dangerous.  This module establishes trust
infrastructure so Axiom can distinguish facts from suggestions.

Metadata and governance only.  No automatic trust updates, no confidence
learning, no LLM scoring.

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
# Trust levels (ordered from highest to lowest trust)
# ---------------------------------------------------------------------------


class TrustLevel(str, Enum):
    """Trust classification for knowledge provenance.

    Ordered from highest to lowest trust:
    1. founder_verified — directly authored/verified by founders
    2. human_verified — verified by human review
    3. evidence_supported — backed by evidence artifacts
    4. derived — derived from trusted sources
    5. candidate — unverified, pending review
    6. deprecated — previously trusted, now superseded
    """

    FOUNDER_VERIFIED = "founder_verified"
    HUMAN_VERIFIED = "human_verified"
    EVIDENCE_SUPPORTED = "evidence_supported"
    DERIVED = "derived"
    CANDIDATE = "candidate"
    DEPRECATED = "deprecated"


# Canonical trust ordering (index 0 = highest trust)
TRUST_ORDER: list[TrustLevel] = [
    TrustLevel.FOUNDER_VERIFIED,
    TrustLevel.HUMAN_VERIFIED,
    TrustLevel.EVIDENCE_SUPPORTED,
    TrustLevel.DERIVED,
    TrustLevel.CANDIDATE,
    TrustLevel.DEPRECATED,
]


def trust_rank(level: TrustLevel | str) -> int:
    """Return numeric rank for a trust level (lower = more trusted).

    Unknown levels receive the lowest rank (len(TRUST_ORDER)).
    """
    if isinstance(level, str):
        try:
            level = TrustLevel(level)
        except ValueError:
            return len(TRUST_ORDER)
    try:
        return TRUST_ORDER.index(level)
    except ValueError:
        return len(TRUST_ORDER)


# ---------------------------------------------------------------------------
# Source confidence
# ---------------------------------------------------------------------------


class SourceConfidence(str, Enum):
    """Confidence classification for the originating source."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Provenance status
# ---------------------------------------------------------------------------


class ProvenanceStatus(str, Enum):
    """Lifecycle status of a provenance record."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class KnowledgeProvenanceRow(Base):
    """Persisted provenance record."""

    __tablename__ = "knowledge_provenance"

    provenance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_name: Mapped[str] = mapped_column(String(300), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_paths: Mapped[str] = mapped_column(Text, nullable=True)
    approving_source: Mapped[str] = mapped_column(String(200), nullable=True)
    confidence_score: Mapped[str] = mapped_column(String(10), nullable=True)
    superseded_by: Mapped[str] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    deprecated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class KnowledgeProvenanceEventRow(Base):
    """Event log for provenance lifecycle changes."""

    __tablename__ = "knowledge_provenance_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provenance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class KnowledgeProvenance:
    """Provenance record for a piece of knowledge."""

    def __init__(
        self,
        provenance_id: str = "",
        knowledge_name: str = "",
        trust_level: TrustLevel | str = TrustLevel.CANDIDATE,
        source_confidence: SourceConfidence | str = SourceConfidence.UNKNOWN,
        status: ProvenanceStatus | str = ProvenanceStatus.ACTIVE,
        origin: str | None = None,
        evidence_paths: list[str] | None = None,
        approving_source: str | None = None,
        confidence_score: float | None = None,
        superseded_by: str | None = None,
        notes: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.provenance_id = provenance_id or str(uuid4())
        self.knowledge_name = knowledge_name
        if isinstance(trust_level, TrustLevel):
            self.trust_level = trust_level
        else:
            try:
                self.trust_level = TrustLevel(trust_level)
            except ValueError:
                self.trust_level = trust_level
        if isinstance(source_confidence, SourceConfidence):
            self.source_confidence = source_confidence
        else:
            try:
                self.source_confidence = SourceConfidence(source_confidence)
            except ValueError:
                self.source_confidence = source_confidence
        if isinstance(status, ProvenanceStatus):
            self.status = status
        else:
            try:
                self.status = ProvenanceStatus(status)
            except ValueError:
                self.status = status
        self.origin = origin
        self.evidence_paths = evidence_paths or []
        self.approving_source = approving_source
        self.confidence_score = confidence_score
        self.superseded_by = superseded_by
        self.notes = notes
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance_id": self.provenance_id,
            "knowledge_name": self.knowledge_name,
            "trust_level": self.trust_level.value if isinstance(self.trust_level, TrustLevel) else self.trust_level,
            "source_confidence": self.source_confidence.value if isinstance(self.source_confidence, SourceConfidence) else self.source_confidence,
            "status": self.status.value if isinstance(self.status, ProvenanceStatus) else self.status,
            "origin": self.origin,
            "evidence_paths": self.evidence_paths,
            "approving_source": self.approving_source,
            "confidence_score": self.confidence_score,
            "superseded_by": self.superseded_by,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards (% and _) and the escape char (\\) in user-supplied filter strings."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _serialize_trust_level(level: TrustLevel | str) -> str:
    return level.value if isinstance(level, TrustLevel) else level


def _serialize_confidence(conf: SourceConfidence | str) -> str:
    return conf.value if isinstance(conf, SourceConfidence) else conf


def _serialize_status(status: ProvenanceStatus | str) -> str:
    return status.value if isinstance(status, ProvenanceStatus) else status


class KnowledgeProvenanceRegistry:
    """Governed registry of knowledge provenance and trust.

    Backed by SQLite via SQLAlchemy.  Supports register, list, deprecate,
    supersede, and trust ordering.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    def register(self, prov: KnowledgeProvenance) -> KnowledgeProvenance:
        """Register or update a provenance record.

        Returns the record reflecting the persisted state.
        """
        if not prov.knowledge_name:
            raise ValueError("knowledge_name must not be empty")

        with get_session(self._session_factory) as session:
            existing = session.get(KnowledgeProvenanceRow, prov.provenance_id)
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                existing.knowledge_name = prov.knowledge_name
                existing.trust_level = _serialize_trust_level(prov.trust_level)
                existing.source_confidence = _serialize_confidence(prov.source_confidence)
                existing.status = _serialize_status(prov.status)
                existing.origin = prov.origin
                existing.evidence_paths = json.dumps(prov.evidence_paths) if prov.evidence_paths is not None else None
                existing.approving_source = prov.approving_source
                existing.confidence_score = str(prov.confidence_score) if prov.confidence_score is not None else None
                existing.superseded_by = prov.superseded_by
                existing.notes = prov.notes
                existing.updated_at = now
                existing.deprecated = 1 if prov.status == ProvenanceStatus.DEPRECATED else 0
                self._record_event(session, prov.provenance_id, "updated")
                prov.updated_at = now
            else:
                row = KnowledgeProvenanceRow(
                    provenance_id=prov.provenance_id,
                    knowledge_name=prov.knowledge_name,
                    trust_level=_serialize_trust_level(prov.trust_level),
                    source_confidence=_serialize_confidence(prov.source_confidence),
                    status=_serialize_status(prov.status),
                    origin=prov.origin,
                    evidence_paths=json.dumps(prov.evidence_paths) if prov.evidence_paths is not None else None,
                    approving_source=prov.approving_source,
                    confidence_score=str(prov.confidence_score) if prov.confidence_score is not None else None,
                    superseded_by=prov.superseded_by,
                    notes=prov.notes,
                    created_at=prov.created_at,
                    updated_at=prov.updated_at,
                    deprecated=1 if prov.status == ProvenanceStatus.DEPRECATED else 0,
                )
                session.add(row)
                self._record_event(session, prov.provenance_id, "registered")
        return prov

    def get(self, provenance_id: str) -> KnowledgeProvenance | None:
        """Get a single provenance record by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeProvenanceRow, provenance_id)
            if row is None:
                return None
            return self._row_to_provenance(row)

    def list_provenance(
        self,
        name_filter: str | None = None,
        trust_level: TrustLevel | None = None,
        include_deprecated: bool = False,
    ) -> list[KnowledgeProvenance]:
        """List provenance records, ordered by trust rank then name."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeProvenanceRow)
            if not include_deprecated:
                query = query.filter(KnowledgeProvenanceRow.deprecated == 0)
            if trust_level is not None:
                query = query.filter(KnowledgeProvenanceRow.trust_level == trust_level.value)
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    KnowledgeProvenanceRow.knowledge_name.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(KnowledgeProvenanceRow.knowledge_name).all()
            results = [self._row_to_provenance(r) for r in rows]
            # Sort by trust rank (deterministic ordering)
            results.sort(key=lambda p: (trust_rank(p.trust_level), p.knowledge_name))
            return results

    def deprecate(self, provenance_id: str) -> bool:
        """Mark a provenance record as deprecated."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeProvenanceRow, provenance_id)
            if row is None:
                return False
            row.status = ProvenanceStatus.DEPRECATED.value
            row.deprecated = 1
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(session, provenance_id, "deprecated")
            return True

    def supersede(self, old_id: str, new_id: str) -> bool:
        """Mark old provenance as superseded by new provenance.

        Sets old record status to SUPERSEDED and records superseded_by.
        Both records must exist.
        """
        with get_session(self._session_factory) as session:
            old_row = session.get(KnowledgeProvenanceRow, old_id)
            new_row = session.get(KnowledgeProvenanceRow, new_id)
            if old_row is None or new_row is None:
                return False
            now = datetime.now(timezone.utc).isoformat()
            old_row.status = ProvenanceStatus.SUPERSEDED.value
            old_row.superseded_by = new_id
            old_row.updated_at = now
            self._record_event(session, old_id, "superseded", details=f"superseded_by={new_id}")
            return True

    def get_supersession_chain(self, provenance_id: str) -> list[KnowledgeProvenance]:
        """Walk the supersession chain starting from the given record.

        Returns the chain from oldest to newest.  Stops on cycle or missing link.
        """
        chain: list[KnowledgeProvenance] = []
        visited: set[str] = set()
        current_id: str | None = provenance_id

        while current_id and current_id not in visited:
            visited.add(current_id)
            record = self.get(current_id)
            if record is None:
                break
            chain.append(record)
            current_id = record.superseded_by

        return chain

    def provenance_count(self) -> int:
        """Return total number of provenance records (including deprecated)."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeProvenanceRow).count()

    def to_json(
        self,
        name_filter: str | None = None,
        trust_level: TrustLevel | None = None,
        include_deprecated: bool = False,
    ) -> str:
        """Return provenance records as JSON string."""
        records = self.list_provenance(
            name_filter=name_filter,
            trust_level=trust_level,
            include_deprecated=include_deprecated,
        )
        return json.dumps([r.to_dict() for r in records], indent=2, default=str)

    # --- Internal ---

    def _record_event(
        self, session: Any, provenance_id: str, event_type: str, details: str | None = None
    ) -> None:
        event = KnowledgeProvenanceEventRow(
            event_id=str(uuid4()),
            provenance_id=provenance_id,
            event_type=event_type,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            details=details,
        )
        session.add(event)

    @staticmethod
    def _row_to_provenance(row: KnowledgeProvenanceRow) -> KnowledgeProvenance:
        try:
            tl = TrustLevel(row.trust_level)
        except ValueError:
            tl = row.trust_level  # type: ignore[assignment]
        try:
            sc = SourceConfidence(row.source_confidence)
        except ValueError:
            sc = row.source_confidence  # type: ignore[assignment]
        try:
            st = ProvenanceStatus(row.status)
        except ValueError:
            st = row.status  # type: ignore[assignment]

        evidence = []
        if row.evidence_paths is not None:
            try:
                evidence = json.loads(row.evidence_paths)
            except (json.JSONDecodeError, TypeError):
                evidence = []

        confidence_score = None
        if row.confidence_score is not None:
            try:
                confidence_score = float(row.confidence_score)
            except (ValueError, TypeError):
                confidence_score = None

        return KnowledgeProvenance(
            provenance_id=row.provenance_id,
            knowledge_name=row.knowledge_name,
            trust_level=tl,
            source_confidence=sc,
            status=st,
            origin=row.origin,
            evidence_paths=evidence,
            approving_source=row.approving_source,
            confidence_score=confidence_score,
            superseded_by=row.superseded_by,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
