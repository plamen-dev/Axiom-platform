"""Tests for the Semantic Retrieval Engine."""

from __future__ import annotations

import json
import tempfile

import pytest
from axiom_core.knowledge_graph import (
    GraphEdgeType,
    GraphNodeType,
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from axiom_core.semantic_retrieval import (
    _SCORE_EXACT_MATCH,
    MAX_RESULTS_CAP,
    MAX_RESULTS_DEFAULT,
    RetrievalEvidence,
    RetrievalExplanation,
    RetrievalMatch,
    RetrievalQuery,
    RetrievalResult,
    SemanticRetrievalEngine,
    _approval_rank,
    _trust_rank,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fresh_db() -> str:
    return tempfile.mktemp(suffix=".db")


def _seed_graph(db_path: str) -> dict[str, str]:
    """Seed a graph with test data. Returns node IDs."""
    graph = KnowledgeGraph(db_path)

    nodes = [
        KnowledgeGraphNode(
            node_id="obj-room-occupancy",
            node_type=GraphNodeType.KNOWLEDGE_OBJECT,
            source_registry="knowledge_objects",
            label="Room Occupancy",
            metadata={"object_type": "concept", "description": "Room occupancy rules"},
        ),
        KnowledgeGraphNode(
            node_id="obj-diffuser-placement",
            node_type=GraphNodeType.KNOWLEDGE_OBJECT,
            source_registry="knowledge_objects",
            label="Diffuser Placement",
            metadata={"object_type": "pattern", "description": "HVAC diffuser placement rules"},
        ),
        KnowledgeGraphNode(
            node_id="obj-lighting-load",
            node_type=GraphNodeType.KNOWLEDGE_OBJECT,
            source_registry="knowledge_objects",
            label="Lighting Load",
            metadata={"object_type": "rule"},
        ),
        KnowledgeGraphNode(
            node_id="wf-room-name",
            node_type=GraphNodeType.WORKFLOW,
            source_registry="workflows",
            label="Room Name Flow",
            metadata={"description": "Complete room naming workflow"},
        ),
        KnowledgeGraphNode(
            node_id="step-get-room",
            node_type=GraphNodeType.WORKFLOW_STEP,
            source_registry="workflows",
            label="Get Room Type from Room Occupancy",
            metadata={"step_order": 1},
        ),
        KnowledgeGraphNode(
            node_id="prov-room-occ",
            node_type=GraphNodeType.PROVENANCE,
            source_registry="knowledge_provenance",
            label="Room Occupancy Provenance",
            metadata={"trust_level": "founder_verified", "confidence_score": 0.95, "origin": "manual"},
        ),
        KnowledgeGraphNode(
            node_id="prov-lighting",
            node_type=GraphNodeType.PROVENANCE,
            source_registry="knowledge_provenance",
            label="Lighting Load Provenance",
            metadata={"trust_level": "candidate", "confidence_score": 0.3, "origin": "auto"},
        ),
        KnowledgeGraphNode(
            node_id="review-room-occ",
            node_type=GraphNodeType.REVIEW,
            source_registry="knowledge_reviews",
            label="Review: Room Occupancy",
            metadata={"decision": "approved", "reviewer": "plamen", "reason": "human_validation"},
        ),
        KnowledgeGraphNode(
            node_id="review-lighting",
            node_type=GraphNodeType.REVIEW,
            source_registry="knowledge_reviews",
            label="Review: Lighting Load",
            metadata={"decision": "proposed", "reviewer": "system", "reason": "low_confidence"},
        ),
        KnowledgeGraphNode(
            node_id="cap-inventory",
            node_type=GraphNodeType.CAPABILITY,
            source_registry="capability_state",
            label="InventoryModel",
            metadata={"status": "validated"},
        ),
        KnowledgeGraphNode(
            node_id="candidate-grid-pattern",
            node_type=GraphNodeType.LEARNING_CANDIDATE,
            source_registry="learning_candidates",
            label="Grid Creation Pattern",
            metadata={"candidate_type": "repeated_success", "strength": "strong"},
        ),
    ]

    edges = [
        KnowledgeGraphEdge(
            edge_id="wf-room-name--has_step-->step-get-room",
            source_node_id="wf-room-name",
            target_node_id="step-get-room",
            edge_type=GraphEdgeType.HAS_STEP,
            source_registry="workflows",
        ),
        KnowledgeGraphEdge(
            edge_id="step-get-room--consumes-->obj-room-occupancy",
            source_node_id="step-get-room",
            target_node_id="obj-room-occupancy",
            edge_type=GraphEdgeType.CONSUMES,
            source_registry="workflows",
        ),
        KnowledgeGraphEdge(
            edge_id="obj-room-occupancy--approved_by-->review-room-occ",
            source_node_id="obj-room-occupancy",
            target_node_id="review-room-occ",
            edge_type=GraphEdgeType.APPROVED_BY,
            source_registry="knowledge_reviews",
        ),
        KnowledgeGraphEdge(
            edge_id="obj-lighting-load--reviewed_by-->review-lighting",
            source_node_id="obj-lighting-load",
            target_node_id="review-lighting",
            edge_type=GraphEdgeType.REVIEWED_BY,
            source_registry="knowledge_reviews",
        ),
        KnowledgeGraphEdge(
            edge_id="obj-room-occupancy--depends_on-->obj-lighting-load",
            source_node_id="obj-room-occupancy",
            target_node_id="obj-lighting-load",
            edge_type=GraphEdgeType.DEPENDS_ON,
            source_registry="knowledge_objects",
        ),
    ]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    registries = sorted({n.source_registry for n in nodes})
    graph._persist_graph(nodes, edges, registries, now)
    return {
        "room_occ": "obj-room-occupancy",
        "diffuser": "obj-diffuser-placement",
        "lighting": "obj-lighting-load",
        "wf": "wf-room-name",
        "step": "step-get-room",
        "prov_room": "prov-room-occ",
        "prov_lighting": "prov-lighting",
        "review_room": "review-room-occ",
        "review_lighting": "review-lighting",
        "cap": "cap-inventory",
        "candidate": "candidate-grid-pattern",
    }


# ---------------------------------------------------------------------------
# Test: Data models
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_explanation_to_dict(self) -> None:
        e = RetrievalExplanation(reason="Exact match.", details="Trust: high")
        d = e.to_dict()
        assert d["reason"] == "Exact match."
        assert d["details"] == "Trust: high"

    def test_explanation_no_details(self) -> None:
        e = RetrievalExplanation(reason="Partial match.")
        d = e.to_dict()
        assert "details" not in d

    def test_evidence_to_dict(self) -> None:
        ev = RetrievalEvidence(
            evidence_type="provenance",
            path="/artifacts/evidence.json",
            trust_level="founder_verified",
            confidence_score=0.95,
        )
        d = ev.to_dict()
        assert d["evidence_type"] == "provenance"
        assert d["trust_level"] == "founder_verified"
        assert d["confidence_score"] == 0.95

    def test_match_to_dict(self) -> None:
        m = RetrievalMatch(
            object_id="id1",
            object_name="Test Object",
            object_type="concept",
            score=85.0,
            source_registry="knowledge_objects",
            trust_level="human_verified",
            approval_status="approved",
            explanation=RetrievalExplanation(reason="Exact match."),
        )
        d = m.to_dict()
        assert d["object_id"] == "id1"
        assert d["score"] == 85.0
        assert d["explanation"]["reason"] == "Exact match."

    def test_query_to_dict(self) -> None:
        q = RetrievalQuery(query_text="room occupancy", query_type="workflow")
        d = q.to_dict()
        assert d["query_text"] == "room occupancy"
        assert d["query_type"] == "workflow"
        assert d["max_results"] == MAX_RESULTS_DEFAULT

    def test_result_to_dict(self) -> None:
        q = RetrievalQuery(query_text="test")
        r = RetrievalResult(query=q, matches=[], total_candidates=0)
        d = r.to_dict()
        assert d["result_count"] == 0
        assert d["total_candidates"] == 0
        assert "created_at" in d


# ---------------------------------------------------------------------------
# Test: Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_trust_rank_known(self) -> None:
        assert _trust_rank("founder_verified") == 0
        assert _trust_rank("candidate") == 4

    def test_trust_rank_unknown(self) -> None:
        assert _trust_rank("bogus") == 6

    def test_approval_rank_known(self) -> None:
        assert _approval_rank("approved") == 0
        assert _approval_rank("rejected") == 3

    def test_approval_rank_unknown(self) -> None:
        assert _approval_rank("unknown") == 6


# ---------------------------------------------------------------------------
# Test: Query validation
# ---------------------------------------------------------------------------


class TestQueryValidation:
    def test_empty_query_raises(self) -> None:
        db = _fresh_db()
        engine = SemanticRetrievalEngine(db)
        with pytest.raises(ValueError, match="empty"):
            engine.retrieve(RetrievalQuery(query_text=""))

    def test_whitespace_only_raises(self) -> None:
        db = _fresh_db()
        engine = SemanticRetrievalEngine(db)
        with pytest.raises(ValueError, match="empty"):
            engine.retrieve(RetrievalQuery(query_text="   "))

    def test_max_results_capped(self) -> None:
        q = RetrievalQuery(query_text="test", max_results=9999)
        assert q.max_results == MAX_RESULTS_CAP

    def test_max_results_floor(self) -> None:
        q = RetrievalQuery(query_text="test", max_results=0)
        assert q.max_results == 1

    def test_unknown_type_returns_empty(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(
            RetrievalQuery(query_text="room", query_type="bogus_type")
        )
        assert result.matches == []
        assert result.total_candidates == 0


# ---------------------------------------------------------------------------
# Test: Exact match retrieval
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_name_match(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room Occupancy"))
        names = [m.object_name for m in result.matches]
        assert "Room Occupancy" in names
        # The exact match should have highest base score
        room_match = next(m for m in result.matches if m.object_name == "Room Occupancy")
        assert room_match.score >= _SCORE_EXACT_MATCH

    def test_exact_match_case_insensitive(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="room occupancy"))
        names = [m.object_name for m in result.matches]
        assert "Room Occupancy" in names


# ---------------------------------------------------------------------------
# Test: Partial match retrieval
# ---------------------------------------------------------------------------


class TestPartialMatch:
    def test_partial_name_match(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Occupancy"))
        names = [m.object_name for m in result.matches]
        assert "Room Occupancy" in names
        # Step label contains "Room Occupancy" → also matched
        assert any("Occupancy" in n for n in names)

    def test_partial_match_score_lower_than_exact(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        # "Room Occupancy" is exact; "Occupancy" is partial
        result = engine.retrieve(RetrievalQuery(query_text="Room Occupancy"))
        exact_match = next(
            (m for m in result.matches if m.object_name == "Room Occupancy"),
            None,
        )
        partial_match = next(
            (m for m in result.matches if m.object_name == "Room Occupancy Provenance"),
            None,
        )
        if exact_match and partial_match:
            assert exact_match.score > partial_match.score


# ---------------------------------------------------------------------------
# Test: Type-filtered retrieval
# ---------------------------------------------------------------------------


class TestTypeFiltered:
    def test_workflow_type_filter(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(
            RetrievalQuery(query_text="Room", query_type="workflow")
        )
        for m in result.matches:
            assert m.object_type == "workflow"

    def test_capability_type_filter(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(
            RetrievalQuery(query_text="InventoryModel", query_type="capability")
        )
        assert len(result.matches) == 1
        assert result.matches[0].object_name == "InventoryModel"
        assert result.matches[0].object_type == "capability"

    def test_type_aliases(self) -> None:
        """'object' and 'knowledge_object' both map to KNOWLEDGE_OBJECT."""
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        r1 = engine.retrieve(
            RetrievalQuery(query_text="Room", query_type="object")
        )
        r2 = engine.retrieve(
            RetrievalQuery(query_text="Room", query_type="knowledge_object")
        )
        assert len(r1.matches) == len(r2.matches)


# ---------------------------------------------------------------------------
# Test: Relationship-aware retrieval
# ---------------------------------------------------------------------------


class TestRelationshipAware:
    def test_related_nodes_included(self) -> None:
        """Searching 'Room Occupancy' should also return connected nodes."""
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room Occupancy"))
        # The workflow step consumes Room Occupancy
        # The review is connected via approved_by
        # Lighting Load is connected via depends_on
        # At minimum we should get some relationship matches
        assert len(result.matches) > 1

    def test_relationship_explanation(self) -> None:
        """Relationship matches should have graph-derived explanations."""
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room Occupancy"))
        rel_matches = [
            m for m in result.matches
            if m.explanation and "Relationship" in m.explanation.reason
        ]
        # Should have at least one relationship-derived match
        assert len(rel_matches) >= 1


# ---------------------------------------------------------------------------
# Test: Explanations
# ---------------------------------------------------------------------------


class TestExplanations:
    def test_every_match_has_explanation(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room"))
        for m in result.matches:
            assert m.explanation is not None
            assert m.explanation.reason != ""

    def test_exact_match_explanation(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room Occupancy"))
        exact = next(m for m in result.matches if m.object_name == "Room Occupancy")
        assert "Exact" in exact.explanation.reason

    def test_partial_match_explanation(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Occupancy"))
        partial = next(
            (m for m in result.matches if m.object_name != "Occupancy"),
            None,
        )
        if partial:
            assert "Partial" in partial.explanation.reason or "Relationship" in partial.explanation.reason


# ---------------------------------------------------------------------------
# Test: Trust weighting
# ---------------------------------------------------------------------------


class TestTrustWeighting:
    def test_founder_verified_outranks_candidate(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Provenance"))
        prov_matches = [m for m in result.matches if "Provenance" in m.object_name]
        if len(prov_matches) >= 2:
            founder = next(
                (m for m in prov_matches if m.trust_level == "founder_verified"),
                None,
            )
            candidate_m = next(
                (m for m in prov_matches if m.trust_level == "candidate"),
                None,
            )
            if founder and candidate_m:
                assert founder.score > candidate_m.score


# ---------------------------------------------------------------------------
# Test: Approval weighting
# ---------------------------------------------------------------------------


class TestApprovalWeighting:
    def test_approved_outranks_proposed(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Review"))
        review_matches = [m for m in result.matches if "Review" in m.object_name]
        if len(review_matches) >= 2:
            approved = next(
                (m for m in review_matches if m.approval_status == "approved"),
                None,
            )
            proposed = next(
                (m for m in review_matches if m.approval_status == "proposed"),
                None,
            )
            if approved and proposed:
                assert approved.score > proposed.score


# ---------------------------------------------------------------------------
# Test: Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_ordering_is_stable(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        r1 = engine.retrieve(RetrievalQuery(query_text="Room"))
        r2 = engine.retrieve(RetrievalQuery(query_text="Room"))
        assert [m.object_id for m in r1.matches] == [m.object_id for m in r2.matches]
        assert [m.score for m in r1.matches] == [m.score for m in r2.matches]

    def test_score_descending(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room"))
        scores = [m.score for m in result.matches]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Test: JSON output
# ---------------------------------------------------------------------------


class TestJSON:
    def test_json_output_valid(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="Room"))
        j = engine.to_json(result)
        parsed = json.loads(j)
        assert "matches" in parsed
        assert "query" in parsed
        assert parsed["query"]["query_text"] == "Room"

    def test_json_round_trip(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        engine = SemanticRetrievalEngine(db)
        result = engine.retrieve(RetrievalQuery(query_text="InventoryModel"))
        j = engine.to_json(result)
        parsed = json.loads(j)
        assert parsed["result_count"] == len(result.matches)
        assert parsed["total_candidates"] == result.total_candidates


# ---------------------------------------------------------------------------
# Test: No mutation
# ---------------------------------------------------------------------------


class TestNoMutation:
    def test_retrieval_does_not_change_node_count(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        graph = KnowledgeGraph(db)
        before = graph.node_count()

        engine = SemanticRetrievalEngine(db)
        engine.retrieve(RetrievalQuery(query_text="Room"))
        engine.retrieve(RetrievalQuery(query_text="Lighting"))
        engine.retrieve(RetrievalQuery(query_text="InventoryModel"))

        after = graph.node_count()
        assert before == after

    def test_retrieval_does_not_change_edge_count(self) -> None:
        db = _fresh_db()
        _seed_graph(db)
        graph = KnowledgeGraph(db)
        before = graph.edge_count()

        engine = SemanticRetrievalEngine(db)
        engine.retrieve(RetrievalQuery(query_text="Room"))

        after = graph.edge_count()
        assert before == after
