"""Tests for the Knowledge Graph Foundation v1."""

import json

import pytest
from axiom_core.knowledge_graph import (
    MAX_TRAVERSAL_DEPTH,
    GraphEdgeType,
    GraphNodeType,
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphSnapshot,
    KnowledgeGraphTraversalResult,
    _deterministic_edge_id,
    _escape_like,
)


@pytest.fixture
def graph(tmp_path):
    """Create a KnowledgeGraph backed by a temp SQLite DB."""
    db = str(tmp_path / "test_graph.db")
    return KnowledgeGraph(db)


def _seed_triangle(graph: KnowledgeGraph):
    """Seed a triangle graph: A -> B -> C -> A for cycle testing."""
    from axiom_core.database import get_session, make_session_factory
    from axiom_core.knowledge_graph import (
        KnowledgeGraphEdgeRow,
        KnowledgeGraphNodeRow,
        KnowledgeGraphSnapshotRow,
    )

    sf = make_session_factory(graph._engine)
    now = "2026-01-01T00:00:00+00:00"
    with get_session(sf) as session:
        for nid, label in [("A", "Node A"), ("B", "Node B"), ("C", "Node C")]:
            session.add(KnowledgeGraphNodeRow(
                node_id=nid,
                node_type="knowledge_object",
                source_registry="test",
                label=label,
                metadata_json="{}",
                created_at=now,
            ))
        for src, tgt in [("A", "B"), ("B", "C"), ("C", "A")]:
            session.add(KnowledgeGraphEdgeRow(
                edge_id=f"{src}->{tgt}",
                source_node_id=src,
                target_node_id=tgt,
                edge_type="relates_to",
                source_registry="test",
                metadata_json="{}",
                created_at=now,
            ))
        session.add(KnowledgeGraphSnapshotRow(
            snapshot_id="snap-triangle",
            node_count=3,
            edge_count=3,
            node_types_json='["knowledge_object"]',
            edge_types_json='["relates_to"]',
            source_registries_json='["test"]',
            created_at=now,
        ))


# -----------------------------------------------------------------------
# Data model tests
# -----------------------------------------------------------------------


class TestDataModels:
    def test_node_to_dict(self):
        n = KnowledgeGraphNode(
            node_id="n1",
            node_type=GraphNodeType.KNOWLEDGE_OBJECT,
            source_registry="test",
            label="Test Node",
            metadata={"key": "value"},
        )
        d = n.to_dict()
        assert d["node_id"] == "n1"
        assert d["node_type"] == "knowledge_object"
        assert d["label"] == "Test Node"
        assert d["metadata"] == {"key": "value"}

    def test_edge_to_dict(self):
        e = KnowledgeGraphEdge(
            edge_id="e1",
            source_node_id="n1",
            target_node_id="n2",
            edge_type=GraphEdgeType.DEPENDS_ON,
            source_registry="test",
        )
        d = e.to_dict()
        assert d["edge_id"] == "e1"
        assert d["edge_type"] == "depends_on"
        assert d["source_node_id"] == "n1"
        assert d["target_node_id"] == "n2"

    def test_snapshot_to_dict(self):
        s = KnowledgeGraphSnapshot(
            node_count=5,
            edge_count=3,
            node_types=["knowledge_object", "workflow"],
            edge_types=["depends_on"],
            source_registries=["test"],
        )
        d = s.to_dict()
        assert d["node_count"] == 5
        assert d["edge_count"] == 3
        assert d["node_types"] == ["knowledge_object", "workflow"]

    def test_traversal_result_to_dict(self):
        r = KnowledgeGraphTraversalResult(
            start_node_id="n1",
            depth=2,
            visited_nodes=[
                KnowledgeGraphNode("n1", GraphNodeType.KNOWLEDGE_OBJECT, "test", "N1"),
            ],
            visited_edges=[],
            cycle_detected=True,
        )
        d = r.to_dict()
        assert d["start_node_id"] == "n1"
        assert d["depth"] == 2
        assert d["visited_node_count"] == 1
        assert d["cycle_detected"] is True

    def test_empty_metadata_defaults(self):
        n = KnowledgeGraphNode("n1", GraphNodeType.KNOWLEDGE_OBJECT, "test", "X")
        assert n.metadata == {}
        e = KnowledgeGraphEdge(edge_id="e1")
        assert e.metadata == {}


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


