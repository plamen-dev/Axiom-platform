"""Tests for Configuration Dependency Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.config_dependency import (
    ConfigurationDependency,
    ConfigurationDependencyEngine,
    ConfigurationDependencyGraph,
    ConfigurationDependencyReport,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_dependency_auto_id(self):
        d = ConfigurationDependency(source_id="a", target_id="b")
        assert d.dependency_id
        assert d.source_id == "a"
        assert d.target_id == "b"
        assert d.created_at

    def test_graph_auto_id(self):
        g = ConfigurationDependencyGraph(node_count=3, edge_count=2)
        assert g.graph_id
        assert g.node_count == 3

    def test_report_auto_id(self):
        r = ConfigurationDependencyReport(graph_id="g1")
        assert r.report_id
        assert r.graph_id == "g1"

    def test_dependency_to_dict(self):
        d = ConfigurationDependency(
            source_id="a",
            target_id="b",
            dependency_type="requires",
            status="active",
            rationale="A needs B",
        )
        dd = d.to_dict()
        assert dd["source_id"] == "a"
        assert dd["target_id"] == "b"
        assert dd["rationale"] == "A needs B"

    def test_graph_to_dict(self):
        dep = ConfigurationDependency(source_id="a", target_id="b")
        g = ConfigurationDependencyGraph(dependencies=[dep], node_count=2, edge_count=1)
        gd = g.to_dict()
        assert gd["node_count"] == 2
        assert len(gd["dependencies"]) == 1


# ---------------------------------------------------------------------------
# Engine - basic creation
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_dependencies(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(dependencies=[])
        assert report["blocked_count"] == 0
        assert report["invalid_count"] == 0
        graph = report["graph"]
        assert graph["node_count"] == 0
        assert graph["edge_count"] == 0

    def test_simple_requires(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            {"source_id": "B", "target_id": "C", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps)
        graph = report["graph"]
        assert graph["node_count"] == 3
        assert graph["edge_count"] == 2
        assert report["blocked_count"] == 0

    def test_all_dependency_types(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            {"source_id": "C", "target_id": "D", "dependency_type": "blocks"},
            {"source_id": "E", "target_id": "F", "dependency_type": "related_to"},
            {"source_id": "G", "target_id": "H", "dependency_type": "supersedes"},
        ]
        report = engine.create(dependencies=deps)
        graph = report["graph"]
        assert graph["node_count"] == 8
        assert graph["edge_count"] == 4


# ---------------------------------------------------------------------------
# Engine - cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_simple_cycle(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            {"source_id": "B", "target_id": "C", "dependency_type": "requires"},
            {"source_id": "C", "target_id": "A", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps)
        assert report["blocked_count"] == 3

    def test_self_cycle(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "A", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps)
        assert report["blocked_count"] == 1

    def test_no_cycle(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            {"source_id": "B", "target_id": "C", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps)
        assert report["blocked_count"] == 0

    def test_related_to_does_not_form_cycle(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "related_to"},
            {"source_id": "B", "target_id": "A", "dependency_type": "related_to"},
        ]
        report = engine.create(dependencies=deps)
        assert report["blocked_count"] == 0


# ---------------------------------------------------------------------------
# Engine - unknown ID handling
# ---------------------------------------------------------------------------


class TestUnknownIdHandling:
    def test_unknown_source_marked_invalid(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "unknown", "target_id": "B", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps, known_ids=["B", "C"])
        assert report["invalid_count"] == 1

    def test_unknown_target_marked_invalid(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "unknown", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps, known_ids=["A", "B"])
        assert report["invalid_count"] == 1

    def test_known_ids_not_invalid(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps, known_ids=["A", "B"])
        assert report["invalid_count"] == 0

    def test_no_known_ids_skips_validation(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "X", "target_id": "Y", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps, known_ids=None)
        assert report["invalid_count"] == 0


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_dependencies_sorted_by_source_target(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        deps = [
            {"source_id": "Z", "target_id": "A", "dependency_type": "requires"},
            {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            {"source_id": "M", "target_id": "N", "dependency_type": "requires"},
        ]
        report = engine.create(dependencies=deps)
        result_deps = report["graph"]["dependencies"]
        sources = [d["source_id"] for d in result_deps]
        assert sources == sorted(sources)


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            dependencies=[
                {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            ]
        )
        report_id = report["report_id"]

        evidence_dir = tmp_path / "config_dependencies" / report_id
        assert (evidence_dir / "config_dependency_request.json").exists()
        assert (evidence_dir / "config_dependency_result.json").exists()
        assert (evidence_dir / "config_dependency_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_no_issues(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            dependencies=[
                {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            ]
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "config_dependencies" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True

    def test_pass_fail_false_when_blocked(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            dependencies=[
                {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
                {"source_id": "B", "target_id": "A", "dependency_type": "requires"},
            ]
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "config_dependencies" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_pass_fail_false_when_invalid(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            dependencies=[
                {"source_id": "X", "target_id": "B", "dependency_type": "requires"},
            ],
            known_ids=["B"],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "config_dependencies" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(dependencies=[])
        report_id = report["report_id"]

        md = (
            tmp_path / "config_dependencies" / report_id / "config_dependency_summary.md"
        ).read_text()
        assert "# Configuration Dependency Report" in md


# ---------------------------------------------------------------------------
# Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(dependencies=[])
        report_id = report["report_id"]

        loaded = engine.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id

    def test_list_reports(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        engine.create(dependencies=[])
        engine.create(
            dependencies=[
                {"source_id": "A", "target_id": "B", "dependency_type": "requires"},
            ]
        )

        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        report = engine.create(dependencies=[])
        report_id = report["report_id"]

        md = engine.export_report(report_id)
        assert "# Configuration Dependency Report" in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        dep_dir = tmp_path / "config_dependencies"
        dep_dir.mkdir(exist_ok=True)
        link_name = dep_dir / "evil-link"
        make_symlink_or_skip(link_name, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_dep_path("evil-link")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = ConfigurationDependencyEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# CommandRegistry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "config-dependency-create" in names
        assert "config-dependencies" in names
        assert "config-dependency-show" in names
        assert "config-dependency-export" in names


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_config_dependency_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/config_dependency.py"]
            == "tests/test_config_dependency.py"
        )
