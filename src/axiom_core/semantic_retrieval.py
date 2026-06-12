"""Semantic Retrieval Engine — knowledge retrieval with explanations.

Retrieves knowledge from existing registries and the knowledge graph,
ranks results deterministically, and provides explanations for every
match.

Retrieval infrastructure only.  No autonomous reasoning, no planning,
no execution, no learning.  The graph and registries remain the source
of truth.

No embeddings.  No vector database.  No LLM scoring.
No probabilistic ranking.

Persistence via SQLAlchemy/SQLite (reuses the Axiom database layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.knowledge_graph import (
    GraphEdgeType,
    GraphNodeType,
    KnowledgeGraph,
    KnowledgeGraphEdgeRow,
    KnowledgeGraphNodeRow,
    _escape_like,
    _serialize_edge_type,
    _serialize_node_type,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RESULTS_DEFAULT = 20
MAX_RESULTS_CAP = 100

# Scoring weights
_SCORE_EXACT_MATCH = 100.0
_SCORE_PARTIAL_MATCH = 50.0
_SCORE_RELATIONSHIP_MATCH = 30.0
_SCORE_METADATA_MATCH = 20.0

# Trust level bonus (higher trust → higher bonus)
_TRUST_BONUS: dict[str, float] = {
    "founder_verified": 25.0,
    "human_verified": 20.0,
    "evidence_supported": 15.0,
    "derived": 10.0,
    "candidate": 5.0,
    "deprecated": 0.0,
}

# Approval status bonus
_APPROVAL_BONUS: dict[str, float] = {
    "approved": 15.0,
    "proposed": 5.0,
    "rejected": 0.0,
    "deprecated": 0.0,
    "superseded": 0.0,
    "needs_more_evidence": 2.0,
}

# Trust ordering for tiebreaker (lower index = higher trust)
_TRUST_ORDER: list[str] = [
    "founder_verified",
    "human_verified",
    "evidence_supported",
    "derived",
    "candidate",
    "deprecated",
]

# Approval ordering for tiebreaker (lower index = better)
_APPROVAL_ORDER: list[str] = [
    "approved",
    "proposed",
    "needs_more_evidence",
    "rejected",
    "deprecated",
    "superseded",
]

# Node type → user-facing query type mapping
_QUERY_TYPE_TO_NODE_TYPE: dict[str, GraphNodeType] = {
    "knowledge_object": GraphNodeType.KNOWLEDGE_OBJECT,
    "object": GraphNodeType.KNOWLEDGE_OBJECT,
    "workflow": GraphNodeType.WORKFLOW,
    "workflow_step": GraphNodeType.WORKFLOW_STEP,
    "step": GraphNodeType.WORKFLOW_STEP,
    "rule": GraphNodeType.RULE,
    "capability": GraphNodeType.CAPABILITY,
    "evidence": GraphNodeType.EVIDENCE,
    "provenance": GraphNodeType.PROVENANCE,
    "review": GraphNodeType.REVIEW,
    "learning_candidate": GraphNodeType.LEARNING_CANDIDATE,
    "candidate": GraphNodeType.LEARNING_CANDIDATE,
    "failure_pattern": GraphNodeType.FAILURE_PATTERN,
    "failure": GraphNodeType.FAILURE_PATTERN,
    "decision": GraphNodeType.DECISION,
    "source": GraphNodeType.KNOWLEDGE_SOURCE,
    "knowledge_source": GraphNodeType.KNOWLEDGE_SOURCE,
}

VALID_QUERY_TYPES: frozenset[str] = frozenset(_QUERY_TYPE_TO_NODE_TYPE.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _trust_rank(level: str) -> int:
    """Numeric rank for trust level (lower = more trusted)."""
    try:
        return _TRUST_ORDER.index(level)
    except ValueError:
        return len(_TRUST_ORDER)


def _approval_rank(status: str) -> int:
    """Numeric rank for approval status (lower = better)."""
    try:
        return _APPROVAL_ORDER.index(status)
    except ValueError:
        return len(_APPROVAL_ORDER)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RetrievalExplanation:
    """Explains why a match was returned."""

    def __init__(self, reason: str, details: str | None = None) -> None:
        self.reason = reason
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"reason": self.reason}
        if self.details is not None:
            d["details"] = self.details
        return d


class RetrievalEvidence:
    """Evidence supporting a retrieval match."""

    def __init__(
        self,
        evidence_type: str = "",
        path: str | None = None,
        provenance_id: str | None = None,
        trust_level: str | None = None,
        confidence_score: float | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.path = path
        self.provenance_id = provenance_id
        self.trust_level = trust_level
        self.confidence_score = confidence_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "path": self.path,
            "provenance_id": self.provenance_id,
            "trust_level": self.trust_level,
            "confidence_score": self.confidence_score,
        }


class RetrievalMatch:
    """A single retrieval result with score, evidence, and explanation."""

    def __init__(
        self,
        object_id: str,
        object_name: str,
        object_type: str,
        score: float = 0.0,
        source_registry: str = "",
        trust_level: str | None = None,
        approval_status: str | None = None,
        evidence: list[RetrievalEvidence] | None = None,
        provenance_references: list[str] | None = None,
        explanation: RetrievalExplanation | None = None,
    ) -> None:
        self.object_id = object_id
        self.object_name = object_name
        self.object_type = object_type
        self.score = score
        self.source_registry = source_registry
        self.trust_level = trust_level
        self.approval_status = approval_status
        self.evidence = evidence if evidence is not None else []
        self.provenance_references = provenance_references if provenance_references is not None else []
        self.explanation = explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_name": self.object_name,
            "object_type": self.object_type,
            "score": self.score,
            "source_registry": self.source_registry,
            "trust_level": self.trust_level,
            "approval_status": self.approval_status,
            "evidence": [e.to_dict() for e in self.evidence],
            "provenance_references": self.provenance_references,
            "explanation": self.explanation.to_dict() if self.explanation is not None else None,
        }


class RetrievalQuery:
    """Encapsulates a retrieval request."""

    def __init__(
        self,
        query_text: str,
        query_type: str | None = None,
        max_results: int = MAX_RESULTS_DEFAULT,
    ) -> None:
        self.query_text = query_text
        self.query_type = query_type
        self.max_results = min(max(max_results, 1), MAX_RESULTS_CAP)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query_text,
            "query_type": self.query_type,
            "max_results": self.max_results,
        }


class RetrievalResult:
    """Container for retrieval results."""

    def __init__(
        self,
        query: RetrievalQuery,
        matches: list[RetrievalMatch] | None = None,
        total_candidates: int = 0,
        created_at: str | None = None,
    ) -> None:
        self.query = query
        self.matches = matches if matches is not None else []
        self.total_candidates = total_candidates
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "matches": [m.to_dict() for m in self.matches],
            "total_candidates": self.total_candidates,
            "result_count": len(self.matches),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Semantic Retrieval Engine
# ---------------------------------------------------------------------------


class SemanticRetrievalEngine:
    """Governed retrieval engine for the Axiom knowledge system.

    Searches the knowledge graph (and by extension the registries that
    feed it) for nodes matching a query.  Supports exact, partial,
    type-filtered, and relationship-aware retrieval.

    Read-only — never mutates knowledge.
    Deterministic — results are ranked by score DESC, trust level,
    approval status, then name ASC.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)
        self._graph = KnowledgeGraph(db_path)

    # --- Public API ---

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Execute a retrieval query.

        Raises ValueError for empty queries.
        """
        text = query.query_text.strip()
        if not text:
            raise ValueError("Query text must not be empty.")

        # Resolve node type filter
        node_type_filter: GraphNodeType | None = None
        if query.query_type is not None:
            node_type_filter = _QUERY_TYPE_TO_NODE_TYPE.get(
                query.query_type.lower()
            )
            # Unknown type → empty results, not an error
            if node_type_filter is None:
                return RetrievalResult(
                    query=query,
                    matches=[],
                    total_candidates=0,
                )

        # Collect candidate matches
        candidates: list[RetrievalMatch] = []

        # Phase 1: Direct node matches (exact + partial)
        self._search_nodes(text, node_type_filter, candidates)

        # Phase 2: Relationship-aware matches
        self._search_relationships(text, node_type_filter, candidates)

        # Deduplicate by object_id (keep highest score)
        deduped = self._deduplicate(candidates)

        # Enrich with provenance and review data
        self._enrich_trust_and_approval(deduped)

        # Apply trust and approval bonuses to scores
        for m in deduped:
            if m.trust_level:
                m.score += _TRUST_BONUS.get(m.trust_level, 0.0)
            if m.approval_status:
                m.score += _APPROVAL_BONUS.get(m.approval_status, 0.0)

        # Sort deterministically
        sorted_matches = self._sort_matches(deduped)

        total = len(sorted_matches)
        capped = sorted_matches[: query.max_results]

        return RetrievalResult(
            query=query,
            matches=capped,
            total_candidates=total,
        )

    def to_json(self, result: RetrievalResult) -> str:
        """Serialize a result to JSON."""
        return json.dumps(result.to_dict(), indent=2, default=str)

    # --- Search phases ---

    def _search_nodes(
        self,
        text: str,
        node_type_filter: GraphNodeType | None,
        out: list[RetrievalMatch],
    ) -> None:
        """Search graph nodes for exact and partial label matches."""
        text_lower = text.lower()
        escaped = _escape_like(text)

        with get_session(self._session_factory) as session:
            query = session.query(KnowledgeGraphNodeRow)
            if node_type_filter is not None:
                query = query.filter(
                    KnowledgeGraphNodeRow.node_type
                    == _serialize_node_type(node_type_filter)
                )
            # LIKE search for partial match
            query = query.filter(
                KnowledgeGraphNodeRow.label.ilike(f"%{escaped}%", escape="\\")
            )
            rows = query.order_by(
                KnowledgeGraphNodeRow.node_type,
                KnowledgeGraphNodeRow.label,
            ).all()

            for row in rows:
                label_lower = row.label.lower()
                if label_lower == text_lower:
                    score = _SCORE_EXACT_MATCH
                    reason = "Exact object name match."
                elif text_lower in label_lower:
                    score = _SCORE_PARTIAL_MATCH
                    reason = f"Partial match: label contains '{text}'."
                else:
                    score = _SCORE_PARTIAL_MATCH
                    reason = f"Partial match: label contains '{text}'."

                out.append(RetrievalMatch(
                    object_id=row.node_id,
                    object_name=row.label,
                    object_type=row.node_type,
                    score=score,
                    source_registry=row.source_registry,
                    explanation=RetrievalExplanation(reason=reason),
                ))

    def _search_relationships(
        self,
        text: str,
        node_type_filter: GraphNodeType | None,
        out: list[RetrievalMatch],
    ) -> None:
        """Find nodes connected to matching nodes via graph edges."""
        escaped = _escape_like(text)

        # Already-matched IDs (from node search)
        existing_ids = {m.object_id for m in out}

        with get_session(self._session_factory) as session:
            # Find anchor nodes matching the query text
            anchor_query = session.query(KnowledgeGraphNodeRow).filter(
                KnowledgeGraphNodeRow.label.ilike(f"%{escaped}%", escape="\\")
            )
            anchor_rows = anchor_query.all()
            anchor_ids = {r.node_id for r in anchor_rows}
            anchor_labels = {r.node_id: r.label for r in anchor_rows}

            if not anchor_ids:
                return

            # Find edges where an anchor is source or target
            edge_rows = (
                session.query(KnowledgeGraphEdgeRow)
                .filter(
                    (KnowledgeGraphEdgeRow.source_node_id.in_(anchor_ids))
                    | (KnowledgeGraphEdgeRow.target_node_id.in_(anchor_ids))
                )
                .all()
            )

            # Collect related node IDs (not already matched)
            related_ids: set[str] = set()
            # Map related_id → (anchor_label, edge_type)
            relation_info: dict[str, list[tuple[str, str]]] = {}
            for e in edge_rows:
                if e.source_node_id in anchor_ids:
                    related_id = e.target_node_id
                    anchor_lbl = anchor_labels.get(e.source_node_id, "")
                else:
                    related_id = e.source_node_id
                    anchor_lbl = anchor_labels.get(e.target_node_id, "")

                if related_id in existing_ids or related_id in anchor_ids:
                    continue
                related_ids.add(related_id)
                relation_info.setdefault(related_id, []).append(
                    (anchor_lbl, e.edge_type)
                )

            if not related_ids:
                return

            # Fetch related nodes
            related_rows = (
                session.query(KnowledgeGraphNodeRow)
                .filter(KnowledgeGraphNodeRow.node_id.in_(related_ids))
            )
            if node_type_filter is not None:
                related_rows = related_rows.filter(
                    KnowledgeGraphNodeRow.node_type
                    == _serialize_node_type(node_type_filter)
                )
            related_rows = related_rows.all()

            for row in related_rows:
                infos = relation_info.get(row.node_id, [])
                if not infos:
                    continue
                anchor_lbl, edge_type = infos[0]
                reason = (
                    f"Relationship derived from Knowledge Graph: "
                    f"connected to '{anchor_lbl}' via {edge_type}."
                )
                out.append(RetrievalMatch(
                    object_id=row.node_id,
                    object_name=row.label,
                    object_type=row.node_type,
                    score=_SCORE_RELATIONSHIP_MATCH,
                    source_registry=row.source_registry,
                    explanation=RetrievalExplanation(reason=reason),
                ))

    # --- Enrichment ---

    def _enrich_trust_and_approval(
        self,
        matches: list[RetrievalMatch],
    ) -> None:
        """Add trust level and approval status from provenance/reviews."""
        # Build lookup: node_id → match
        match_map = {m.object_id: m for m in matches}
        node_ids = set(match_map.keys())

        if not node_ids:
            return

        with get_session(self._session_factory) as session:
            # Look for provenance edges pointing to our nodes
            prov_edges = (
                session.query(KnowledgeGraphEdgeRow)
                .filter(
                    KnowledgeGraphEdgeRow.edge_type == _serialize_edge_type(GraphEdgeType.SUPPORTED_BY),
                    KnowledgeGraphEdgeRow.source_node_id.in_(node_ids),
                )
                .all()
            )
            prov_node_ids = {e.target_node_id for e in prov_edges}

            # Also check if matched nodes themselves are provenance nodes
            prov_rows = (
                session.query(KnowledgeGraphNodeRow)
                .filter(
                    KnowledgeGraphNodeRow.node_type == "provenance",
                    KnowledgeGraphNodeRow.node_id.in_(node_ids | prov_node_ids),
                )
                .all()
            )
            for pr in prov_rows:
                if pr.node_id in match_map:
                    meta = json.loads(pr.metadata_json) if pr.metadata_json else {}
                    trust = meta.get("trust_level")
                    if trust:
                        match_map[pr.node_id].trust_level = trust

            # Look for review edges pointing to our nodes
            review_edges = (
                session.query(KnowledgeGraphEdgeRow)
                .filter(
                    KnowledgeGraphEdgeRow.edge_type.in_([
                        _serialize_edge_type(GraphEdgeType.APPROVED_BY),
                        _serialize_edge_type(GraphEdgeType.REJECTED_BY),
                        _serialize_edge_type(GraphEdgeType.REVIEWED_BY),
                    ]),
                    KnowledgeGraphEdgeRow.source_node_id.in_(node_ids),
                )
                .all()
            )
            for edge in review_edges:
                if edge.source_node_id in match_map:
                    et = edge.edge_type
                    if et == _serialize_edge_type(GraphEdgeType.APPROVED_BY):
                        match_map[edge.source_node_id].approval_status = "approved"
                    elif et == _serialize_edge_type(GraphEdgeType.REJECTED_BY):
                        match_map[edge.source_node_id].approval_status = "rejected"
                    elif et == _serialize_edge_type(GraphEdgeType.REVIEWED_BY):
                        if match_map[edge.source_node_id].approval_status is None:
                            match_map[edge.source_node_id].approval_status = "proposed"

            # Also check review nodes themselves for decision metadata
            review_rows = (
                session.query(KnowledgeGraphNodeRow)
                .filter(
                    KnowledgeGraphNodeRow.node_type == "review",
                    KnowledgeGraphNodeRow.node_id.in_(node_ids),
                )
                .all()
            )
            for rr in review_rows:
                if rr.node_id in match_map:
                    meta = json.loads(rr.metadata_json) if rr.metadata_json else {}
                    decision = meta.get("decision")
                    if decision:
                        match_map[rr.node_id].approval_status = decision

            # Enrich provenance metadata into explanation details
            for pr in prov_rows:
                if pr.node_id in match_map:
                    meta = json.loads(pr.metadata_json) if pr.metadata_json else {}
                    trust = meta.get("trust_level", "")
                    m = match_map[pr.node_id]
                    if trust and m.explanation:
                        m.explanation.details = (
                            f"Trust level: {trust}."
                        )

    # --- Deduplication and sorting ---

    @staticmethod
    def _deduplicate(
        candidates: list[RetrievalMatch],
    ) -> list[RetrievalMatch]:
        """Keep highest-scored match per object_id."""
        seen: dict[str, RetrievalMatch] = {}
        for c in candidates:
            existing = seen.get(c.object_id)
            if existing is None or c.score > existing.score:
                seen[c.object_id] = c
        return list(seen.values())

    @staticmethod
    def _sort_matches(matches: list[RetrievalMatch]) -> list[RetrievalMatch]:
        """Deterministic sort: score DESC, trust ASC, approval ASC, name ASC."""
        return sorted(
            matches,
            key=lambda m: (
                -m.score,
                _trust_rank(m.trust_level or ""),
                _approval_rank(m.approval_status or ""),
                m.object_name.lower(),
            ),
        )