class TestHelpers:
    def test_deterministic_edge_id(self):
        eid = _deterministic_edge_id("src", "tgt", "depends_on")
        assert eid == "src--depends_on-->tgt"
        # Same inputs always produce same ID
        assert _deterministic_edge_id("src", "tgt", "depends_on") == eid

    def test_escape_like(self):
        assert _escape_like("hello%world") == "hello\\%world"
        assert _escape_like("under_score") == "under\\_score"
        assert _escape_like("back\\slash") == "back\\\\slash"


# -----------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------


class TestPersistence:
    def test_node_roundtrip(self, graph):
        _seed_triangle(graph)
        node = graph.get_node("A")
        assert node is not None
        assert node.node_id == "A"
        assert node.label == "Node A"
        assert node.node_type == GraphNodeType.KNOWLEDGE_OBJECT

    def test_edge_roundtrip(self, graph):
        _seed_triangle(graph)
        edges = graph.list_edges(node_id="A")
        assert len(edges) == 2  # A->B outgoing, C->A incoming
        edge_ids = sorted([e.edge_id for e in edges])
        assert "A->B" in edge_ids
        assert "C->A" in edge_ids

    def test_node_count(self, graph):
        assert graph.node_count() == 0
        _seed_triangle(graph)
        assert graph.node_count() == 3

    def test_edge_count(self, graph):
        assert graph.edge_count() == 0
        _seed_triangle(graph)
        assert graph.edge_count() == 3

    def test_snapshot_roundtrip(self, graph):
        _seed_triangle(graph)
        snap = graph.get_latest_snapshot()
        assert snap is not None
        assert snap.node_count == 3
        assert snap.edge_count == 3
        assert snap.source_registries == ["test"]

    def test_list_nodes_filtered_by_type(self, graph):
        _seed_triangle(graph)
        nodes = graph.list_nodes(node_type=GraphNodeType.KNOWLEDGE_OBJECT)
        assert len(nodes) == 3

    def test_list_nodes_filtered_by_label(self, graph):
        _seed_triangle(graph)
        nodes = graph.list_nodes(label_filter="Node A")
        assert len(nodes) == 1
        assert nodes[0].node_id == "A"

    def test_list_edges_filtered_by_type(self, graph):
        _seed_triangle(graph)
        edges = graph.list_edges(edge_type=GraphEdgeType.RELATES_TO)
        assert len(edges) == 3
        edges_none = graph.list_edges(edge_type=GraphEdgeType.DEPENDS_ON)
        assert len(edges_none) == 0

    def test_node_not_found(self, graph):
        assert graph.get_node("nonexistent") is None

    def test_empty_metadata_persists_correctly(self, graph):
        """Empty {} metadata should roundtrip as {} not None."""
        _seed_triangle(graph)
        node = graph.get_node("A")
        assert node is not None
        assert node.metadata == {}

    def test_deterministic_ordering(self, graph):
        """Nodes should be ordered by type then label."""
        _seed_triangle(graph)
        nodes = graph.list_nodes()
        labels = [n.label for n in nodes]
        assert labels == ["Node A", "Node B", "Node C"]


# -----------------------------------------------------------------------
# Neighbors
# -----------------------------------------------------------------------


