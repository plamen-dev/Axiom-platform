"""Tests for the Knowledge Object Model (PR #37).

Covers: objects persist, relationships persist, cycles don't crash,
JSON valid, deterministic ordering.
"""

import json

import pytest
from axiom_core.knowledge_objects import (
    KnowledgeObject,
    KnowledgeObjectRegistry,
    KnowledgeObjectType,
    KnowledgeReference,
    KnowledgeRelationship,
    RelationshipType,
)


@pytest.fixture()
def registry(tmp_path):
    """Isolated registry with a temporary database."""
    db = str(tmp_path / "test_knowledge_objects.db")
    return KnowledgeObjectRegistry(db_path=db)


# ---------------------------------------------------------------------------
# TestObjectPersistence
# ---------------------------------------------------------------------------


class TestObjectPersistence:
    """Objects can be created, retrieved, and updated."""

    def test_create_and_retrieve(self, registry):
        obj = KnowledgeObject(
            object_id="obj_001",
            object_name="Grid Creation Pattern",
            object_type=KnowledgeObjectType.PATTERN,
            description="Standard grid creation workflow",
        )
        registry.create_object(obj)
        retrieved = registry.get_object("obj_001")
        assert retrieved is not None
        assert retrieved.object_name == "Grid Creation Pattern"
        assert retrieved.object_type == KnowledgeObjectType.PATTERN

    def test_update_existing(self, registry):
        obj = KnowledgeObject(
            object_id="obj_002",
            object_name="Old Name",
            object_type=KnowledgeObjectType.CONCEPT,
        )
        registry.create_object(obj)
        obj.object_name = "New Name"
        registry.create_object(obj)
        retrieved = registry.get_object("obj_002")
        assert retrieved.object_name == "New Name"

    def test_multiple_types(self, registry):
        types = [
            KnowledgeObjectType.CONCEPT,
            KnowledgeObjectType.RULE,
            KnowledgeObjectType.WORKFLOW,
            KnowledgeObjectType.CAPABILITY,
        ]
        for i, t in enumerate(types):
            registry.create_object(KnowledgeObject(
                object_id=f"obj_{i}",
                object_name=f"Object {i}",
                object_type=t,
            ))
        assert registry.object_count() == 4

    def test_timestamps_exist(self, registry):
        obj = KnowledgeObject(
            object_id="obj_ts",
            object_name="Timestamped",
            object_type=KnowledgeObjectType.DECISION,
        )
        registry.create_object(obj)
        retrieved = registry.get_object("obj_ts")
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_object("nonexistent") is None

    def test_metadata_persists(self, registry):
        obj = KnowledgeObject(
            object_id="obj_meta",
            object_name="With Metadata",
            object_type=KnowledgeObjectType.PLAYBOOK,
            metadata={"priority": "high", "tags": ["grid", "revit"]},
        )
        registry.create_object(obj)
        retrieved = registry.get_object("obj_meta")
        assert retrieved.metadata == {"priority": "high", "tags": ["grid", "revit"]}


# ---------------------------------------------------------------------------
# TestRelationshipPersistence
# ---------------------------------------------------------------------------


