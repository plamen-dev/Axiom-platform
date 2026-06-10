"""Knowledge Source Registry — governed registry of all knowledge origins.

Tracks every source of knowledge that Axiom may consume.  Metadata and
governance only.  No retrieval, no embeddings, no vector DB, no graph,
no learning, no workflow execution.

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
# Knowledge source types
# ---------------------------------------------------------------------------


class KnowledgeSourceType(str, Enum):
    """Classification of knowledge source origin."""

    ARCHITECTURE_DOC = "architecture_doc"
    RUNBOOK = "runbook"
    SKILL = "skill"
    PR_SNAPSHOT = "pr_snapshot"
    EVIDENCE_BUNDLE = "evidence_bundle"
    CAPABILITY_STATE = "capability_state"
    VALIDATION_REGISTRY = "validation_registry"
    COMMAND_REGISTRY = "command_registry"
    DISCOVERY_CANDIDATE = "discovery_candidate"
    FOUNDER_DOCUMENT = "founder_document"
    WORKFLOW_DOCUMENT = "workflow_document"
    EXTERNAL_REFERENCE = "external_reference"


# ---------------------------------------------------------------------------
# Knowledge source status
# ---------------------------------------------------------------------------


class KnowledgeSourceStatus(str, Enum):
    """Lifecycle status of a knowledge source."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class KnowledgeSourceRow(Base):
    """Persisted knowledge source definition."""

    __tablename__ = "knowledge_sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deprecated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trust_level: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    notes: Mapped[str] = mapped_column(Text, nullable=True)


class KnowledgeSourceEventRow(Base):
    """Event log for knowledge source lifecycle changes."""

    __tablename__ = "knowledge_source_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp_utc: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models (non-ORM — used for API/CLI output)
# ---------------------------------------------------------------------------