class TestNeighbors:
    def test_neighbors(self, graph):
        _seed_triangle(graph)
        neighbors = graph.get_neighbors("A")
        neighbor_ids = sorted([n.node_id for n in neighbors])
        assert neighbor_ids == ["B", "C"]

    def test_neighbors_nonexistent_node(self, graph):
        _seed_triangle(graph)
        neighbors = graph.get_neighbors("nonexistent")
        assert neighbors == []

    def test_isolated_node_has_no_neighbors(self, graph):
        from axiom_core.database import get_session, make_session_factory
        from axiom_core.knowledge_graph import KnowledgeGraphNodeRow

        sf = make_session_factory(graph._engine)
        with get_session(sf) as session:
            session.add(KnowledgeGraphNodeRow(
                node_id="isolated",
                node_type="knowledge_object",
                source_registry="test",
                label="Alone",
                metadata_json="{}",
                created_at="2026-01-01T00:00:00+00:00",
            ))
        assert graph.get_neighbors("isolated") == []


# -----------------------------------------------------------------------
# Traversal
# -----------------------------------------------------------------------


class TestTraversal:
    def test_traversal_depth_0(self, graph):
        """Depth 0 should return only the start node."""
        _seed_triangle(graph)
        result = graph.traverse("A", max_depth=0)
        assert len(result.visited_nodes) == 1
        assert result.visited_nodes[0].node_id == "A"
        assert len(result.visited_edges) == 0

    def test_traversal_depth_1(self, graph):
        """Depth 1 returns start + immediate neighbors."""
        _seed_triangle(graph)
        result = graph.traverse("A", max_depth=1)
        visited_ids = sorted([n.node_id for n in result.visited_nodes])
        assert visited_ids == ["A", "B", "C"]

    def test_traversal_cycle_detected(self, graph):
        """Triangle graph should detect a cycle during traversal."""
        _seed_triangle(graph)
        result = graph.traverse("A", max_depth=3)
        assert result.cycle_detected is True
        # All 3 nodes should still be visited
        assert len(result.visited_nodes) == 3

    def test_traversal_does_not_crash_on_cycle(self, graph):
        """Even with large depth, cycles don't cause infinite loop."""
        _seed_triangle(graph)
        result = graph.traverse("A", max_depth=MAX_TRAVERSAL_DEPTH)
        assert len(result.visited_nodes) == 3
        assert result.cycle_detected is True

    def test_traversal_depth_capped(self, graph):
        """Excessive depth is capped at MAX_TRAVERSAL_DEPTH."""
        _seed_triangle(graph)
        result = graph.traverse("A", max_depth=100)
        assert result.depth == MAX_TRAVERSAL_DEPTH

    def test_traversal_nonexistent_start(self, graph):
        """Traversal from a missing node returns empty result."""
        result = graph.traverse("nonexistent", max_depth=2)
        assert len(result.visited_nodes) == 0
        assert len(result.visited_edges) == 0

    def test_traversal_deterministic(self, graph):
        """Two traversals from the same node produce identical results."""
        _seed_triangle(graph)
        r1 = graph.traverse("A", max_depth=2)
        r2 = graph.traverse("A", max_depth=2)
        ids1 = [n.node_id for n in r1.visited_nodes]
        ids2 = [n.node_id for n in r2.visited_nodes]
        assert ids1 == ids2


# -----------------------------------------------------------------------
# Build from registries
# -----------------------------------------------------------------------