class TestRelationshipPersistence:
    """Relationships persist between objects."""

    def test_create_and_list(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="a", object_name="A", object_type=KnowledgeObjectType.CONCEPT,
        ))
        registry.create_object(KnowledgeObject(
            object_id="b", object_name="B", object_type=KnowledgeObjectType.RULE,
        ))
        rel = KnowledgeRelationship(
            source_object_id="a",
            target_object_id="b",
            relationship_type=RelationshipType.DEPENDS_ON,
            notes="A depends on B",
        )
        registry.create_relationship(rel)
        rels = registry.list_relationships()
        assert len(rels) == 1
        assert rels[0].source_object_id == "a"
        assert rels[0].target_object_id == "b"
        assert rels[0].relationship_type == RelationshipType.DEPENDS_ON

    def test_multiple_relationships(self, registry):
        for i in range(3):
            registry.create_object(KnowledgeObject(
                object_id=f"n{i}", object_name=f"Node {i}",
                object_type=KnowledgeObjectType.CONCEPT,
            ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="n0", target_object_id="n1",
            relationship_type=RelationshipType.PRODUCES,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="n1", target_object_id="n2",
            relationship_type=RelationshipType.CONSUMES,
        ))
        assert registry.relationship_count() == 2

    def test_filter_by_object_id(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="x", object_name="X", object_type=KnowledgeObjectType.PATTERN,
        ))
        registry.create_object(KnowledgeObject(
            object_id="y", object_name="Y", object_type=KnowledgeObjectType.PATTERN,
        ))
        registry.create_object(KnowledgeObject(
            object_id="z", object_name="Z", object_type=KnowledgeObjectType.PATTERN,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="x", target_object_id="y",
            relationship_type=RelationshipType.RELATED_TO,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="y", target_object_id="z",
            relationship_type=RelationshipType.DERIVED_FROM,
        ))
        # "y" is in both relationships
        rels_y = registry.list_relationships(object_id="y")
        assert len(rels_y) == 2
        # "x" is only in one
        rels_x = registry.list_relationships(object_id="x")
        assert len(rels_x) == 1

    def test_filter_by_type(self, registry):
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="a", target_object_id="b",
            relationship_type=RelationshipType.VALIDATED_BY,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="c", target_object_id="d",
            relationship_type=RelationshipType.SUPERSEDES,
        ))
        rels = registry.list_relationships(relationship_type=RelationshipType.VALIDATED_BY)
        assert len(rels) == 1
        assert rels[0].relationship_type == RelationshipType.VALIDATED_BY


# ---------------------------------------------------------------------------
# TestCyclesDoNotCrash
# ---------------------------------------------------------------------------


class TestCyclesDoNotCrash:
    """Cyclic relationships are allowed (metadata, not execution)."""

    def test_self_reference(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="self", object_name="Self-referencing",
            object_type=KnowledgeObjectType.CONCEPT,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="self", target_object_id="self",
            relationship_type=RelationshipType.RELATED_TO,
        ))
        rels = registry.get_relationships_for("self")
        assert len(rels) == 1

    def test_mutual_cycle(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="c1", object_name="C1", object_type=KnowledgeObjectType.RULE,
        ))
        registry.create_object(KnowledgeObject(
            object_id="c2", object_name="C2", object_type=KnowledgeObjectType.RULE,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="c1", target_object_id="c2",
            relationship_type=RelationshipType.DEPENDS_ON,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="c2", target_object_id="c1",
            relationship_type=RelationshipType.DEPENDS_ON,
        ))
        assert registry.relationship_count() == 2
        rels = registry.get_relationships_for("c1")
        assert len(rels) == 2

    def test_triangle_cycle(self, registry):
        for i in range(3):
            registry.create_object(KnowledgeObject(
                object_id=f"t{i}", object_name=f"T{i}",
                object_type=KnowledgeObjectType.WORKFLOW,
            ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="t0", target_object_id="t1",
            relationship_type=RelationshipType.PRODUCES,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="t1", target_object_id="t2",
            relationship_type=RelationshipType.PRODUCES,
        ))
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="t2", target_object_id="t0",
            relationship_type=RelationshipType.PRODUCES,
        ))
        assert registry.relationship_count() == 3


