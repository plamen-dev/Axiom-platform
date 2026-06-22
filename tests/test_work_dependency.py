"""Tests for the Work Item Dependency Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.work_dependency import (
    WorkDependency,
    WorkDependencyEngine,
    WorkDependencyGraph,
    WorkDependencyReport,
    WorkDependencyStatus,
    WorkDependencyType,
    detect_cycle,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> WorkDependencyEngine:
    return WorkDependencyEngine(artifacts_root=str(tmp_path))


def _sample_deps() -> list[dict]:
    return [
        {
            "source_work_id": "w2",
            "target_work_id": "w3",
            "dependency_type": "blocks",
            "status": "active",
        },
        {
            "source_work_id": "w1",
            "target_work_id": "w2",
            "dependency_type": "requires",
            "status": "active",
            "rationale": "w1 needs w2",
        },
        {
            "source_work_id": "w1",
            "target_work_id": "w4",
            "dependency_type": "related_to",
            "status": "blocked",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_dependency_defaults(self) -> None:
        d = WorkDependency()
        assert d.dependency_id
        assert d.created_at
        assert d.dependency_type == "requires"
        assert d.status == "active"

    def test_graph_defaults(self) -> None:
        g = WorkDependencyGraph()
        assert g.graph_id
        assert g.created_at
        assert g.dependencies == []
        assert g.node_count == 0
        assert g.edge_count == 0

    def test_report_defaults(self) -> None:
        r = WorkDependencyReport()
        assert r.report_id
        assert r.created_at
        assert r.blocked_count == 0
        assert r.invalid_count == 0


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=[])
        assert result["graph"]["edge_count"] == 0
        assert result["graph"]["node_count"] == 0

    def test_create_with_deps(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        assert result["graph"]["edge_count"] == 3
        # nodes: w1, w2, w3, w4
        assert result["graph"]["node_count"] == 4

    def test_all_types(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {
                "source_work_id": f"s{t.value}",
                "target_work_id": f"t{t.value}",
                "dependency_type": t.value,
            }
            for t in WorkDependencyType
        ]
        result = engine.create(dependencies=deps)
        assert result["graph"]["edge_count"] == len(WorkDependencyType)

    def test_all_statuses(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {
                "source_work_id": f"s{s.value}",
                "target_work_id": f"t{s.value}",
                "dependency_type": "related_to",
                "status": s.value,
            }
            for s in WorkDependencyStatus
        ]
        result = engine.create(dependencies=deps)
        assert result["graph"]["edge_count"] == len(WorkDependencyStatus)


# ---------------------------------------------------------------------------
# TestStatusPersistence
# ---------------------------------------------------------------------------


class TestStatusPersistence:
    def test_status_persisted(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        by_pair = {
            (d["source_work_id"], d["target_work_id"]): d
            for d in result["graph"]["dependencies"]
        }
        assert by_pair[("w1", "w4")]["status"] == "blocked"
        assert by_pair[("w1", "w2")]["status"] == "active"

    def test_blocked_count(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        assert result["blocked_count"] == 1

    def test_rationale_persisted(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        by_pair = {
            (d["source_work_id"], d["target_work_id"]): d
            for d in result["graph"]["dependencies"]
        }
        assert by_pair[("w1", "w2")]["rationale"] == "w1 needs w2"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError, match="Invalid dependency_type"):
            engine.create(
                dependencies=[
                    {"source_work_id": "a", "target_work_id": "b", "dependency_type": "implies"}
                ]
            )

    def test_invalid_status_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                dependencies=[
                    {"source_work_id": "a", "target_work_id": "b", "status": "pending"}
                ]
            )

    def test_missing_endpoints_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError, match="required"):
            engine.create(dependencies=[{"source_work_id": "a"}])


# ---------------------------------------------------------------------------
# TestCycleDetection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_no_cycle_acyclic(self) -> None:
        deps = [
            WorkDependency(source_work_id="a", target_work_id="b", dependency_type="requires"),
            WorkDependency(source_work_id="b", target_work_id="c", dependency_type="requires"),
        ]
        assert detect_cycle(deps) == []

    def test_detect_simple_cycle(self) -> None:
        deps = [
            WorkDependency(source_work_id="a", target_work_id="b", dependency_type="requires"),
            WorkDependency(source_work_id="b", target_work_id="a", dependency_type="requires"),
        ]
        cycle = detect_cycle(deps)
        assert cycle
        assert "a" in cycle and "b" in cycle

    def test_related_to_does_not_form_cycle(self) -> None:
        deps = [
            WorkDependency(source_work_id="a", target_work_id="b", dependency_type="related_to"),
            WorkDependency(source_work_id="b", target_work_id="a", dependency_type="related_to"),
        ]
        assert detect_cycle(deps) == []

    def test_cycle_marks_invalid(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {"source_work_id": "a", "target_work_id": "b", "dependency_type": "requires"},
            {"source_work_id": "b", "target_work_id": "a", "dependency_type": "requires"},
        ]
        result = engine.create(dependencies=deps)
        assert result["has_cycle"] is True
        assert result["invalid_count"] == 2
        assert all(d["status"] == "invalid" for d in result["graph"]["dependencies"])

    def test_multiple_independent_cycles_all_invalid(
        self, engine: WorkDependencyEngine
    ) -> None:
        deps = [
            {"source_work_id": "a", "target_work_id": "b", "dependency_type": "requires"},
            {"source_work_id": "b", "target_work_id": "a", "dependency_type": "requires"},
            {"source_work_id": "c", "target_work_id": "d", "dependency_type": "blocks"},
            {"source_work_id": "d", "target_work_id": "c", "dependency_type": "blocks"},
        ]
        result = engine.create(dependencies=deps)
        assert result["has_cycle"] is True
        # All four edges participate in a cycle, not just the first cycle's two.
        assert result["invalid_count"] == 4
        assert all(d["status"] == "invalid" for d in result["graph"]["dependencies"])

    def test_self_loop_marked_invalid(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {"source_work_id": "a", "target_work_id": "a", "dependency_type": "requires"},
        ]
        result = engine.create(dependencies=deps)
        assert result["has_cycle"] is True
        assert result["invalid_count"] == 1

    def test_deterministic_cycle(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {"source_work_id": "b", "target_work_id": "c", "dependency_type": "requires"},
            {"source_work_id": "c", "target_work_id": "a", "dependency_type": "requires"},
            {"source_work_id": "a", "target_work_id": "b", "dependency_type": "requires"},
        ]
        r1 = engine.create(dependencies=deps)
        r2 = engine.create(dependencies=list(reversed(deps)))
        assert r1["cycle"] == r2["cycle"]


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_deps_ordered(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        pairs = [
            (d["source_work_id"], d["target_work_id"])
            for d in result["graph"]["dependencies"]
        ]
        assert pairs == sorted(pairs)

    def test_order_independent(self, engine: WorkDependencyEngine) -> None:
        r1 = engine.create(dependencies=_sample_deps())
        r2 = engine.create(dependencies=list(reversed(_sample_deps())))
        pairs1 = [
            (d["source_work_id"], d["target_work_id"], d["dependency_type"])
            for d in r1["graph"]["dependencies"]
        ]
        pairs2 = [
            (d["source_work_id"], d["target_work_id"], d["dependency_type"])
            for d in r2["graph"]["dependencies"]
        ]
        assert pairs1 == pairs2


# ---------------------------------------------------------------------------
# TestSourceReferences
# ---------------------------------------------------------------------------


class TestSourceReferences:
    def test_work_ids_preserved(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        pairs = {
            (d["source_work_id"], d["target_work_id"])
            for d in result["graph"]["dependencies"]
        }
        assert ("w1", "w2") in pairs
        assert ("w2", "w3") in pairs
        assert ("w1", "w4") in pairs


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "work_dependency_request.json",
            "work_dependency_result.json",
            "work_dependency_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "work_dependency_request.json").read_text())
        assert len(data["dependencies"]) == 3

    def test_summary_has_header(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "work_dependency_summary.md").read_text()
        assert "# Work Dependency Report" in md
        assert "## Graph" in md
        assert "## Dependencies" in md

    def test_pass_fail_passes_acyclic(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {"source_work_id": "a", "target_work_id": "b", "dependency_type": "requires"},
        ]
        result = engine.create(dependencies=deps)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_fails_on_cycle(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {"source_work_id": "a", "target_work_id": "b", "dependency_type": "requires"},
            {"source_work_id": "b", "target_work_id": "a", "dependency_type": "requires"},
        ]
        result = engine.create(dependencies=deps)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["has_cycle"] is True

    def test_pass_fail_fails_on_invalid(self, engine: WorkDependencyEngine) -> None:
        deps = [
            {
                "source_work_id": "a",
                "target_work_id": "b",
                "dependency_type": "related_to",
                "status": "invalid",
            },
        ]
        result = engine.create(dependencies=deps)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_pass_fail_empty_passes(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=[])
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["graph"]["edge_count"] == 3

    def test_list_reports_deterministic(self, engine: WorkDependencyEngine) -> None:
        engine.create(dependencies=_sample_deps())
        engine.create(dependencies=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: WorkDependencyEngine) -> None:
        result = engine.create(dependencies=_sample_deps())
        md = engine.export_report(result["report_id"])
        assert "# Work Dependency Report" in md
        assert "REQUIRES" in md

    def test_export_nonexistent_raises(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: WorkDependencyEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: WorkDependencyEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: WorkDependencyEngine) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {
            "work-dependency-create",
            "work-dependency-show",
            "work-dependency-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_work_dependency_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/work_dependency.py"]
            == "tests/test_work_dependency.py"
        )