class TestBuildFromRegistries:
    def test_build_from_knowledge_objects(self, tmp_path):
        """Build a graph from knowledge objects and relationships."""
        from axiom_core.knowledge_objects import (
            KnowledgeObject,
            KnowledgeObjectRegistry,
            KnowledgeObjectType,
            KnowledgeRelationship,
            RelationshipType,
        )

        db = str(tmp_path / "build_test.db")
        obj_reg = KnowledgeObjectRegistry(db)
        obj_reg.create_object(KnowledgeObject(
            object_id="obj1",
            object_name="Concept A",
            object_type=KnowledgeObjectType.CONCEPT,
        ))
        obj_reg.create_object(KnowledgeObject(
            object_id="obj2",
            object_name="Rule B",
            object_type=KnowledgeObjectType.RULE,
        ))
        obj_reg.create_relationship(KnowledgeRelationship(
            relationship_id="rel1",
            source_object_id="obj1",
            target_object_id="obj2",
            relationship_type=RelationshipType.DEPENDS_ON,
        ))

        graph = KnowledgeGraph(db)
        snapshot = graph.build_from_registries(db)

        assert snapshot.node_count >= 2
        assert snapshot.edge_count >= 1
        assert "knowledge_objects" in snapshot.source_registries

        # Verify nodes persisted
        n1 = graph.get_node("obj1")
        assert n1 is not None
        assert n1.label == "Concept A"
        assert n1.node_type == GraphNodeType.KNOWLEDGE_OBJECT

        n2 = graph.get_node("obj2")
        assert n2 is not None

        # Verify relationship became edge
        edges = graph.list_edges(node_id="obj1")
        assert any(e.edge_type == GraphEdgeType.DEPENDS_ON for e in edges)

    def test_build_from_workflows(self, tmp_path):
        """Build graph from workflow definitions with steps and rules."""
        from axiom_core.workflow_registry import (
            WorkflowDefinition,
            WorkflowKnowledgeRegistry,
            WorkflowRule,
            WorkflowStep,
        )

        db = str(tmp_path / "wf_test.db")
        wf_reg = WorkflowKnowledgeRegistry(db)
        wf = WorkflowDefinition(
            workflow_id="wf1",
            workflow_name="Test Workflow",
            steps=[
                WorkflowStep(step_id="s1", step_name="Step One", step_order=1),
                WorkflowStep(step_id="s2", step_name="Step Two", step_order=2),
            ],
            rules=[
                WorkflowRule(rule_id="r1", rule_name="Rule One"),
            ],
        )
        wf_reg.register_workflow(wf)

        graph = KnowledgeGraph(db)
        snapshot = graph.build_from_registries(db)

        assert "workflows" in snapshot.source_registries
        # 1 workflow + 2 steps + 1 rule = 4 nodes minimum
        wf_node = graph.get_node("wf1")
        assert wf_node is not None
        assert wf_node.node_type == GraphNodeType.WORKFLOW

        step_node = graph.get_node("step:wf1:s1")
        assert step_node is not None
        assert step_node.node_type == GraphNodeType.WORKFLOW_STEP

        rule_node = graph.get_node("rule:wf1:r1")
        assert rule_node is not None
        assert rule_node.node_type == GraphNodeType.RULE

        # Edges: has_step x2, has_rule x1
        wf_edges = graph.list_edges(node_id="wf1")
        assert len(wf_edges) >= 3
        edge_types = [e.edge_type for e in wf_edges]
        assert GraphEdgeType.HAS_STEP in edge_types
        assert GraphEdgeType.HAS_RULE in edge_types

    def test_build_from_reviews(self, tmp_path):
        """Build graph from knowledge reviews."""
        from axiom_core.knowledge_reviews import (
            KnowledgeReview,
            KnowledgeReviewRegistry,
            ReviewDecision,
        )

        db = str(tmp_path / "rev_test.db")
        rev_reg = KnowledgeReviewRegistry(db)
        rev_reg.create_review(KnowledgeReview(
            review_id="rev1",
            knowledge_id="k1",
            knowledge_name="Approved Item",
            decision=ReviewDecision.APPROVED,
        ))

        graph = KnowledgeGraph(db)
        snapshot = graph.build_from_registries(db)

        assert "knowledge_reviews" in snapshot.source_registries
        rev_node = graph.get_node("review:rev1")
        assert rev_node is not None
        assert rev_node.node_type == GraphNodeType.REVIEW
        assert "approved" in rev_node.metadata.get("decision", "")

        # Edge: k1 --approved_by--> review:rev1
        edges = graph.list_edges(node_id="review:rev1")
        assert any(e.edge_type == GraphEdgeType.APPROVED_BY for e in edges)

    def test_build_from_rejected_review(self, tmp_path):
        """Rejected reviews create rejected_by edges."""
        from axiom_core.knowledge_reviews import (
            KnowledgeReview,
            KnowledgeReviewRegistry,
            ReviewDecision,
        )

        db = str(tmp_path / "rej_test.db")
        rev_reg = KnowledgeReviewRegistry(db)
        rev_reg.create_review(KnowledgeReview(
            review_id="rev_rej",
            knowledge_id="k2",
            knowledge_name="Rejected Item",
            decision=ReviewDecision.REJECTED,
        ))

        graph = KnowledgeGraph(db)
        graph.build_from_registries(db)
        edges = graph.list_edges(node_id="review:rev_rej")
        assert any(e.edge_type == GraphEdgeType.REJECTED_BY for e in edges)

    def test_refresh_is_deterministic(self, tmp_path):
        """Two builds from the same data produce the same node/edge counts."""
        from axiom_core.knowledge_objects import (
            KnowledgeObject,
            KnowledgeObjectRegistry,
            KnowledgeObjectType,
        )

        db = str(tmp_path / "determ_test.db")
        obj_reg = KnowledgeObjectRegistry(db)
        obj_reg.create_object(KnowledgeObject(
            object_id="d1", object_name="Det 1",
            object_type=KnowledgeObjectType.CONCEPT,
        ))

        graph = KnowledgeGraph(db)
        s1 = graph.build_from_registries(db)
        s2 = graph.build_from_registries(db)
        assert s1.node_count == s2.node_count
        assert s1.edge_count == s2.edge_count
        assert s1.node_types == s2.node_types

    def test_build_clears_previous_graph(self, tmp_path):
        """Rebuild replaces previous graph entirely."""
        from axiom_core.knowledge_objects import (
            KnowledgeObject,
            KnowledgeObjectRegistry,
            KnowledgeObjectType,
        )

        db = str(tmp_path / "clear_test.db")
        obj_reg = KnowledgeObjectRegistry(db)
        obj_reg.create_object(KnowledgeObject(
            object_id="c1", object_name="Clear 1",
            object_type=KnowledgeObjectType.CONCEPT,
        ))

        graph = KnowledgeGraph(db)
        graph.build_from_registries(db)
        assert graph.node_count() >= 1

        # Seed a manual extra node
        _seed_triangle(graph)
        count_with_extra = graph.node_count()

        # Rebuild should clear the triangle nodes
        graph.build_from_registries(db)
        assert graph.node_count() < count_with_extra


