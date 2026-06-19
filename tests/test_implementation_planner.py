"""Tests for axiom_core.implementation_planner — Implementation Plan Generator v1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

import pytest

# ---------------------------------------------------------------------------
# Lightweight fakes for WorkItem / CodeSymbolRegistry / KnowledgeGraph so
# that tests stay isolated from real DB state.
# ---------------------------------------------------------------------------


class _FakeStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class _FakeType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    CLEANUP = "cleanup"
    REFACTOR = "refactor"
    TEST = "test"
    DOCUMENTATION = "documentation"
    VALIDATION = "validation"
    INVESTIGATION = "investigation"
    REVIEW_FINDING = "review_finding"


class _FakePriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSET = "unset"


@dataclass
class _FakeWorkItem:
    item_id: str = "wi-001"
    title: str = "Add widget support"
    description: str | None = "Implement widget rendering in the dashboard"
    item_type: _FakeType = _FakeType.FEATURE
    status: _FakeStatus = _FakeStatus.APPROVED
    priority: _FakePriority = _FakePriority.MEDIUM


class _FakeWorkItemRegistry:
    def __init__(self, items: dict[str, _FakeWorkItem] | None = None) -> None:
        self._items = items or {}

    def get_item(self, item_id: str) -> _FakeWorkItem | None:
        return self._items.get(item_id)


@dataclass
class _FakeFile:
    path: str = ""
    category: str = "source"
    module_name: str | None = None


@dataclass
class _FakeSym:
    name: str = ""
    qualified_name: str = ""
    kind: str = "class"


@dataclass
class _FakeCovRef:
    test_file: str = ""
    target_module: str = ""


class _FakeCodeRegistry:
    def __init__(
        self,
        files: list[_FakeFile] | None = None,
        symbols: list[_FakeSym] | None = None,
        coverage: list[_FakeCovRef] | None = None,
    ) -> None:
        self._files = files or []
        self._symbols = symbols or []
        self._coverage = coverage or []

    def list_files(self) -> list[_FakeFile]:
        return self._files

    def list_symbols(self) -> list[_FakeSym]:
        return self._symbols

    def list_test_coverage(self) -> list[_FakeCovRef]:
        return self._coverage


@dataclass
class _FakeNode:
    label: str = ""


class _FakeKnowledgeGraph:
    def __init__(self, nodes: list[_FakeNode] | None = None) -> None:
        self._nodes = nodes or []

    def list_nodes(self) -> list[_FakeNode]:
        return self._nodes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db_path)
    return db_path


@pytest.fixture()
def planner(tmp_db):
    from axiom_core.implementation_planner import ImplementationPlanner

    return ImplementationPlanner(db_path=tmp_db)


@pytest.fixture()
def approved_item():
    return _FakeWorkItem(
        item_id="wi-001",
        title="Add widget support",
        description="Implement widget rendering in the dashboard",
        item_type=_FakeType.FEATURE,
        status=_FakeStatus.APPROVED,
    )


@pytest.fixture()
def work_items(approved_item):
    return _FakeWorkItemRegistry({"wi-001": approved_item})


@pytest.fixture()
def code_registry():
    return _FakeCodeRegistry(
        files=[
            _FakeFile(path="src/axiom_core/widget.py", module_name="axiom_core.widget"),
            _FakeFile(path="src/axiom_core/dashboard.py", module_name="axiom_core.dashboard"),
            _FakeFile(path="src/axiom_cli/main.py", module_name="axiom_cli.main"),
            _FakeFile(path="tests/test_widget.py", module_name="tests.test_widget"),
        ],
        symbols=[
            _FakeSym(name="WidgetRenderer", qualified_name="axiom_core.widget.WidgetRenderer", kind="class"),
            _FakeSym(name="render_dashboard", qualified_name="axiom_core.dashboard.render_dashboard", kind="function"),
            _FakeSym(name="DashboardLayout", qualified_name="axiom_core.dashboard.DashboardLayout", kind="class"),
        ],
        coverage=[
            _FakeCovRef(test_file="tests/test_widget.py", target_module="axiom_core.widget"),
        ],
    )


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_change_type_values(self):
        from axiom_core.implementation_planner import ChangeType

        assert ChangeType.ADD.value == "add"
        assert ChangeType.MODIFY.value == "modify"
        assert ChangeType.DELETE.value == "delete"

    def test_risk_level_values(self):
        from axiom_core.implementation_planner import RiskLevel

        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"

    def test_plan_status_values(self):
        from axiom_core.implementation_planner import PlanStatus

        assert PlanStatus.DRAFT.value == "draft"
        assert PlanStatus.READY.value == "ready"
        assert PlanStatus.SUPERSEDED.value == "superseded"


# ---------------------------------------------------------------------------
# TestDataModels
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_file_change_intent_roundtrip(self):
        from axiom_core.implementation_planner import ChangeType, FileChangeIntent

        fc = FileChangeIntent(
            file_path="src/foo.py",
            change_type=ChangeType.MODIFY,
            description="Fix bug",
            related_symbols=["Foo.bar"],
        )
        d = fc.to_dict()
        assert d["file_path"] == "src/foo.py"
        assert d["change_type"] == "modify"
        fc2 = FileChangeIntent.from_dict(d)
        assert fc2.file_path == fc.file_path
        assert fc2.change_type == fc.change_type

    def test_implementation_step_roundtrip(self):
        from axiom_core.implementation_planner import ImplementationStep

        step = ImplementationStep(
            step_number=1,
            description="Add module",
            target_files=["src/foo.py"],
            verification="ruff check src/foo.py",
        )
        d = step.to_dict()
        assert d["step_number"] == 1
        step2 = ImplementationStep.from_dict(d)
        assert step2.description == step.description

    def test_test_plan_roundtrip(self):
        from axiom_core.implementation_planner import TestPlan

        tp = TestPlan(
            test_files=["tests/test_foo.py"],
            new_tests_needed=["tests/test_bar.py"],
            regression_commands=["poetry run pytest"],
        )
        d = tp.to_dict()
        assert d["test_files"] == ["tests/test_foo.py"]
        tp2 = TestPlan.from_dict(d)
        assert tp2.test_files == tp.test_files

    def test_risk_note_roundtrip(self):
        from axiom_core.implementation_planner import RiskLevel, RiskNote

        r = RiskNote(description="Big change", level=RiskLevel.HIGH, mitigation="Split PR")
        d = r.to_dict()
        assert d["level"] == "high"
        r2 = RiskNote.from_dict(d)
        assert r2.level == RiskLevel.HIGH

    def test_implementation_plan_to_dict(self):
        from axiom_core.implementation_planner import (
            ImplementationPlan,
            ImplementationStep,
        )

        plan = ImplementationPlan(
            work_item_id="wi-001",
            title="Test Plan",
            summary="A summary",
            steps=[ImplementationStep(step_number=1, description="Do thing")],
            non_goals=["No autonomous execution"],
        )
        d = plan.to_dict()
        assert d["work_item_id"] == "wi-001"
        assert d["status"] == "draft"
        assert len(d["steps"]) == 1
        assert d["non_goals"] == ["No autonomous execution"]
        parsed = json.loads(json.dumps(d, default=str))
        assert parsed["title"] == "Test Plan"


# ---------------------------------------------------------------------------
# TestPlanner
# ---------------------------------------------------------------------------


class TestPlanner:
    def test_generate_approved_item(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        assert plan.work_item_id == "wi-001"
        assert "widget" in plan.title.lower() or "Widget" in plan.title
        assert plan.status.value == "draft"
        assert len(plan.steps) >= 1
        assert len(plan.file_changes) >= 1
        assert plan.test_plan is not None

    def test_generate_unknown_item_raises(self, planner, code_registry):
        empty_reg = _FakeWorkItemRegistry({})
        with pytest.raises(ValueError, match="not found"):
            planner.generate(
                work_item_id="wi-999",
                work_item_registry=empty_reg,
                code_registry=code_registry,
            )

    def test_generate_proposed_item_raises(self, planner, code_registry):
        item = _FakeWorkItem(status=_FakeStatus.PROPOSED)
        reg = _FakeWorkItemRegistry({"wi-001": item})
        with pytest.raises(ValueError, match="status"):
            planner.generate(
                work_item_id="wi-001",
                work_item_registry=reg,
                code_registry=code_registry,
            )

    def test_generate_completed_item_raises(self, planner, code_registry):
        item = _FakeWorkItem(status=_FakeStatus.COMPLETED)
        reg = _FakeWorkItemRegistry({"wi-001": item})
        with pytest.raises(ValueError, match="status"):
            planner.generate(
                work_item_id="wi-001",
                work_item_registry=reg,
                code_registry=code_registry,
            )

    def test_generate_in_progress_item_succeeds(self, planner, work_items, code_registry):
        item = _FakeWorkItem(status=_FakeStatus.IN_PROGRESS)
        reg = _FakeWorkItemRegistry({"wi-001": item})
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=reg,
            code_registry=code_registry,
        )
        assert plan.work_item_id == "wi-001"

    def test_file_changes_match_target_files(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        fc_paths = {fc.file_path for fc in plan.file_changes}
        for fc in plan.file_changes:
            assert fc.file_path in fc_paths

    def test_feature_item_gets_add_change_type(self, planner, work_items, code_registry):
        from axiom_core.implementation_planner import ChangeType

        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        if plan.file_changes:
            assert plan.file_changes[0].change_type == ChangeType.ADD

    def test_bug_fix_item_gets_modify_change_type(self, planner, code_registry):
        from axiom_core.implementation_planner import ChangeType

        item = _FakeWorkItem(
            item_type=_FakeType.BUG_FIX,
            status=_FakeStatus.APPROVED,
            title="Fix widget crash",
            description="Widget crashes on null input",
        )
        reg = _FakeWorkItemRegistry({"wi-001": item})
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=reg,
            code_registry=code_registry,
        )
        if plan.file_changes:
            assert plan.file_changes[0].change_type == ChangeType.MODIFY

    def test_file_changes_link_related_symbols(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        widget_changes = [fc for fc in plan.file_changes if "widget" in fc.file_path]
        assert len(widget_changes) >= 1
        assert len(widget_changes[0].related_symbols) >= 1, (
            "related_symbols should not be empty for src/ files (src. prefix must be stripped)"
        )

    def test_test_plan_links_coverage(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        if plan.test_plan.test_files:
            assert "tests/test_widget.py" in plan.test_plan.test_files

    def test_risks_generated_for_cli_changes(self, planner, code_registry):
        item = _FakeWorkItem(
            title="Fix CLI rendering",
            description="Update axiom_cli main command output",
            status=_FakeStatus.APPROVED,
        )
        reg = _FakeWorkItemRegistry({"wi-001": item})
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=reg,
            code_registry=code_registry,
        )
        risk_descs = [r.description.lower() for r in plan.risks]
        assert any("cli" in d for d in risk_descs)

    def test_refactor_gets_high_risk(self, planner, code_registry):
        from axiom_core.implementation_planner import RiskLevel

        item = _FakeWorkItem(
            item_type=_FakeType.REFACTOR,
            status=_FakeStatus.APPROVED,
            title="Refactor widget module",
            description="Restructure widget internals",
        )
        reg = _FakeWorkItemRegistry({"wi-001": item})
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=reg,
            code_registry=code_registry,
        )
        levels = [r.level for r in plan.risks]
        assert RiskLevel.HIGH in levels

    def test_non_goals_always_present(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        assert len(plan.non_goals) >= 1
        assert any("execution" in ng.lower() for ng in plan.non_goals)

    def test_evidence_requirements_present(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        assert len(plan.evidence_requirements) >= 1

    def test_plan_is_deterministic(self, planner, work_items, code_registry):
        plan1 = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        plan2 = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        d1 = plan1.to_dict()
        d2 = plan2.to_dict()
        for key in ("title", "summary", "steps", "file_changes", "risks", "non_goals"):
            assert d1[key] == d2[key], f"Non-deterministic field: {key}"

    def test_json_output_valid(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        output = json.dumps(plan.to_dict(), indent=2, default=str)
        parsed = json.loads(output)
        assert parsed["work_item_id"] == "wi-001"


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_plan_persists_and_retrieves(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        retrieved = planner.get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id
        assert retrieved.work_item_id == "wi-001"
        assert retrieved.title == plan.title

    def test_get_plan_for_work_item(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        retrieved = planner.get_plan_for_work_item("wi-001")
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id

    def test_get_plan_unknown_returns_none(self, planner):
        assert planner.get_plan("nonexistent-id") is None

    def test_get_plan_for_unknown_work_item_returns_none(self, planner):
        assert planner.get_plan_for_work_item("nonexistent-wi") is None

    def test_list_plans(self, planner, work_items, code_registry):
        planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        plans = planner.list_plans()
        assert len(plans) >= 1

    def test_list_plans_filter_by_status(self, planner, work_items, code_registry):
        from axiom_core.implementation_planner import PlanStatus

        planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        drafts = planner.list_plans(status=PlanStatus.DRAFT)
        assert len(drafts) >= 1
        for p in drafts:
            assert p.status == PlanStatus.DRAFT

    def test_regenerate_supersedes_old_plan(self, planner, work_items, code_registry):
        from axiom_core.implementation_planner import PlanStatus

        plan1 = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        plan2 = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        old = planner.get_plan(plan1.plan_id)
        assert old is not None
        assert old.status == PlanStatus.SUPERSEDED
        new = planner.get_plan(plan2.plan_id)
        assert new is not None
        assert new.status == PlanStatus.DRAFT

    def test_get_plan_for_work_item_skips_superseded(self, planner, work_items, code_registry):
        from axiom_core.implementation_planner import PlanStatus

        planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        plan2 = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        result = planner.get_plan_for_work_item("wi-001")
        assert result is not None
        assert result.plan_id == plan2.plan_id
        assert result.status != PlanStatus.SUPERSEDED

    def test_from_row_roundtrip(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
        )
        retrieved = planner.get_plan(plan.plan_id)
        assert retrieved is not None
        d_orig = plan.to_dict()
        d_retr = retrieved.to_dict()
        for key in ("work_item_id", "title", "summary", "status", "steps",
                     "file_changes", "non_goals"):
            assert d_orig[key] == d_retr[key], f"Roundtrip mismatch: {key}"


# ---------------------------------------------------------------------------
# TestKnowledgeIntegration
# ---------------------------------------------------------------------------


class TestKnowledgeIntegration:
    def test_knowledge_graph_nodes_linked(self, planner, work_items, code_registry):
        kg = _FakeKnowledgeGraph(nodes=[
            _FakeNode(label="Widget rendering architecture"),
            _FakeNode(label="Dashboard layout rules"),
            _FakeNode(label="Unrelated concept"),
        ])
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
            knowledge_graph=kg,
        )
        assert len(plan.related_knowledge) >= 1
        labels_lower = [k.lower() for k in plan.related_knowledge]
        assert any("widget" in lbl for lbl in labels_lower)

    def test_knowledge_graph_none_is_safe(self, planner, work_items, code_registry):
        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
            knowledge_graph=None,
        )
        assert plan.related_knowledge == []

    def test_knowledge_graph_error_is_safe(self, planner, work_items, code_registry):
        class _BrokenGraph:
            def list_nodes(self):
                raise RuntimeError("graph unavailable")

        plan = planner.generate(
            work_item_id="wi-001",
            work_item_registry=work_items,
            code_registry=code_registry,
            knowledge_graph=_BrokenGraph(),
        )
        assert plan.related_knowledge == []


# ---------------------------------------------------------------------------
# TestKeywordExtraction
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_extracts_meaningful_words(self):
        from axiom_core.implementation_planner import ImplementationPlanner

        item = _FakeWorkItem(title="Fix widget crash", description="The widget crashes on null")
        keywords = ImplementationPlanner._extract_keywords(item)
        assert "fix" in keywords
        assert "widget" in keywords
        assert "crash" in keywords
        assert "the" not in keywords

    def test_empty_description_safe(self):
        from axiom_core.implementation_planner import ImplementationPlanner

        item = _FakeWorkItem(title="Simple task", description=None)
        keywords = ImplementationPlanner._extract_keywords(item)
        assert "simple" in keywords
        assert "task" in keywords

    def test_stop_words_removed(self):
        from axiom_core.implementation_planner import ImplementationPlanner

        item = _FakeWorkItem(title="the and or is a", description="")
        keywords = ImplementationPlanner._extract_keywords(item)
        assert len(keywords) == 0
