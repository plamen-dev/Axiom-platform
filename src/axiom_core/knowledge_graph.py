"""Knowledge Graph Foundation — navigable structure connecting knowledge.

Connects knowledge objects, workflows, provenance, evidence, capabilities,
failures, and decisions into a traversable graph derived from existing
registries.

Structural/navigation infrastructure only.  No semantic retrieval, no
embeddings, no autonomous reasoning, no workflow execution.

The graph is *derived* from existing registries — it is not a competing
source of truth.

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
# Graph node types
# ---------------------------------------------------------------------------


class GraphNodeType(str, Enum):
    """Classification of graph nodes."""

    KNOWLEDGE_SOURCE = "knowledge_source"
    KNOWLEDGE_OBJECT = "knowledge_object"
    WORKFLOW = "workflow"
    WORKFLOW_STEP = "workflow_step"
    RULE = "rule"
    CAPABILITY = "capability"
    EVIDENCE = "evidence"
    PROVENANCE = "provenance"
    REVIEW = "review"
    LEARNING_CANDIDATE = "learning_candidate"
    FAILURE_PATTERN = "failure_pattern"
    DECISION = "decision"


# ---------------------------------------------------------------------------
# Graph edge types — reuse knowledge_objects.RelationshipType where possible
# ---------------------------------------------------------------------------


class GraphEdgeType(str, Enum):
    """Types of edges in the knowledge graph."""

    RELATES_TO = "relates_to"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    VALIDATED_BY = "validated_by"
    SUPERSEDES = "supersedes"
    APPROVED_BY = "approved_by"
    REJECTED_BY = "rejected_by"
    SUPPORTED_BY = "supported_by"
    PRODUCED_BY = "produced_by"
    CONSUMES = "consumes"
    PRODUCES = "produces"
    FAILED_BY = "failed_by"
    CANDIDATE_FOR = "candidate_for"
    HAS_STEP = "has_step"
    HAS_RULE = "has_rule"
    REVIEWED_BY = "reviewed_by"
    SOURCED_FROM = "sourced_from"


# Mapping from knowledge_objects.RelationshipType values to GraphEdgeType
_RELATIONSHIP_TO_EDGE: dict[str, GraphEdgeType] = {
    "depends_on": GraphEdgeType.DEPENDS_ON,
    "derived_from": GraphEdgeType.DERIVED_FROM,
    "validated_by": GraphEdgeType.VALIDATED_BY,
    "supersedes": GraphEdgeType.SUPERSEDES,
    "related_to": GraphEdgeType.RELATES_TO,
    "consumes": GraphEdgeType.CONSUMES,
    "produces": GraphEdgeType.PRODUCES,
}

# Max traversal depth cap
MAX_TRAVERSAL_DEPTH = 10

# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class KnowledgeGraphNodeRow(Base):
    """Persisted graph node."""

    __tablename__ = "knowledge_graph_nodes"

    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_registry: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class KnowledgeGraphEdgeRow(Base):
    """Persisted graph edge."""

    __tablename__ = "knowledge_graph_edges"

    edge_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_node_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_registry: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class KnowledgeGraphSnapshotRow(Base):
    """Persisted graph snapshot metadata."""

    __tablename__ = "knowledge_graph_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_count: Mapped[int] = mapped_column(nullable=False)
    edge_count: Mapped[int] = mapped_column(nullable=False)
    node_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    edge_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_registries_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


def _serialize_node_type(nt: GraphNodeType | str) -> str:
    return nt.value if isinstance(nt, GraphNodeType) else nt


def _serialize_edge_type(et: GraphEdgeType | str) -> str:
    return et.value if isinstance(et, GraphEdgeType) else et


def _coerce_enum(value: str, enum_cls: type[Enum]) -> Enum | str:
    """Coerce a string to an enum member, returning the raw string on failure."""
    try:
        return enum_cls(value)
    except ValueError:
        return value


class KnowledgeGraphNode:
    """A node in the knowledge graph."""

    def __init__(
        self,
        node_id: str,
        node_type: GraphNodeType | str,
        source_registry: str,
        label: str,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.node_type = node_type
        self.source_registry = source_registry
        self.label = label
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": _serialize_node_type(self.node_type),
            "source_registry": self.source_registry,
            "label": self.label,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class KnowledgeGraphEdge:
    """An edge in the knowledge graph."""

    def __init__(
        self,
        edge_id: str | None = None,
        source_node_id: str = "",
        target_node_id: str = "",
        edge_type: GraphEdgeType | str = GraphEdgeType.RELATES_TO,
        source_registry: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.edge_id = edge_id or str(uuid4())
        self.source_node_id = source_node_id
        self.target_node_id = target_node_id
        self.edge_type = edge_type
        self.source_registry = source_registry
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": _serialize_edge_type(self.edge_type),
            "source_registry": self.source_registry,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class KnowledgeGraphSnapshot:
    """Immutable snapshot of the graph state at a point in time."""

    def __init__(
        self,
        snapshot_id: str | None = None,
        node_count: int = 0,
        edge_count: int = 0,
        node_types: list[str] | None = None,
        edge_types: list[str] | None = None,
        source_registries: list[str] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.snapshot_id = snapshot_id or str(uuid4())
        self.node_count = node_count
        self.edge_count = edge_count
        self.node_types = node_types if node_types is not None else []
        self.edge_types = edge_types if edge_types is not None else []
        self.source_registries = source_registries if source_registries is not None else []
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "node_types": self.node_types,
            "edge_types": self.edge_types,
            "source_registries": self.source_registries,
            "created_at": self.created_at,
        }


class KnowledgeGraphTraversalResult:
    """Result of a bounded graph traversal."""

    def __init__(
        self,
        start_node_id: str,
        depth: int,
        visited_nodes: list[KnowledgeGraphNode] | None = None,
        visited_edges: list[KnowledgeGraphEdge] | None = None,
        cycle_detected: bool = False,
    ) -> None:
        self.start_node_id = start_node_id
        self.depth = depth
        self.visited_nodes = visited_nodes if visited_nodes is not None else []
        self.visited_edges = visited_edges if visited_edges is not None else []
        self.cycle_detected = cycle_detected

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_node_id": self.start_node_id,
            "depth": self.depth,
            "visited_node_count": len(self.visited_nodes),
            "visited_edge_count": len(self.visited_edges),
            "visited_nodes": [n.to_dict() for n in self.visited_nodes],
            "visited_edges": [e.to_dict() for e in self.visited_edges],
            "cycle_detected": self.cycle_detected,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards and the escape char in user-supplied filter strings."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _deterministic_edge_id(source_id: str, target_id: str, edge_type: str) -> str:
    """Generate a stable edge ID from its endpoints and type."""
    return f"{source_id}--{edge_type}-->{target_id}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class KnowledgeGraph:
    """Governed knowledge graph derived from existing registries.

    Backed by SQLite via SQLAlchemy.  Supports build, persist, query,
    and bounded traversal with cycle safety and deterministic ordering.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    # --- Build from registries ---

    def build_from_registries(
        self,
        db_path: str | None = None,
    ) -> KnowledgeGraphSnapshot:
        """Build/rebuild the graph from existing knowledge registries.

        Clears current graph state and rebuilds from scratch for determinism.
        Each registry is consumed if available; missing registries are skipped.
        Returns a snapshot of the rebuilt graph.
        """
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []
        now = datetime.now(timezone.utc).isoformat()
        source_registries_used: set[str] = set()

        # --- Knowledge Objects + Relationships ---
        try:
            from axiom_core.knowledge_objects import KnowledgeObjectRegistry

            obj_reg = KnowledgeObjectRegistry(db_path)
            for obj in obj_reg.list_objects():
                nodes.append(KnowledgeGraphNode(
                    node_id=obj.object_id,
                    node_type=GraphNodeType.KNOWLEDGE_OBJECT,
                    source_registry="knowledge_objects",
                    label=obj.object_name,
                    metadata={"object_type": obj.object_type.value if isinstance(obj.object_type, Enum) else str(obj.object_type), "description": obj.description},
                    created_at=obj.created_at,
                ))
                if obj.source_id:
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(obj.object_id, obj.source_id, "sourced_from"),
                        source_node_id=obj.object_id,
                        target_node_id=obj.source_id,
                        edge_type=GraphEdgeType.SOURCED_FROM,
                        source_registry="knowledge_objects",
                        created_at=obj.created_at,
                    ))
            for rel in obj_reg.list_relationships():
                rel_type_str = rel.relationship_type.value if isinstance(rel.relationship_type, Enum) else str(rel.relationship_type)
                edge_type = _RELATIONSHIP_TO_EDGE.get(rel_type_str, GraphEdgeType.RELATES_TO)
                edges.append(KnowledgeGraphEdge(
                    edge_id=rel.relationship_id,
                    source_node_id=rel.source_object_id,
                    target_node_id=rel.target_object_id,
                    edge_type=edge_type,
                    source_registry="knowledge_objects",
                    metadata={"notes": rel.notes} if rel.notes else {},
                    created_at=rel.created_at,
                ))
            source_registries_used.add("knowledge_objects")
        except Exception:
            pass

        # --- Knowledge Sources ---
        try:
            from axiom_core.knowledge_registry import KnowledgeSourceRegistry

            src_reg = KnowledgeSourceRegistry(db_path)
            for src in src_reg.list_sources(include_disabled=True):
                nodes.append(KnowledgeGraphNode(
                    node_id=src.source_id,
                    node_type=GraphNodeType.KNOWLEDGE_SOURCE,
                    source_registry="knowledge_sources",
                    label=src.source_name,
                    metadata={"source_type": src.source_type.value if isinstance(src.source_type, Enum) else str(src.source_type), "enabled": src.enabled},
                    created_at=src.created_at,
                ))
            source_registries_used.add("knowledge_sources")
        except Exception:
            pass

        # --- Knowledge Provenance ---
        try:
            from axiom_core.knowledge_provenance import KnowledgeProvenanceRegistry

            prov_reg = KnowledgeProvenanceRegistry(db_path)
            for prov in prov_reg.list_provenance(include_deprecated=True):
                node_id = f"prov:{prov.provenance_id}"
                nodes.append(KnowledgeGraphNode(
                    node_id=node_id,
                    node_type=GraphNodeType.PROVENANCE,
                    source_registry="knowledge_provenance",
                    label=prov.knowledge_name,
                    metadata={
                        "trust_level": prov.trust_level.value if isinstance(prov.trust_level, Enum) else str(prov.trust_level),
                        "confidence_score": prov.confidence_score,
                        "origin": prov.origin,
                    },
                    created_at=prov.created_at,
                ))
                # Provenance uses knowledge_name not knowledge_id;
                # linking to object nodes by name is a future enhancement.
                if prov.superseded_by:
                    sup_node_id = f"prov:{prov.superseded_by}"
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(sup_node_id, node_id, "supersedes"),
                        source_node_id=sup_node_id,
                        target_node_id=node_id,
                        edge_type=GraphEdgeType.SUPERSEDES,
                        source_registry="knowledge_provenance",
                        created_at=prov.created_at,
                    ))
            source_registries_used.add("knowledge_provenance")
        except Exception:
            pass

        # --- Workflow Definitions ---
        try:
            from axiom_core.workflow_registry import WorkflowKnowledgeRegistry

            wf_reg = WorkflowKnowledgeRegistry(db_path)
            for wf in wf_reg.list_workflows(include_deprecated=True):
                nodes.append(KnowledgeGraphNode(
                    node_id=wf.workflow_id,
                    node_type=GraphNodeType.WORKFLOW,
                    source_registry="workflows",
                    label=wf.workflow_name,
                    metadata={"description": wf.description, "version": wf.version},
                    created_at=wf.created_at,
                ))
                for step in wf.steps:
                    step_node_id = f"step:{wf.workflow_id}:{step.step_id}"
                    nodes.append(KnowledgeGraphNode(
                        node_id=step_node_id,
                        node_type=GraphNodeType.WORKFLOW_STEP,
                        source_registry="workflows",
                        label=step.step_name,
                        metadata={"step_order": step.step_order, "description": step.description},
                        created_at=wf.created_at,
                    ))
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(wf.workflow_id, step_node_id, "has_step"),
                        source_node_id=wf.workflow_id,
                        target_node_id=step_node_id,
                        edge_type=GraphEdgeType.HAS_STEP,
                        source_registry="workflows",
                        created_at=wf.created_at,
                    ))
                for rule in wf.rules:
                    rule_node_id = f"rule:{wf.workflow_id}:{rule.rule_id}"
                    nodes.append(KnowledgeGraphNode(
                        node_id=rule_node_id,
                        node_type=GraphNodeType.RULE,
                        source_registry="workflows",
                        label=rule.rule_name,
                        metadata={"condition": rule.condition, "action": rule.action, "priority": rule.priority},
                        created_at=wf.created_at,
                    ))
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(wf.workflow_id, rule_node_id, "has_rule"),
                        source_node_id=wf.workflow_id,
                        target_node_id=rule_node_id,
                        edge_type=GraphEdgeType.HAS_RULE,
                        source_registry="workflows",
                        created_at=wf.created_at,
                    ))
            source_registries_used.add("workflows")
        except Exception:
            pass

        # --- Learning Candidates ---
        try:
            from axiom_core.learning_candidates import LearningCandidateRegistry

            lc_reg = LearningCandidateRegistry(db_path)
            for cand in lc_reg.list_candidates(include_dismissed=True):
                node_id = f"candidate:{cand.candidate_id}"
                nodes.append(KnowledgeGraphNode(
                    node_id=node_id,
                    node_type=GraphNodeType.LEARNING_CANDIDATE,
                    source_registry="learning_candidates",
                    label=cand.candidate_name,
                    metadata={
                        "candidate_type": cand.candidate_type.value if isinstance(cand.candidate_type, Enum) else str(cand.candidate_type),
                        "strength": cand.strength.value if isinstance(cand.strength, Enum) else str(cand.strength),
                        "confidence_score": cand.confidence_score,
                    },
                    created_at=cand.created_at,
                ))
                # Learning candidates do not have a knowledge_id;
                # edges to knowledge items would require name-based
                # matching which is a future enhancement.
            source_registries_used.add("learning_candidates")
        except Exception:
            pass

        # --- Knowledge Reviews ---
        try:
            from axiom_core.knowledge_reviews import KnowledgeReviewRegistry

            rev_reg = KnowledgeReviewRegistry(db_path)
            for rev in rev_reg.list_reviews():
                node_id = f"review:{rev.review_id}"
                decision_str = rev.decision.value if isinstance(rev.decision, Enum) else str(rev.decision)
                nodes.append(KnowledgeGraphNode(
                    node_id=node_id,
                    node_type=GraphNodeType.REVIEW,
                    source_registry="knowledge_reviews",
                    label=f"Review: {rev.knowledge_name}",
                    metadata={
                        "decision": decision_str,
                        "reason": rev.reason.value if isinstance(rev.reason, Enum) else str(rev.reason),
                        "status": rev.status.value if isinstance(rev.status, Enum) else str(rev.status),
                        "reviewer": rev.reviewer,
                    },
                    created_at=rev.created_at,
                ))
                if rev.knowledge_id:
                    edge_type = GraphEdgeType.APPROVED_BY if decision_str == "approved" else (
                        GraphEdgeType.REJECTED_BY if decision_str == "rejected" else GraphEdgeType.REVIEWED_BY
                    )
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(rev.knowledge_id, node_id, _serialize_edge_type(edge_type)),
                        source_node_id=rev.knowledge_id,
                        target_node_id=node_id,
                        edge_type=edge_type,
                        source_registry="knowledge_reviews",
                        created_at=rev.created_at,
                    ))
                if rev.superseded_by:
                    sup_node_id = f"review:{rev.superseded_by}"
                    edges.append(KnowledgeGraphEdge(
                        edge_id=_deterministic_edge_id(sup_node_id, node_id, "supersedes"),
                        source_node_id=sup_node_id,
                        target_node_id=node_id,
                        edge_type=GraphEdgeType.SUPERSEDES,
                        source_registry="knowledge_reviews",
                        created_at=rev.created_at,
                    ))
            source_registries_used.add("knowledge_reviews")
        except Exception:
            pass

        # --- Persist: clear old graph, write new ---
        snapshot = self._persist_graph(nodes, edges, sorted(source_registries_used), now)
        return snapshot

    def _persist_graph(
        self,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        source_registries: list[str],
        now: str,
    ) -> KnowledgeGraphSnapshot:
        """Clear existing graph data and persist new nodes/edges/snapshot."""
        node_type_set: set[str] = set()
        edge_type_set: set[str] = set()

        with get_session(self._session_factory) as session:
            session.query(KnowledgeGraphEdgeRow).delete()
            session.query(KnowledgeGraphNodeRow).delete()

            for n in nodes:
                nt = _serialize_node_type(n.node_type)
                node_type_set.add(nt)
                session.add(KnowledgeGraphNodeRow(
                    node_id=n.node_id,
                    node_type=nt,
                    source_registry=n.source_registry,
                    label=n.label,
                    metadata_json=json.dumps(n.metadata, default=str) if n.metadata is not None else None,
                    created_at=n.created_at,
                ))

            seen_edge_ids: set[str] = set()
            for e in edges:
                if e.edge_id in seen_edge_ids:
                    continue
                seen_edge_ids.add(e.edge_id)
                et = _serialize_edge_type(e.edge_type)
                edge_type_set.add(et)
                session.add(KnowledgeGraphEdgeRow(
                    edge_id=e.edge_id,
                    source_node_id=e.source_node_id,
                    target_node_id=e.target_node_id,
                    edge_type=et,
                    source_registry=e.source_registry,
                    metadata_json=json.dumps(e.metadata, default=str) if e.metadata is not None else None,
                    created_at=e.created_at,
                ))

            snapshot_id = str(uuid4())
            snapshot_row = KnowledgeGraphSnapshotRow(
                snapshot_id=snapshot_id,
                node_count=len(nodes),
                edge_count=len(seen_edge_ids),
                node_types_json=json.dumps(sorted(node_type_set)),
                edge_types_json=json.dumps(sorted(edge_type_set)),
                source_registries_json=json.dumps(source_registries),
                created_at=now,
            )
            session.add(snapshot_row)

        return KnowledgeGraphSnapshot(
            snapshot_id=snapshot_id,
            node_count=len(nodes),
            edge_count=len(seen_edge_ids),
            node_types=sorted(node_type_set),
            edge_types=sorted(edge_type_set),
            source_registries=source_registries,
            created_at=now,
        )

    # --- Query operations ---

    def get_node(self, node_id: str) -> KnowledgeGraphNode | None:
        """Get a single node by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(KnowledgeGraphNodeRow, node_id)
            if row is None:
                return None
            return self._row_to_node(row)

    def list_nodes(
        self,
        node_type: GraphNodeType | None = None,
        label_filter: str | None = None,
    ) -> list[KnowledgeGraphNode]:
        """List nodes, optionally filtered by type or label."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeGraphNodeRow)
            if node_type is not None:
                query = query.filter(
                    KnowledgeGraphNodeRow.node_type == _serialize_node_type(node_type)
                )
            if label_filter is not None:
                escaped = _escape_like(label_filter)
                query = query.filter(
                    KnowledgeGraphNodeRow.label.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(
                KnowledgeGraphNodeRow.node_type,
                KnowledgeGraphNodeRow.label,
            ).all()
            return [self._row_to_node(r) for r in rows]

    def node_count(self) -> int:
        """Return total number of nodes."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeGraphNodeRow).count()

    def list_edges(
        self,
        node_id: str | None = None,
        edge_type: GraphEdgeType | None = None,
    ) -> list[KnowledgeGraphEdge]:
        """List edges, optionally filtered by node or type."""
        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeGraphEdgeRow)
            if node_id is not None:
                query = query.filter(
                    (KnowledgeGraphEdgeRow.source_node_id == node_id)
                    | (KnowledgeGraphEdgeRow.target_node_id == node_id)
                )
            if edge_type is not None:
                query = query.filter(
                    KnowledgeGraphEdgeRow.edge_type == _serialize_edge_type(edge_type)
                )
            rows = query.order_by(
                KnowledgeGraphEdgeRow.edge_type,
                KnowledgeGraphEdgeRow.source_node_id,
                KnowledgeGraphEdgeRow.target_node_id,
            ).all()
            return [self._row_to_edge(r) for r in rows]

    def edge_count(self) -> int:
        """Return total number of edges."""
        with get_session(self._session_factory) as session:
            return session.query(KnowledgeGraphEdgeRow).count()

    def get_neighbors(self, node_id: str) -> list[KnowledgeGraphNode]:
        """Return nodes directly connected to the given node."""
        with get_session(self._session_factory) as session:
            edge_rows = (
                session.query(KnowledgeGraphEdgeRow)
                .filter(
                    (KnowledgeGraphEdgeRow.source_node_id == node_id)
                    | (KnowledgeGraphEdgeRow.target_node_id == node_id)
                )
                .all()
            )
            neighbor_ids: set[str] = set()
            for e in edge_rows:
                if e.source_node_id != node_id:
                    neighbor_ids.add(e.source_node_id)
                if e.target_node_id != node_id:
                    neighbor_ids.add(e.target_node_id)

            if not neighbor_ids:
                return []

            rows = (
                session.query(KnowledgeGraphNodeRow)
                .filter(KnowledgeGraphNodeRow.node_id.in_(sorted(neighbor_ids)))
                .order_by(KnowledgeGraphNodeRow.node_type, KnowledgeGraphNodeRow.label)
                .all()
            )
            return [self._row_to_node(r) for r in rows]

    # --- Traversal ---

    def traverse(
        self,
        start_node_id: str,
        max_depth: int = 2,
    ) -> KnowledgeGraphTraversalResult:
        """Bounded BFS traversal from a starting node.

        max_depth is capped at MAX_TRAVERSAL_DEPTH (10).
        Cycles are detected and do not cause infinite loops.
        Returns deterministically ordered results.
        """
        effective_depth = min(max(max_depth, 0), MAX_TRAVERSAL_DEPTH)

        with get_session(self._session_factory) as session:
            start_row = session.get(KnowledgeGraphNodeRow, start_node_id)
            if start_row is None:
                return KnowledgeGraphTraversalResult(
                    start_node_id=start_node_id,
                    depth=effective_depth,
                )

            visited_ids: set[str] = set()
            visited_nodes: list[KnowledgeGraphNode] = []
            visited_edges: list[KnowledgeGraphEdge] = []
            cycle_detected = False

            # BFS
            current_frontier: list[str] = [start_node_id]
            for _depth_level in range(effective_depth + 1):
                next_frontier: list[str] = []
                for nid in sorted(current_frontier):
                    if nid in visited_ids:
                        cycle_detected = True
                        continue
                    visited_ids.add(nid)
                    row = session.get(KnowledgeGraphNodeRow, nid)
                    if row is None:
                        continue
                    visited_nodes.append(self._row_to_node(row))

                    if _depth_level < effective_depth:
                        edge_rows = (
                            session.query(KnowledgeGraphEdgeRow)
                            .filter(
                                (KnowledgeGraphEdgeRow.source_node_id == nid)
                                | (KnowledgeGraphEdgeRow.target_node_id == nid)
                            )
                            .order_by(
                                KnowledgeGraphEdgeRow.edge_type,
                                KnowledgeGraphEdgeRow.source_node_id,
                                KnowledgeGraphEdgeRow.target_node_id,
                            )
                            .all()
                        )
                        seen_edge_ids: set[str] = {e.edge_id for e in visited_edges}
                        for er in edge_rows:
                            if er.edge_id not in seen_edge_ids:
                                visited_edges.append(self._row_to_edge(er))
                                seen_edge_ids.add(er.edge_id)
                            neighbor_id = er.target_node_id if er.source_node_id == nid else er.source_node_id
                            if neighbor_id not in visited_ids:
                                next_frontier.append(neighbor_id)

                current_frontier = next_frontier
                if not current_frontier:
                    break

        return KnowledgeGraphTraversalResult(
            start_node_id=start_node_id,
            depth=effective_depth,
            visited_nodes=visited_nodes,
            visited_edges=visited_edges,
            cycle_detected=cycle_detected,
        )

    # --- Snapshot ---

    def get_latest_snapshot(self) -> KnowledgeGraphSnapshot | None:
        """Return the most recent snapshot, or None."""
        with get_session(self._session_factory) as session:
            row = (
                session.query(KnowledgeGraphSnapshotRow)
                .order_by(KnowledgeGraphSnapshotRow.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return KnowledgeGraphSnapshot(
                snapshot_id=row.snapshot_id,
                node_count=row.node_count,
                edge_count=row.edge_count,
                node_types=json.loads(row.node_types_json),
                edge_types=json.loads(row.edge_types_json),
                source_registries=json.loads(row.source_registries_json),
                created_at=row.created_at,
            )

    # --- JSON ---

    def to_json(self) -> str:
        """Return the full graph as JSON."""
        nodes = self.list_nodes()
        edges = self.list_edges()
        snapshot = self.get_latest_snapshot()
        return json.dumps({
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
            "snapshot": snapshot.to_dict() if snapshot else None,
        }, indent=2, default=str)

    # --- Internal ---

    @staticmethod
    def _row_to_node(row: KnowledgeGraphNodeRow) -> KnowledgeGraphNode:
        metadata = json.loads(row.metadata_json) if row.metadata_json is not None else {}
        return KnowledgeGraphNode(
            node_id=row.node_id,
            node_type=_coerce_enum(row.node_type, GraphNodeType),
            source_registry=row.source_registry,
            label=row.label,
            metadata=metadata,
            created_at=row.created_at,
        )

    @staticmethod
    def _row_to_edge(row: KnowledgeGraphEdgeRow) -> KnowledgeGraphEdge:
        metadata = json.loads(row.metadata_json) if row.metadata_json is not None else {}
        return KnowledgeGraphEdge(
            edge_id=row.edge_id,
            source_node_id=row.source_node_id,
            target_node_id=row.target_node_id,
            edge_type=_coerce_enum(row.edge_type, GraphEdgeType),
            source_registry=row.source_registry,
            metadata=metadata,
            created_at=row.created_at,
        )