class KnowledgeSourceMetadata:
    """Rich metadata for a knowledge source."""

    def __init__(
        self,
        source_id: str,
        source_name: str,
        source_type: KnowledgeSourceType | str,
        path: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        enabled: bool = True,
        deprecated: bool = False,
        trust_level: str = "unknown",
        notes: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.source_id = source_id
        self.source_name = source_name
        self.source_type = source_type
        self.path = path
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.enabled = enabled
        self.deprecated = deprecated
        self.trust_level = trust_level
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": _serialize_source_type(self.source_type),
            "path": self.path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
            "deprecated": self.deprecated,
            "trust_level": self.trust_level,
            "notes": self.notes,
        }

    @property
    def status(self) -> KnowledgeSourceStatus:
        if self.deprecated:
            return KnowledgeSourceStatus.DEPRECATED
        if not self.enabled:
            return KnowledgeSourceStatus.DISABLED
        return KnowledgeSourceStatus.ACTIVE


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _serialize_source_type(source_type: KnowledgeSourceType | str) -> str:
    """Convert source_type to its string value for persistence."""
    return source_type.value if isinstance(source_type, KnowledgeSourceType) else source_type


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards (% and _) in user-supplied filter strings."""
    return value.replace("%", r"\%").replace("_", r"\_")


class KnowledgeSourceRegistry:
    """Governed registry of all knowledge sources Axiom may consume.

    Backed by SQLite via SQLAlchemy.  Supports register, list, refresh,
    enable/disable, and deprecation.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    def register(self, source: KnowledgeSourceMetadata) -> KnowledgeSourceMetadata:
        """Register a new knowledge source (or update if source_id exists).

        Returns the metadata reflecting the persisted state (with updated
        timestamps for existing sources).
        """
        with get_session(self._session_factory) as session:
            existing = session.get(KnowledgeSourceRow, source.source_id)
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                existing.source_name = source.source_name
                existing.source_type = _serialize_source_type(source.source_type)
                existing.path = source.path
                existing.updated_at = now
                existing.enabled = 1 if source.enabled else 0
                existing.deprecated = 1 if source.deprecated else 0
                existing.trust_level = source.trust_level
                existing.notes = source.notes
                self._record_event(session, source.source_id, "updated")
                source.updated_at = now
            else:
                row = KnowledgeSourceRow(
                    source_id=source.source_id,
                    source_name=source.source_name,
                    source_type=_serialize_source_type(source.source_type),
                    path=source.path,
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                    enabled=1 if source.enabled else 0,
                    deprecated=1 if source.deprecated else 0,
                    trust_level=source.trust_level,
                    notes=source.notes,
                )
                session.add(row)
                self._record_event(session, source.source_id, "registered")
        return source

    def list_sources(
        self,
        include_disabled: bool = False,
        source_type: KnowledgeSourceType | None = None,
        name_filter: str | None = None,
    ) -> list[KnowledgeSourceMetadata]:
        """List registered sources, optionally filtered."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeSourceRow)
            if not include_disabled:
                query = query.filter(KnowledgeSourceRow.enabled == 1)
            if source_type is not None:
                query = query.filter(KnowledgeSourceRow.source_type == source_type.value)
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    KnowledgeSourceRow.source_name.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(KnowledgeSourceRow.source_name).all()
            return [self._row_to_metadata(r) for r in rows]

    def get(self, source_id: str) -> KnowledgeSourceMetadata | None:
        """Get a single source by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeSourceRow, source_id)
            if row is None:
                return None
            return self._row_to_metadata(row)

    def disable(self, source_id: str) -> bool:
        """Disable a source (excluded from default listing)."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeSourceRow, source_id)
            if row is None:
                return False
            row.enabled = 0
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(session, source_id, "disabled")
            return True

    def enable(self, source_id: str) -> bool:
        """Re-enable a previously disabled source."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeSourceRow, source_id)
            if row is None:
                return False
            row.enabled = 1
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(session, source_id, "enabled")
            return True

    def deprecate(self, source_id: str) -> bool:
        """Mark a source as deprecated."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeSourceRow, source_id)
            if row is None:
                return False
            row.deprecated = 1
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_event(session, source_id, "deprecated")
            return True

    def refresh(
        self,
        include_disabled: bool = False,
        name_filter: str | None = None,
    ) -> list[KnowledgeSourceMetadata]:
        """Refresh and return sources (deterministic re-read).

        This is a deterministic operation: repeated calls with the same
        database state produce the same result.  Accepts the same filter
        parameters as list_sources so CLI flags are honoured.
        """
        return self.list_sources(include_disabled=include_disabled, name_filter=name_filter)

    def to_json(
        self,
        include_disabled: bool = False,
        name_filter: str | None = None,
    ) -> str:
        """Return sources as JSON string."""
        sources = self.list_sources(include_disabled=include_disabled, name_filter=name_filter)
        return json.dumps([s.to_dict() for s in sources], indent=2, default=str)

    def source_count(self) -> int:
        """Return total number of registered sources (including disabled)."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeSourceRow).count()

    # --- Internal ---

    def _record_event(self, session: Any, source_id: str, event_type: str) -> None:
        event = KnowledgeSourceEventRow(
            event_id=str(uuid4()),
            source_id=source_id,
            event_type=event_type,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            details=None,
        )
        session.add(event)

    @staticmethod
    def _row_to_metadata(row: KnowledgeSourceRow) -> KnowledgeSourceMetadata:
        try:
            source_type = KnowledgeSourceType(row.source_type)
        except ValueError:
            source_type = row.source_type  # type: ignore[assignment]
        return KnowledgeSourceMetadata(
            source_id=row.source_id,
            source_name=row.source_name,
            source_type=source_type,
            path=row.path,
            created_at=row.created_at,
            updated_at=row.updated_at,
            enabled=bool(row.enabled),
            deprecated=bool(row.deprecated),
            trust_level=row.trust_level,
            notes=row.notes,
        )
