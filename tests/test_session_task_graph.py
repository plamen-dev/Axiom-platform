"""Tests for SessionTaskGraphRegistry and Session Task Graph v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_task_graph import (
    DependencyType,
    SessionTask,
    SessionTaskDependency,
    SessionTaskGraphRegistry,
    SessionTaskStatus,
    SessionTaskType,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestSessionTaskType:
    def test_values(self) -> None:
        assert SessionTaskType.IMPLEMENTATION.value == "implementation"
        assert SessionTaskType.VALIDATION.value == "validation"
        assert SessionTaskType.REVIEW.value == "review"
        assert SessionTaskType.REPAIR.value == "repair"
        assert SessionTaskType.REPORTING.value == "reporting"
        assert SessionTaskType.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(SessionTaskType) == 6


class TestSessionTaskStatus:
    def test_values(self) -> None:
        assert SessionTaskStatus.CREATED.value == "created"
        assert SessionTaskStatus.READY.value == "ready"
        assert SessionTaskStatus.BLOCKED.value == "blocked"
        assert SessionTaskStatus.IN_PROGRESS.value == "in_progress"
        assert SessionTaskStatus.COMPLETED.value == "completed"
        assert SessionTaskStatus.FAILED.value == "failed"

    def test_count(self) -> None:
        assert len(SessionTaskStatus) == 6


class TestDependencyType:
    def test_values(self) -> None:
        assert DependencyType.PARENT_CHILD.value == "parent_child"
        assert DependencyType.REQUIRES.value == "requires"
        assert DependencyType.BLOCKS.value == "blocks"
        assert DependencyType.RELATED.value == "related"

    def test_count(self) -> None:
        assert len(DependencyType) == 4


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestSessionTaskDataclass:
    def test_defaults(self) -> None:
        t = SessionTask(title="Test task")
        assert t.task_id
        assert t.title == "Test task"
        assert t.task_type == "other"
        assert t.status == "created"
        assert t.parent_task_id == ""
        assert t.created_at

    def test_to_dict(self) -> None:
        t = SessionTask(title="Test")
        d = t.to_dict()
        assert d["title"] == "Test"
        assert "task_id" in d
        assert "created_at" in d


class TestSessionTaskDependencyDataclass:
    def test_defaults(self) -> None:
        d = SessionTaskDependency(
            source_task_id="a",
            target_task_id="b",
        )
        assert d.dependency_id
        assert d.dependency_type == "related"
        assert d.created_at

    def test_to_dict(self) -> None:
        d = SessionTaskDependency(
            source_task_id="a",
            target_task_id="b",
        )
        result = d.to_dict()
        assert result["source_task_id"] == "a"
        assert result["target_task_id"] == "b"
        assert "dependency_id" in result


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateTask:
    def test_basic(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="Build feature")
        assert task["title"] == "Build feature"
        assert task["task_type"] == "other"
        assert task["status"] == "created"

    def test_custom_fields(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(
            title="Validate PR",
            task_type="validation",
            status="ready",
            description="Run full suite",
        )
        assert task["task_type"] == "validation"
        assert task["status"] == "ready"
        assert task["description"] == "Run full suite"

    def test_with_parent(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        parent = reg.create_task(title="Parent")
        child = reg.create_task(
            title="Child",
            parent_task_id=parent["task_id"],
        )
        assert child["parent_task_id"] == parent["task_id"]

    def test_invalid_type(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid task_type"):
            reg.create_task(title="X", task_type="nonexistent")

    def test_invalid_status(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid status"):
            reg.create_task(title="X", status="nonexistent")


class TestGetTask:
    def test_existing(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        created = reg.create_task(title="Get me")
        found = reg.get_task(created["task_id"])
        assert found is not None
        assert found["title"] == "Get me"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        assert reg.get_task("does-not-exist") is None


class TestListTasks:
    def test_empty(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        assert reg.list_tasks() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        reg.create_task(title="T1")
        reg.create_task(title="T2")
        assert len(reg.list_tasks()) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        reg.create_task(title="Completed", status="completed")
        reg.create_task(title="Blocked", status="blocked")
        reg.create_task(title="Created", status="created")
        result = reg.list_tasks()
        order = [t["status"] for t in result]
        assert order == ["blocked", "created", "completed"]

    def test_filter_type(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        reg.create_task(title="T1", task_type="validation")
        reg.create_task(title="T2", task_type="review")
        filtered = reg.list_tasks(task_type="validation")
        assert len(filtered) == 1
        assert filtered[0]["title"] == "T1"

    def test_filter_status(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        reg.create_task(title="T1", status="ready")
        reg.create_task(title="T2", status="blocked")
        filtered = reg.list_tasks(status="ready")
        assert len(filtered) == 1
        assert filtered[0]["title"] == "T1"

    def test_filter_parent(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        parent = reg.create_task(title="Parent")
        reg.create_task(title="Child", parent_task_id=parent["task_id"])
        reg.create_task(title="Other")
        filtered = reg.list_tasks(parent_task_id=parent["task_id"])
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Child"


# ---------------------------------------------------------------------------
# Dependency tests
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_add_dependency(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="Source")
        t2 = reg.create_task(title="Target")
        dep = reg.add_dependency(
            t1["task_id"], t2["task_id"],
            dependency_type="requires",
        )
        assert dep["source_task_id"] == t1["task_id"]
        assert dep["target_task_id"] == t2["task_id"]
        assert dep["dependency_type"] == "requires"

    def test_get_dependencies(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="Source")
        t2 = reg.create_task(title="Target")
        reg.add_dependency(t1["task_id"], t2["task_id"])
        deps = reg.get_dependencies(t1["task_id"])
        assert len(deps) == 1

    def test_self_dependency_rejected(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t = reg.create_task(title="Self")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            reg.add_dependency(t["task_id"], t["task_id"])

    def test_invalid_dependency_type(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="A")
        t2 = reg.create_task(title="B")
        with pytest.raises(ValueError, match="Invalid dependency_type"):
            reg.add_dependency(t1["task_id"], t2["task_id"], "nonexistent")

    def test_source_not_found(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t = reg.create_task(title="Target")
        with pytest.raises(ValueError, match="Source task not found"):
            reg.add_dependency("nonexistent", t["task_id"])

    def test_target_not_found(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t = reg.create_task(title="Source")
        with pytest.raises(ValueError, match="Target task not found"):
            reg.add_dependency(t["task_id"], "nonexistent")


# ---------------------------------------------------------------------------
# Cycle detection tests
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="A")
        t2 = reg.create_task(title="B")
        reg.add_dependency(t1["task_id"], t2["task_id"], "requires")
        with pytest.raises(ValueError, match="would create a cycle"):
            reg.add_dependency(t2["task_id"], t1["task_id"], "requires")

    def test_indirect_cycle(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="A")
        t2 = reg.create_task(title="B")
        t3 = reg.create_task(title="C")
        reg.add_dependency(t1["task_id"], t2["task_id"], "requires")
        reg.add_dependency(t2["task_id"], t3["task_id"], "requires")
        with pytest.raises(ValueError, match="would create a cycle"):
            reg.add_dependency(t3["task_id"], t1["task_id"], "requires")

    def test_no_cycle_valid_dag(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="A")
        t2 = reg.create_task(title="B")
        t3 = reg.create_task(title="C")
        reg.add_dependency(t1["task_id"], t2["task_id"], "requires")
        reg.add_dependency(t1["task_id"], t3["task_id"], "requires")
        deps = reg.get_dependencies(t1["task_id"])
        assert len(deps) == 2

    def test_has_cycle_static(self) -> None:
        deps = [
            {"source_task_id": "a", "target_task_id": "b"},
            {"source_task_id": "b", "target_task_id": "c"},
            {"source_task_id": "c", "target_task_id": "a"},
        ]
        assert SessionTaskGraphRegistry._has_cycle(deps) is True

    def test_no_cycle_static(self) -> None:
        deps = [
            {"source_task_id": "a", "target_task_id": "b"},
            {"source_task_id": "b", "target_task_id": "c"},
        ]
        assert SessionTaskGraphRegistry._has_cycle(deps) is False


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportTask:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(
            title="Export test",
            description="Testing export",
            task_type="validation",
        )
        md = reg.export_task(task["task_id"])
        assert "# Task: Export test" in md
        assert "validation" in md
        assert "Testing export" in md

    def test_export_with_dependencies(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        t1 = reg.create_task(title="Source")
        t2 = reg.create_task(title="Target")
        reg.add_dependency(t1["task_id"], t2["task_id"], "requires")
        md = reg.export_task(t1["task_id"])
        assert "## Dependencies" in md
        assert "requires" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_task("nope")


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="Evidence task")
        evidence_dir = reg.write_evidence(task["task_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "session_task_request.json").exists()
        assert (ev_path / "session_task_result.json").exists()
        assert (ev_path / "session_task_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_valid_json(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="JSON task")
        evidence_dir = reg.write_evidence(task["task_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "session_task_request.json",
            "session_task_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_created(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="T1")
        evidence_dir = reg.write_evidence(task["task_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False
        assert pf["is_terminal"] is False

    def test_pass_fail_completed(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="T1", status="completed")
        evidence_dir = reg.write_evidence(task["task_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is True
        assert pf["is_terminal"] is True

    def test_pass_fail_failed(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        task = reg.create_task(title="T1", status="failed")
        evidence_dir = reg.write_evidence(task["task_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False
        assert pf["is_terminal"] is True

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_task("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_task("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_task("../etc/passwd")

    def test_symlink_traversal_blocked(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        tasks_dir = tmp_path / "session_tasks"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = tasks_dir / "evil-link"
        symlink.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            reg._safe_task_path("evil-link")

    def test_symlink_skipped_in_list(self, tmp_path: Path) -> None:
        reg = SessionTaskGraphRegistry(artifacts_root=str(tmp_path))
        reg.create_task(title="Real")
        outside = tmp_path / "outside"
        outside.mkdir()
        fake_json = outside / "task.json"
        fake_json.write_text('{"title":"Evil","status":"created","task_type":"other"}')
        tasks_dir = tmp_path / "session_tasks"
        symlink = tasks_dir / "evil-link"
        symlink.symlink_to(outside)
        results = reg.list_tasks()
        titles = [t["title"] for t in results]
        assert "Real" in titles
        assert "Evil" not in titles


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_task_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "session-task-create",
            "session-tasks",
            "session-task-show",
            "session-task-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_task_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("session-task-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "session_task_request.json" in locations
        assert "session_task_result.json" in locations
        assert "session_task_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/session_task_graph.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_session_task_graph.py"
