"""Autonomous Work Item Registry v1 — durable internal backlog.

Provides a registry for implementation work items that Axiom can reason
about before code is written.  Work items persist in SQLite, support
dependencies between items, and preserve full status-change history.

No code generation, no execution, no GitHub API, no external integrations.
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


class WorkItemType(str, Enum):
    """Classification of work item purpose."""

    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    CLEANUP = "cleanup"
    TEST = "test"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"
    VALIDATION = "validation"
    INVESTIGATION = "investigation"
    REVIEW_FINDING = "review_finding"


class WorkItemStatus(str, Enum):
    """Lifecycle states for a work item."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class WorkItemPriority(str, Enum):
    """Priority levels for work items."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSET = "unset"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class WorkItemRow(Base):
    """SQLAlchemy row for work items."""

    __tablename__ = "work_items"

    item_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=True)
    assigned_to: Mapped[str] = mapped_column(String(200), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class WorkItemHistoryRow(Base):
    """Audit log for work item status changes."""

    __tablename__ = "work_item_history"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str] = mapped_column(String(100), nullable=True)
    new_value: Mapped[str] = mapped_column(String(100), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=True)


class WorkItemDependencyRow(Base):
    """Dependency relationship between work items."""

    __tablename__ = "work_item_dependencies"

    dependency_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    depends_on_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class WorkItemEvidence:
    """Evidence attached to a work item."""

    def __init__(
        self,
        evidence_type: str = "",
        reference_id: str | None = None,
        description: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.reference_id = reference_id
        self.description = description
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "reference_id": self.reference_id,
            "description": self.description,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItemEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            reference_id=data.get("reference_id"),
            description=data.get("description"),
            timestamp=data.get("timestamp"),
        )


class WorkItemDependency:
    """A dependency between two work items."""

    def __init__(
        self,
        item_id: str = "",
        depends_on_id: str = "",
        dependency_type: str = "blocks",
        created_at: str | None = None,
    ) -> None:
        self.item_id = item_id
        self.depends_on_id = depends_on_id
        self.dependency_type = dependency_type
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "depends_on_id": self.depends_on_id,
            "dependency_type": self.dependency_type,
            "created_at": self.created_at,
        }


class WorkItem:
    """A work item with full lifecycle state."""

    def __init__(
        self,
        item_id: str = "",
        title: str = "",
        description: str | None = None,
        item_type: WorkItemType = WorkItemType.FEATURE,
        status: WorkItemStatus = WorkItemStatus.PROPOSED,
        priority: WorkItemPriority = WorkItemPriority.UNSET,
        created_by: str | None = None,
        assigned_to: str | None = None,
        evidence: list[WorkItemEvidence] | None = None,
        dependencies: list[WorkItemDependency] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.item_id = item_id or str(uuid4())
        self.title = title
        self.description = description
        self.item_type = item_type
        self.status = status
        self.priority = priority
        self.created_by = created_by
        self.assigned_to = assigned_to
        self.evidence = evidence if evidence is not None else []
        self.dependencies = dependencies if dependencies is not None else []
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "item_type": self.item_type.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "evidence": [e.to_dict() for e in self.evidence],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(
        cls,
        row: WorkItemRow,
        dependencies: list[WorkItemDependency] | None = None,
    ) -> WorkItem:
        evidence: list[WorkItemEvidence] = []
        if row.evidence_json:
            for e in json.loads(row.evidence_json):
                evidence.append(WorkItemEvidence.from_dict(e))
        return cls(
            item_id=row.item_id,
            title=row.title,
            description=row.description,
            item_type=WorkItemType(row.item_type),
            status=WorkItemStatus(row.status),
            priority=WorkItemPriority(row.priority),
            created_by=row.created_by,
            assigned_to=row.assigned_to,
            evidence=evidence,
            dependencies=dependencies if dependencies is not None else [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class WorkItemHistory:
    """Status change history for a work item."""

    def __init__(
        self,
        item_id: str = "",
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.item_id = item_id
        self.events = events if events is not None else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "events": self.events,
            "event_count": len(self.events),
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WorkItemRegistry:
    """Durable work item registry backed by SQLite.

    Provides CRUD for work items, dependency tracking, and status-change
    history.  Never executes code or mutates external systems.
    """

    def __init__(self, db_path: str | None = None) -> None:
        import os

        effective_path = db_path or os.environ.get("AXIOM_DB_PATH")
        engine = create_db_engine(effective_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    # -- create -------------------------------------------------------------

    def create_item(
        self,
        title: str,
        item_type: WorkItemType,
        description: str | None = None,
        priority: WorkItemPriority = WorkItemPriority.UNSET,
        created_by: str | None = None,
    ) -> WorkItem:
        now = datetime.now(timezone.utc).isoformat()
        item_id = str(uuid4())
        with get_session(self._session_factory) as session:
            row = WorkItemRow(
                item_id=item_id,
                title=title,
                description=description,
                item_type=item_type.value,
                status=WorkItemStatus.PROPOSED.value,
                priority=priority.value,
                created_by=created_by,
                evidence_json=None,
                metadata_json=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            history = WorkItemHistoryRow(
                event_id=str(uuid4()),
                item_id=item_id,
                action="created",
                old_value=None,
                new_value=WorkItemStatus.PROPOSED.value,
                actor=created_by,
                timestamp=now,
                details_json=json.dumps({"title": title, "type": item_type.value}),
            )
            session.add(history)
        return WorkItem(
            item_id=item_id,
            title=title,
            description=description,
            item_type=item_type,
            status=WorkItemStatus.PROPOSED,
            priority=priority,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )

    # -- read ---------------------------------------------------------------

    def get_item(self, item_id: str) -> WorkItem | None:
        with get_session(self._session_factory) as session:
            row = session.get(WorkItemRow, item_id)
            if row is None:
                return None
            deps = self._load_dependencies(session, item_id)
            return WorkItem.from_row(row, dependencies=deps)

    def list_items(
        self,
        status_filter: WorkItemStatus | None = None,
        type_filter: WorkItemType | None = None,
    ) -> list[WorkItem]:
        with get_session(self._session_factory) as session:
            query = session.query(WorkItemRow)
            if status_filter is not None:
                query = query.filter(WorkItemRow.status == status_filter.value)
            if type_filter is not None:
                query = query.filter(WorkItemRow.item_type == type_filter.value)
            query = query.order_by(WorkItemRow.created_at.desc())
            rows = query.all()
            if not rows:
                return []
            item_ids = [row.item_id for row in rows]
            all_dep_rows = (
                session.query(WorkItemDependencyRow)
                .filter(WorkItemDependencyRow.item_id.in_(item_ids))
                .all()
            )
            deps_by_item: dict[str, list[WorkItemDependency]] = {}
            for dep_row in all_dep_rows:
                deps_by_item.setdefault(dep_row.item_id, []).append(
                    WorkItemDependency(
                        item_id=dep_row.item_id,
                        depends_on_id=dep_row.depends_on_id,
                        dependency_type=dep_row.dependency_type,
                        created_at=dep_row.created_at,
                    )
                )
            return [
                WorkItem.from_row(row, dependencies=deps_by_item.get(row.item_id, []))
                for row in rows
            ]

    # -- update -------------------------------------------------------------

    def update_status(
        self,
        item_id: str,
        new_status: WorkItemStatus,
        actor: str | None = None,
        reason: str | None = None,
    ) -> WorkItem:
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = session.get(WorkItemRow, item_id)
            if row is None:
                raise ValueError(f"Work item not found: {item_id}")
            old_status = row.status
            if old_status == new_status.value:
                raise ValueError(
                    f"Work item '{item_id}' is already '{new_status.value}'"
                )
            row.status = new_status.value
            row.updated_at = now
            details: dict[str, Any] = {}
            if reason:
                details["reason"] = reason
            history = WorkItemHistoryRow(
                event_id=str(uuid4()),
                item_id=item_id,
                action="status_changed",
                old_value=old_status,
                new_value=new_status.value,
                actor=actor,
                timestamp=now,
                details_json=json.dumps(details) if details else None,
            )
            session.add(history)
            deps = self._load_dependencies(session, item_id)
            return WorkItem.from_row(row, dependencies=deps)

    def update_fields(
        self,
        item_id: str,
        title: str | None = None,
        description: str | None = None,
        priority: WorkItemPriority | None = None,
        assigned_to: str | None = None,
        actor: str | None = None,
    ) -> WorkItem:
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = session.get(WorkItemRow, item_id)
            if row is None:
                raise ValueError(f"Work item not found: {item_id}")
            changes: dict[str, Any] = {}
            if title is not None and title != row.title:
                changes["title"] = {"old": row.title, "new": title}
                row.title = title
            if description is not None:
                new_desc = description if description != "" else None
                if new_desc != row.description:
                    changes["description"] = {"old": row.description, "new": new_desc}
                    row.description = new_desc
            if priority is not None and priority.value != row.priority:
                changes["priority"] = {"old": row.priority, "new": priority.value}
                row.priority = priority.value
            if assigned_to is not None:
                new_assigned = assigned_to if assigned_to != "" else None
                if new_assigned != row.assigned_to:
                    changes["assigned_to"] = {"old": row.assigned_to, "new": new_assigned}
                    row.assigned_to = new_assigned
            if not changes:
                deps = self._load_dependencies(session, item_id)
                return WorkItem.from_row(row, dependencies=deps)
            row.updated_at = now
            history = WorkItemHistoryRow(
                event_id=str(uuid4()),
                item_id=item_id,
                action="fields_updated",
                old_value=None,
                new_value=None,
                actor=actor,
                timestamp=now,
                details_json=json.dumps(changes),
            )
            session.add(history)
            deps = self._load_dependencies(session, item_id)
            return WorkItem.from_row(row, dependencies=deps)

    # -- evidence -----------------------------------------------------------

    def add_evidence(
        self,
        item_id: str,
        evidence: WorkItemEvidence,
    ) -> WorkItem:
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = session.get(WorkItemRow, item_id)
            if row is None:
                raise ValueError(f"Work item not found: {item_id}")
            existing: list[dict[str, Any]] = []
            if row.evidence_json:
                existing = json.loads(row.evidence_json)
            existing.append(evidence.to_dict())
            row.evidence_json = json.dumps(existing)
            row.updated_at = now
            history = WorkItemHistoryRow(
                event_id=str(uuid4()),
                item_id=item_id,
                action="evidence_added",
                old_value=None,
                new_value=evidence.evidence_type,
                actor=None,
                timestamp=now,
                details_json=json.dumps(evidence.to_dict()),
            )
            session.add(history)
            deps = self._load_dependencies(session, item_id)
            return WorkItem.from_row(row, dependencies=deps)

    # -- dependencies -------------------------------------------------------

    def add_dependency(
        self,
        item_id: str,
        depends_on_id: str,
        dependency_type: str = "blocks",
    ) -> WorkItemDependency:
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            item = session.get(WorkItemRow, item_id)
            if item is None:
                raise ValueError(f"Work item not found: {item_id}")
            dep_item = session.get(WorkItemRow, depends_on_id)
            if dep_item is None:
                raise ValueError(f"Dependency target not found: {depends_on_id}")
            if item_id == depends_on_id:
                raise ValueError("A work item cannot depend on itself")
            existing = (
                session.query(WorkItemDependencyRow)
                .filter(
                    WorkItemDependencyRow.item_id == item_id,
                    WorkItemDependencyRow.depends_on_id == depends_on_id,
                )
                .first()
            )
            if existing is not None:
                raise ValueError(
                    f"Dependency already exists: {item_id} -> {depends_on_id}"
                )
            dep_row = WorkItemDependencyRow(
                dependency_id=str(uuid4()),
                item_id=item_id,
                depends_on_id=depends_on_id,
                dependency_type=dependency_type,
                created_at=now,
            )
            session.add(dep_row)
        return WorkItemDependency(
            item_id=item_id,
            depends_on_id=depends_on_id,
            dependency_type=dependency_type,
            created_at=now,
        )

    def list_dependencies(self, item_id: str) -> list[WorkItemDependency]:
        with get_session(self._session_factory) as session:
            return self._load_dependencies(session, item_id)

    # -- history ------------------------------------------------------------

    def get_history(self, item_id: str) -> WorkItemHistory:
        with get_session(self._session_factory) as session:
            item = session.get(WorkItemRow, item_id)
            if item is None:
                raise ValueError(f"Work item not found: {item_id}")
            rows = (
                session.query(WorkItemHistoryRow)
                .filter(WorkItemHistoryRow.item_id == item_id)
                .order_by(WorkItemHistoryRow.timestamp.asc())
                .all()
            )
            events: list[dict[str, Any]] = []
            for row in rows:
                event: dict[str, Any] = {
                    "event_id": row.event_id,
                    "action": row.action,
                    "old_value": row.old_value,
                    "new_value": row.new_value,
                    "actor": row.actor,
                    "timestamp": row.timestamp,
                }
                if row.details_json:
                    event["details"] = json.loads(row.details_json)
                events.append(event)
            return WorkItemHistory(item_id=item_id, events=events)

    # -- helpers ------------------------------------------------------------

    def _load_dependencies(
        self,
        session: Any,
        item_id: str,
    ) -> list[WorkItemDependency]:
        rows = (
            session.query(WorkItemDependencyRow)
            .filter(WorkItemDependencyRow.item_id == item_id)
            .all()
        )
        return [
            WorkItemDependency(
                item_id=row.item_id,
                depends_on_id=row.depends_on_id,
                dependency_type=row.dependency_type,
                created_at=row.created_at,
            )
            for row in rows
        ]