# ---------------------------------------------------------------------------
# TestJsonOutput
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON output is valid and contains required fields."""

    def test_objects_json_valid(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="j1", object_name="JSON Test",
            object_type=KnowledgeObjectType.EVIDENCE_REFERENCE,
        ))
        output = registry.to_json()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_objects_json_required_fields(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="j2", object_name="Fields Test",
            object_type=KnowledgeObjectType.FAILURE_PATTERN,
            description="Test desc",
        ))
        output = registry.to_json()
        data = json.loads(output)
        required = {"object_id", "object_name", "object_type", "description",
                    "source_id", "created_at", "updated_at", "version", "metadata"}
        assert required.issubset(set(data[0].keys()))

    def test_relationships_json_valid(self, registry):
        registry.create_relationship(KnowledgeRelationship(
            source_object_id="r1", target_object_id="r2",
            relationship_type=RelationshipType.CONSUMES,
        ))
        output = registry.relationships_to_json()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1
        required = {"relationship_id", "source_object_id", "target_object_id",
                    "relationship_type", "created_at", "notes"}
        assert required.issubset(set(data[0].keys()))

    def test_object_type_serialized_as_string(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="j3", object_name="Type Test",
            object_type=KnowledgeObjectType.CAPABILITY,
        ))
        data = json.loads(registry.to_json())
        assert data[0]["object_type"] == "capability"


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Listing produces deterministic ordering (by name)."""

    def test_objects_ordered_by_name(self, registry):
        names = ["Zebra", "Apple", "Mango"]
        for i, name in enumerate(names):
            registry.create_object(KnowledgeObject(
                object_id=f"ord_{i}", object_name=name,
                object_type=KnowledgeObjectType.CONCEPT,
            ))
        objects = registry.list_objects()
        result_names = [o.object_name for o in objects]
        assert result_names == sorted(names)

    def test_repeated_list_same_order(self, registry):
        for i in range(5):
            registry.create_object(KnowledgeObject(
                object_id=f"rep_{i}", object_name=f"Item {i:03d}",
                object_type=KnowledgeObjectType.RULE,
            ))
        first = [o.object_id for o in registry.list_objects()]
        second = [o.object_id for o in registry.list_objects()]
        assert first == second

    def test_json_deterministic(self, registry):
        for i in range(3):
            registry.create_object(KnowledgeObject(
                object_id=f"det_{i}", object_name=f"Det {i}",
                object_type=KnowledgeObjectType.PATTERN,
            ))
        first = registry.to_json()
        second = registry.to_json()
        assert first == second


# ---------------------------------------------------------------------------
# TestKnowledgeReference
# ---------------------------------------------------------------------------


class TestKnowledgeReference:
    """KnowledgeReference is a lightweight reference type."""

    def test_to_dict(self):
        ref = KnowledgeReference(
            object_id="ref_001",
            object_name="Test Ref",
            object_type="concept",
        )
        d = ref.to_dict()
        assert d == {
            "object_id": "ref_001",
            "object_name": "Test Ref",
            "object_type": "concept",
        }


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and validation."""

    def test_empty_relationship_ids_rejected(self, registry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.create_relationship(KnowledgeRelationship(
                source_object_id="",
                target_object_id="b",
                relationship_type=RelationshipType.DEPENDS_ON,
            ))
        with pytest.raises(ValueError, match="must not be empty"):
            registry.create_relationship(KnowledgeRelationship(
                source_object_id="a",
                target_object_id="",
                relationship_type=RelationshipType.DEPENDS_ON,
            ))

    def test_empty_metadata_dict_roundtrips(self, registry):
        obj = KnowledgeObject(
            object_id="empty_meta",
            object_name="Empty Metadata",
            object_type=KnowledgeObjectType.CONCEPT,
            metadata={},
        )
        registry.create_object(obj)
        retrieved = registry.get_object("empty_meta")
        assert retrieved.metadata == {}

    def test_name_filter_with_sql_wildcards(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="wc1", object_name="100% Complete",
            object_type=KnowledgeObjectType.CONCEPT,
        ))
        registry.create_object(KnowledgeObject(
            object_id="wc2", object_name="Other Item",
            object_type=KnowledgeObjectType.CONCEPT,
        ))
        # Searching for literal "%" should only match the first
        results = registry.list_objects(name_filter="%")
        assert len(results) == 1
        assert results[0].object_id == "wc1"

    def test_name_filter_with_backslash(self, registry):
        registry.create_object(KnowledgeObject(
            object_id="bs1", object_name=r"path\to\file",
            object_type=KnowledgeObjectType.WORKFLOW,
        ))
        registry.create_object(KnowledgeObject(
            object_id="bs2", object_name="pathtofile",
            object_type=KnowledgeObjectType.WORKFLOW,
        ))
        results = registry.list_objects(name_filter="\\")
        assert len(results) == 1
        assert results[0].object_id == "bs1"
