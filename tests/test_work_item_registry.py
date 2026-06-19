"""Tests for Autonomous Work Item Registry v1."""

import json

import pytest
from axiom_core.work_item_registry import (
    WorkItemDependency,
    WorkItemEvidence,
    WorkItemPriority,
    WorkItemRegistry,
    WorkItemStatus,
    WorkItemType,
)


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    db = str(tmp_path / "work_items.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db)
    return WorkItemRegistry(db_path=db)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_work_item_types(self):
        expected = {
            "bug_fix", "feature", "cleanup", "test", "documentation",
            "refactor", "validation", "investigation", "review_finding",
        }
        assert {t.value for t in WorkItemType} == expected

    def test_work_item_statuses(self):
        expected = {
            "proposed", "approved", "in_progress", "blocked",
            "completed", "rejected", "deferred",
        }
        assert {s.value for s in WorkItemStatus} == expected

    def test_work_item_priorities(self):
        expected = {"critical", "high", "medium", "low", "unset"}
        assert {p.value for p in WorkItemPriority} == expected


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_basic_item(self, registry):
        item = registry.create_item(
            title="Fix parameter validation",
            item_type=WorkItemType.BUG_FIX,
        )
        assert item.item_id
        assert item.title == "Fix parameter validation"
        assert item.item_type == WorkItemType.BUG_FIX
        assert item.status == WorkItemStatus.PROPOSED
        assert item.priority == WorkItemPriority.UNSET
        assert item.created_at
        assert item.updated_at

    def test_create_with_all_fields(self, registry):
        item = registry.create_item(
            title="Add evidence output",
            item_type=WorkItemType.FEATURE,
            description="Write evidence bundles for validation runs",
            priority=WorkItemPriority.HIGH,
            created_by="devin",
        )
        assert item.description == "Write evidence bundles for validation runs"
        assert item.priority == WorkItemPriority.HIGH
        assert item.created_by == "devin"

    def test_create_all_types(self, registry):
        for wt in WorkItemType:
            item = registry.create_item(title=f"Item {wt.value}", item_type=wt)
            assert item.item_type == wt

    def test_create_persists(self, registry):
        item = registry.create_item(
            title="Persisted item",
            item_type=WorkItemType.CLEANUP,
        )
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert fetched.title == "Persisted item"
        assert fetched.item_type == WorkItemType.CLEANUP

    def test_create_records_history(self, registry):
        item = registry.create_item(
            title="History test",
            item_type=WorkItemType.TEST,
            created_by="tester",
        )
        history = registry.get_history(item.item_id)
        assert len(history.events) == 1
        assert history.events[0]["action"] == "created"
        assert history.events[0]["new_value"] == "proposed"
        assert history.events[0]["actor"] == "tester"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestRead:
    def test_get_unknown_id_returns_none(self, registry):
        assert registry.get_item("nonexistent-id") is None

    def test_list_empty(self, registry):
        assert registry.list_items() == []

    def test_list_items_ordered_by_creation(self, registry):
        a = registry.create_item(title="First", item_type=WorkItemType.BUG_FIX)
        b = registry.create_item(title="Second", item_type=WorkItemType.FEATURE)
        items = registry.list_items()
        assert len(items) == 2
        assert items[0].item_id == b.item_id
        assert items[1].item_id == a.item_id

    def test_list_filter_by_status(self, registry):
        a = registry.create_item(title="Proposed", item_type=WorkItemType.BUG_FIX)
        b = registry.create_item(title="Approved", item_type=WorkItemType.BUG_FIX)
        registry.update_status(b.item_id, WorkItemStatus.APPROVED)
        proposed = registry.list_items(status_filter=WorkItemStatus.PROPOSED)
        assert len(proposed) == 1
        assert proposed[0].item_id == a.item_id

    def test_list_filter_by_type(self, registry):
        registry.create_item(title="Bug", item_type=WorkItemType.BUG_FIX)
        registry.create_item(title="Feature", item_type=WorkItemType.FEATURE)
        bugs = registry.list_items(type_filter=WorkItemType.BUG_FIX)
        assert len(bugs) == 1
        assert bugs[0].title == "Bug"


# ---------------------------------------------------------------------------
# Update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status(self, registry):
        item = registry.create_item(title="To approve", item_type=WorkItemType.BUG_FIX)
        updated = registry.update_status(item.item_id, WorkItemStatus.APPROVED)
        assert updated.status == WorkItemStatus.APPROVED

    def test_update_status_persists(self, registry):
        item = registry.create_item(title="Persist status", item_type=WorkItemType.BUG_FIX)
        registry.update_status(item.item_id, WorkItemStatus.IN_PROGRESS, actor="dev")
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert fetched.status == WorkItemStatus.IN_PROGRESS

    def test_update_status_records_history(self, registry):
        item = registry.create_item(title="History", item_type=WorkItemType.BUG_FIX)
        registry.update_status(
            item.item_id, WorkItemStatus.APPROVED, actor="lead", reason="Looks good"
        )
        history = registry.get_history(item.item_id)
        assert len(history.events) == 2
        change = history.events[1]
        assert change["action"] == "status_changed"
        assert change["old_value"] == "proposed"
        assert change["new_value"] == "approved"
        assert change["actor"] == "lead"
        assert change["details"]["reason"] == "Looks good"

    def test_update_status_unknown_id_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.update_status("missing", WorkItemStatus.APPROVED)

    def test_update_status_same_status_raises(self, registry):
        item = registry.create_item(title="Same", item_type=WorkItemType.BUG_FIX)
        with pytest.raises(ValueError, match="already"):
            registry.update_status(item.item_id, WorkItemStatus.PROPOSED)

    def test_full_lifecycle(self, registry):
        item = registry.create_item(title="Lifecycle", item_type=WorkItemType.FEATURE)
        registry.update_status(item.item_id, WorkItemStatus.APPROVED)
        registry.update_status(item.item_id, WorkItemStatus.IN_PROGRESS)
        registry.update_status(item.item_id, WorkItemStatus.COMPLETED)
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert fetched.status == WorkItemStatus.COMPLETED
        history = registry.get_history(item.item_id)
        assert len(history.events) == 4


# ---------------------------------------------------------------------------
# Update fields
# ---------------------------------------------------------------------------


class TestUpdateFields:
    def test_update_title(self, registry):
        item = registry.create_item(title="Old title", item_type=WorkItemType.BUG_FIX)
        updated = registry.update_fields(item.item_id, title="New title")
        assert updated.title == "New title"
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert fetched.title == "New title"

    def test_update_priority(self, registry):
        item = registry.create_item(title="Prio", item_type=WorkItemType.BUG_FIX)
        updated = registry.update_fields(item.item_id, priority=WorkItemPriority.CRITICAL)
        assert updated.priority == WorkItemPriority.CRITICAL

    def test_update_assigned_to(self, registry):
        item = registry.create_item(title="Assign", item_type=WorkItemType.BUG_FIX)
        updated = registry.update_fields(item.item_id, assigned_to="alice")
        assert updated.assigned_to == "alice"

    def test_update_no_changes(self, registry):
        item = registry.create_item(title="Same", item_type=WorkItemType.BUG_FIX)
        updated = registry.update_fields(item.item_id, title="Same")
        assert updated.title == "Same"
        history = registry.get_history(item.item_id)
        assert len(history.events) == 1

    def test_update_unknown_id_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.update_fields("missing", title="New")

    def test_update_records_history(self, registry):
        item = registry.create_item(title="Track", item_type=WorkItemType.BUG_FIX)
        registry.update_fields(item.item_id, title="Updated", actor="dev")
        history = registry.get_history(item.item_id)
        assert len(history.events) == 2
        assert history.events[1]["action"] == "fields_updated"

    def test_clear_assigned_to(self, registry):
        item = registry.create_item(title="Clear", item_type=WorkItemType.BUG_FIX)
        registry.update_fields(item.item_id, assigned_to="alice")
        updated = registry.update_fields(item.item_id, assigned_to="")
        assert updated.assigned_to is None

    def test_clear_description(self, registry):
        item = registry.create_item(
            title="Clear desc",
            item_type=WorkItemType.BUG_FIX,
            description="Old desc",
        )
        updated = registry.update_fields(item.item_id, description="")
        assert updated.description is None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_add_evidence(self, registry):
        item = registry.create_item(title="Evidence", item_type=WorkItemType.VALIDATION)
        evidence = WorkItemEvidence(
            evidence_type="test_result",
            reference_id="test-001",
            description="All 42 tests pass",
        )
        updated = registry.add_evidence(item.item_id, evidence)
        assert len(updated.evidence) == 1
        assert updated.evidence[0].evidence_type == "test_result"
        assert updated.evidence[0].reference_id == "test-001"

    def test_evidence_persists(self, registry):
        item = registry.create_item(title="Persist", item_type=WorkItemType.VALIDATION)
        evidence = WorkItemEvidence(evidence_type="lint_pass")
        registry.add_evidence(item.item_id, evidence)
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert len(fetched.evidence) == 1

    def test_multiple_evidence(self, registry):
        item = registry.create_item(title="Multi", item_type=WorkItemType.BUG_FIX)
        registry.add_evidence(item.item_id, WorkItemEvidence(evidence_type="test"))
        registry.add_evidence(item.item_id, WorkItemEvidence(evidence_type="lint"))
        fetched = registry.get_item(item.item_id)
        assert fetched is not None
        assert len(fetched.evidence) == 2

    def test_evidence_unknown_id_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.add_evidence("missing", WorkItemEvidence(evidence_type="x"))

    def test_evidence_records_history(self, registry):
        item = registry.create_item(title="Hist", item_type=WorkItemType.BUG_FIX)
        registry.add_evidence(item.item_id, WorkItemEvidence(evidence_type="test"))
        history = registry.get_history(item.item_id)
        assert any(e["action"] == "evidence_added" for e in history.events)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_add_dependency(self, registry):
        a = registry.create_item(title="A", item_type=WorkItemType.BUG_FIX)
        b = registry.create_item(title="B", item_type=WorkItemType.BUG_FIX)
        dep = registry.add_dependency(a.item_id, b.item_id)
        assert dep.item_id == a.item_id
        assert dep.depends_on_id == b.item_id
        assert dep.dependency_type == "blocks"

    def test_dependency_persists(self, registry):
        a = registry.create_item(title="A", item_type=WorkItemType.FEATURE)
        b = registry.create_item(title="B", item_type=WorkItemType.FEATURE)
        registry.add_dependency(a.item_id, b.item_id)
        deps = registry.list_dependencies(a.item_id)
        assert len(deps) == 1
        assert deps[0].depends_on_id == b.item_id

    def test_dependency_loaded_with_item(self, registry):
        a = registry.create_item(title="A", item_type=WorkItemType.CLEANUP)
        b = registry.create_item(title="B", item_type=WorkItemType.CLEANUP)
        registry.add_dependency(a.item_id, b.item_id)
        fetched = registry.get_item(a.item_id)
        assert fetched is not None
        assert len(fetched.dependencies) == 1

    def test_self_dependency_raises(self, registry):
        a = registry.create_item(title="Self", item_type=WorkItemType.BUG_FIX)
        with pytest.raises(ValueError, match="cannot depend on itself"):
            registry.add_dependency(a.item_id, a.item_id)

    def test_duplicate_dependency_raises(self, registry):
        a = registry.create_item(title="A", item_type=WorkItemType.BUG_FIX)
        b = registry.create_item(title="B", item_type=WorkItemType.BUG_FIX)
        registry.add_dependency(a.item_id, b.item_id)
        with pytest.raises(ValueError, match="already exists"):
            registry.add_dependency(a.item_id, b.item_id)

    def test_unknown_item_raises(self, registry):
        a = registry.create_item(title="A", item_type=WorkItemType.BUG_FIX)
        with pytest.raises(ValueError, match="not found"):
            registry.add_dependency(a.item_id, "missing")

    def test_unknown_source_raises(self, registry):
        b = registry.create_item(title="B", item_type=WorkItemType.BUG_FIX)
        with pytest.raises(ValueError, match="not found"):
            registry.add_dependency("missing", b.item_id)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestHistory:
    def test_history_unknown_id_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.get_history("missing")

    def test_history_preserves_order(self, registry):
        item = registry.create_item(title="Order", item_type=WorkItemType.BUG_FIX)
        registry.update_status(item.item_id, WorkItemStatus.APPROVED)
        registry.update_status(item.item_id, WorkItemStatus.IN_PROGRESS)
        registry.update_status(item.item_id, WorkItemStatus.COMPLETED)
        history = registry.get_history(item.item_id)
        assert len(history.events) == 4
        actions = [e["action"] for e in history.events]
        assert actions == ["created", "status_changed", "status_changed", "status_changed"]

    def test_history_to_dict(self, registry):
        item = registry.create_item(title="Dict", item_type=WorkItemType.BUG_FIX)
        history = registry.get_history(item.item_id)
        d = history.to_dict()
        assert d["item_id"] == item.item_id
        assert d["event_count"] == 1
        assert len(d["events"]) == 1


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_work_item_to_dict(self, registry):
        item = registry.create_item(
            title="Serialize",
            item_type=WorkItemType.REVIEW_FINDING,
            priority=WorkItemPriority.HIGH,
        )
        d = item.to_dict()
        assert d["item_type"] == "review_finding"
        assert d["status"] == "proposed"
        assert d["priority"] == "high"
        serialized = json.dumps(d, default=str)
        assert "Serialize" in serialized

    def test_evidence_to_dict(self):
        e = WorkItemEvidence(
            evidence_type="test",
            reference_id="ref-1",
            description="Passed",
        )
        d = e.to_dict()
        assert d["evidence_type"] == "test"
        assert d["reference_id"] == "ref-1"

    def test_evidence_round_trip(self):
        original = WorkItemEvidence(
            evidence_type="lint",
            reference_id="r1",
            description="Clean",
        )
        d = original.to_dict()
        restored = WorkItemEvidence.from_dict(d)
        assert restored.evidence_type == original.evidence_type
        assert restored.reference_id == original.reference_id

    def test_dependency_to_dict(self):
        dep = WorkItemDependency(
            item_id="a",
            depends_on_id="b",
            dependency_type="blocks",
        )
        d = dep.to_dict()
        assert d["item_id"] == "a"
        assert d["depends_on_id"] == "b"

    def test_list_items_json_output(self, registry):
        registry.create_item(title="One", item_type=WorkItemType.BUG_FIX)
        registry.create_item(title="Two", item_type=WorkItemType.FEATURE)
        items = registry.list_items()
        payload = json.dumps([i.to_dict() for i in items], default=str)
        parsed = json.loads(payload)
        assert len(parsed) == 2


# ---------------------------------------------------------------------------
# No state mutation verification
# ---------------------------------------------------------------------------


class TestNoStateMutation:
    """Verify registry operations don't mutate caller data."""

    def test_create_does_not_mutate_nothing(self, registry):
        registry.create_item(title="Safe", item_type=WorkItemType.BUG_FIX)

    def test_list_returns_independent_objects(self, registry):
        registry.create_item(title="A", item_type=WorkItemType.BUG_FIX)
        items1 = registry.list_items()
        items2 = registry.list_items()
        assert items1[0] is not items2[0]
