"""Knowledge Object Model — universal first-class knowledge representation.

Creates a common language for all future reasoning.  Knowledge objects
are typed, named, and can form relationships.

Metadata and governance only.  No graph traversal, no semantic search,
no inference, no embeddings.

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
# Knowledge object types
# ---------------------------------------------------------------------------


class KnowledgeObjectType(str, Enum):
    """Classification of knowledge objects."""

    CONCEPT = "concept"
    RULE = "rule"
    WORKFLOW = "workflow"
    PATTERN = "pattern"
    CAPABILITY = "capability"
    DECISION = "decision"
    PLAYBOOK = "playbook"
    FAILURE_PATTERN = "failure_pattern"
    EVIDENCE_REFERENCE = "evidence_reference"


# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------


class RelationshipType(str, Enum):
    """Types of relationships between knowledge objects."""

    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    VALIDATED_BY = "validated_by"
    SUPERSEDES = "supersedes"
    RELATED_TO = "related_to"
    CONSUMES = "consumes"
    PRODUCES = "produces"


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class KnowledgeObjectRow(Base):
    """Persisted knowledge object."""

    __tablename__ = "knowledge_objects"

    object_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_name: Mapped[str] = mapped_column(String(200), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)


class KnowledgeRelationshipRow(Base):
    """Persisted relationship between two knowledge objects."""

    __tablename__ = "knowledge_relationships"

    relationship_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_object_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_object_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models (non-ORM — used for API/CLI output)
# ---------------------------------------------------------------------------


def _serialize_object_type(obj_type: KnowledgeObjectType | str) -> str:
    """Convert object_type to its string value for persistence."""
    return obj_type.value if isinstance(obj_type, KnowledgeObjectType) else obj_type


def _serialize_relationship_type(rel_type: RelationshipType | str) -> str:
    """Convert relationship_type to its string value for persistence."""
    return rel_type.value if isinstance(rel_type, RelationshipType) else rel_type


class KnowledgeObject:
    """Rich metadata for a knowledge object."""

    def __init__(
        self,
        object_id: str,
        object_name: str,
        object_type: KnowledgeObjectType | str,
        description: str | None = None,
        source_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        version: str = "1.0",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.object_id = object_id
        self.object_name = object_name
        self.object_type = object_type
        self.description = description
        self.source_id = source_id
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.version = version
        self.metadata = metadata if metadata is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_name": self.object_name,
            "object_type": _serialize_object_type(self.object_type),
            "description": self.description,
            "source_id": self.source_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "metadata": self.metadata,
        }


class KnowledgeRelationship:
    """Relationship between two knowledge objects."""

    def __init__(
        self,
        relationship_id: str | None = None,
        source_object_id: str = "",
        target_object_id: str = "",
        relationship_type: RelationshipType | str = RelationshipType.RELATED_TO,
        created_at: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.relationship_id = relationship_id or str(uuid4())
        self.source_object_id = source_object_id
        self.target_object_id = target_object_id
        self.relationship_type = relationship_type
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "source_object_id": self.source_object_id,
            "target_object_id": self.target_object_id,
            "relationship_type": _serialize_relationship_type(self.relationship_type),
            "created_at": self.created_at,
            "notes": self.notes,
        }


class KnowledgeReference:
    """Lightweight reference to a knowledge object (for embedding in other models)."""

    def __init__(self, object_id: str, object_name: str, object_type: str) -> None:
        self.object_id = object_id
        self.object_name = object_name
        self.object_type = object_type

    def to_dict(self) -> dict[str, str]:
        return {
            "object_id": self.object_id,
            "object_name": self.object_name,
            "object_type": self.object_type,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards (% and _) and the escape char (\\) in user-supplied filter strings."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class KnowledgeObjectRegistry:
    """Governed registry of all knowledge objects.

    Backed by SQLite via SQLAlchemy.  Supports create, list, query,
    and relationship management.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    # --- Object operations ---

    def create_object(self, obj: KnowledgeObject) -> KnowledgeObject:
        """Create or update a knowledge object."""
        with get_session(self._session_factory) as session:
            existing = session.get(KnowledgeObjectRow, obj.object_id)
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                existing.object_name = obj.object_name
                existing.object_type = _serialize_object_type(obj.object_type)
                existing.description = obj.description
                existing.source_id = obj.source_id
                existing.updated_at = now
                existing.version = obj.version
                existing.metadata_json = json.dumps(obj.metadata, default=str) if obj.metadata is not None else None
                obj.updated_at = now
            else:
                row = KnowledgeObjectRow(
                    object_id=obj.object_id,
                    object_name=obj.object_name,
                    object_type=_serialize_object_type(obj.object_type),
                    description=obj.description,
                    source_id=obj.source_id,
                    created_at=obj.created_at,
                    updated_at=obj.updated_at,
                    version=obj.version,
                    metadata_json=json.dumps(obj.metadata, default=str) if obj.metadata is not None else None,
                )
                session.add(row)
        return obj

    def get_object(self, object_id: str) -> KnowledgeObject | None:
        """Get a single knowledge object by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeObjectRow, object_id)
            if row is None:
                return None
            return self._row_to_object(row)

    def list_objects(
        self,
        object_type: KnowledgeObjectType | None = None,
        name_filter: str | None = None,
    ) -> list[KnowledgeObject]:
        """List knowledge objects, optionally filtered."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeObjectRow)
            if object_type is not None:
                query = query.filter(
                    KnowledgeObjectRow.object_type == _serialize_object_type(object_type)
                )
            if name_filter is not None:
                escaped = _escape_like(name_filter)
                query = query.filter(
                    KnowledgeObjectRow.object_name.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(KnowledgeObjectRow.object_name).all()
            return [self._row_to_object(r) for r in rows]

    def object_count(self) -> int:
        """Return total number of registered objects."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeObjectRow).count()

    def to_json(
        self,
        object_type: KnowledgeObjectType | None = None,
        name_filter: str | None = None,
    ) -> str:
        """Return objects as JSON string."""
        objects = self.list_objects(object_type=object_type, name_filter=name_filter)
        return json.dumps([o.to_dict() for o in objects], indent=2, default=str)

    # --- Relationship operations ---

    def create_relationship(self, rel: KnowledgeRelationship) -> KnowledgeRelationship:
        """Create a relationship between two objects.

        Cycles are allowed — this is metadata, not execution dependency.
        Dangling references (objects not yet registered) are permitted to
        support forward declarations and eventual consistency patterns.

        Raises ValueError if source_object_id or target_object_id is empty.
        """
        if not rel.source_object_id or not rel.target_object_id:
            raise ValueError("source_object_id and target_object_id must not be empty")
        with get_session(self._session_factory) as session:
            row = KnowledgeRelationshipRow(
                relationship_id=rel.relationship_id,
                source_object_id=rel.source_object_id,
                target_object_id=rel.target_object_id,
                relationship_type=_serialize_relationship_type(rel.relationship_type),
                created_at=rel.created_at,
                notes=rel.notes,
            )
            session.add(row)
        return rel

    def list_relationships(
        self,
        object_id: str | None = None,
        relationship_type: RelationshipType | None = None,
    ) -> list[KnowledgeRelationship]:
        """List relationships, optionally filtered by object or type."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeRelationshipRow)
            if object_id is not None:
                query = query.filter(
                    (KnowledgeRelationshipRow.source_object_id == object_id)
                    | (KnowledgeRelationshipRow.target_object_id == object_id)
                )
            if relationship_type is not None:
                query = query.filter(
                    KnowledgeRelationshipRow.relationship_type == _serialize_relationship_type(relationship_type)
                )
            rows = query.order_by(KnowledgeRelationshipRow.created_at).all()
            return [self._row_to_relationship(r) for r in rows]

    def get_relationships_for(self, object_id: str) -> list[KnowledgeRelationship]:
        """Get all relationships involving a specific object."""
        return self.list_relationships(object_id=object_id)

    def relationship_count(self) -> int:
        """Return total number of relationships."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeRelationshipRow).count()

    def relationships_to_json(
        self,
        object_id: str | None = None,
        relationship_type: RelationshipType | None = None,
    ) -> str:
        """Return relationships as JSON string."""
        rels = self.list_relationships(object_id=object_id, relationship_type=relationship_type)
        return json.dumps([r.to_dict() for r in rels], indent=2, default=str)

    # --- Internal ---

    @staticmethod
    def _row_to_object(row: KnowledgeObjectRow) -> KnowledgeObject:
        try:
            obj_type: KnowledgeObjectType | str = KnowledgeObjectType(row.object_type)
        except ValueError:
            obj_type = row.object_type
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
        return KnowledgeObject(
            object_id=row.object_id,
            object_name=row.object_name,
            object_type=obj_type,
            description=row.description,
            source_id=row.source_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
            metadata=metadata,
        )

    @staticmethod
    def _row_to_relationship(row: KnowledgeRelationshipRow) -> KnowledgeRelationship:
        try:
            rel_type: RelationshipType | str = RelationshipType(row.relationship_type)
        except ValueError:
            rel_type = row.relationship_type
        return KnowledgeRelationship(
            relationship_id=row.relationship_id,
            source_object_id=row.source_object_id,
            target_object_id=row.target_object_id,
            relationship_type=rel_type,
            created_at=row.created_at,
            notes=row.notes,
        )