# -----------------------------------------------------------------------
# JSON output
# -----------------------------------------------------------------------


class TestJSON:
    def test_to_json_valid(self, graph):
        _seed_triangle(graph)
        raw = graph.to_json()
        data = json.loads(raw)
        assert "nodes" in data
        assert "edges" in data
        assert "snapshot" in data
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 3
        assert data["snapshot"]["node_count"] == 3

    def test_to_json_empty(self, graph):
        raw = graph.to_json()
        data = json.loads(raw)
        assert len(data["nodes"]) == 0
        assert len(data["edges"]) == 0
        assert data["snapshot"] is None


# -----------------------------------------------------------------------
# Enum coercion
# -----------------------------------------------------------------------


class TestEnumCoercion:
    def test_node_type_coerced(self, graph):
        _seed_triangle(graph)
        node = graph.get_node("A")
        assert isinstance(node.node_type, GraphNodeType)

    def test_edge_type_coerced(self, graph):
        _seed_triangle(graph)
        edges = graph.list_edges()
        for e in edges:
            assert isinstance(e.edge_type, GraphEdgeType)

    def test_unknown_type_preserved(self, graph):
        """Unknown enum values roundtrip as raw strings."""
        from axiom_core.database import get_session, make_session_factory
        from axiom_core.knowledge_graph import KnowledgeGraphNodeRow

        sf = make_session_factory(graph._engine)
        with get_session(sf) as session:
            session.add(KnowledgeGraphNodeRow(
                node_id="unk",
                node_type="future_type",
                source_registry="test",
                label="Unknown",
                metadata_json="{}",
                created_at="2026-01-01T00:00:00+00:00",
            ))
        node = graph.get_node("unk")
        assert node is not None
        assert node.node_type == "future_type"
