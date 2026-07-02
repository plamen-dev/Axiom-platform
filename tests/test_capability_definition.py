"""Tests for Capability Definition Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_definition import (
    CapabilityDefinition,
    CapabilityDefinitionEngine,
    CapabilityDefinitionReport,
    CapabilityRegistry,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_capability_auto_id(self):
        c = CapabilityDefinition(name="test-cap")
        assert c.capability_id
        assert c.name == "test-cap"
        assert c.created_at

    def test_registry_auto_id(self):
        r = CapabilityRegistry(capability_count=3)
        assert r.registry_id
        assert r.capability_count == 3

    def test_report_auto_id(self):
        rpt = CapabilityDefinitionReport(registry_id="r1")
        assert rpt.report_id
        assert rpt.registry_id == "r1"

    def test_capability_to_dict(self):
        c = CapabilityDefinition(
            name="validate-config",
            description="Validates configurations",
            capability_type="validation",
            status="active",
            dependency_ids=["dep-1", "dep-2"],
        )
        cd = c.to_dict()
        assert cd["name"] == "validate-config"
        assert cd["dependency_ids"] == ["dep-1", "dep-2"]

    def test_registry_to_dict(self):
        cap = CapabilityDefinition(name="cap1")
        reg = CapabilityRegistry(capabilities=[cap], capability_count=1)
        rd = reg.to_dict()
        assert rd["capability_count"] == 1
        assert len(rd["capabilities"]) == 1

    def test_report_to_dict(self):
        rpt = CapabilityDefinitionReport(registry_id="r1", active_count=2, disabled_count=1)
        rd = rpt.to_dict()
        assert rd["active_count"] == 2
        assert rd["disabled_count"] == 1


# ---------------------------------------------------------------------------
# Engine - basic creation
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_capabilities(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(capabilities=[])
        assert report["active_count"] == 0
        assert report["disabled_count"] == 0
        registry = report["registry"]
        assert registry["capability_count"] == 0

    def test_single_active_capability(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [{"name": "cap1", "capability_type": "validation", "status": "active"}]
        report = engine.create(capabilities=caps)
        assert report["active_count"] == 1
        assert report["registry"]["capability_count"] == 1

    def test_all_capability_types(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": f"cap-{t}", "capability_type": t}
            for t in ["validation", "repair", "explanation", "execution", "reporting", "analysis"]
        ]
        report = engine.create(capabilities=caps)
        assert report["registry"]["capability_count"] == 6
        assert report["active_count"] == 6

    def test_all_statuses(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "cap-active", "status": "active"},
            {"name": "cap-disabled", "status": "disabled"},
            {"name": "cap-experimental", "status": "experimental"},
            {"name": "cap-deprecated", "status": "deprecated"},
        ]
        report = engine.create(capabilities=caps)
        assert report["active_count"] == 1
        assert report["disabled_count"] == 1
        assert report["experimental_count"] == 1
        assert report["deprecated_count"] == 1


# ---------------------------------------------------------------------------
# Engine - dependency validation
# ---------------------------------------------------------------------------


class TestDependencyValidation:
    def test_unknown_dep_disables_capability(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "cap1", "dependency_ids": ["unknown-dep"], "status": "active"},
        ]
        report = engine.create(capabilities=caps, known_dependency_ids=["dep-1"])
        assert report["disabled_count"] == 1
        assert report["active_count"] == 0

    def test_known_dep_keeps_active(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "cap1", "dependency_ids": ["dep-1"], "status": "active"},
        ]
        report = engine.create(capabilities=caps, known_dependency_ids=["dep-1"])
        assert report["active_count"] == 1
        assert report["disabled_count"] == 0

    def test_no_known_deps_skips_validation(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "cap1", "dependency_ids": ["any-dep"], "status": "active"},
        ]
        report = engine.create(capabilities=caps, known_dependency_ids=None)
        assert report["active_count"] == 1

    def test_empty_known_deps_disables_all_with_refs(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "cap1", "dependency_ids": ["dep-1"], "status": "active"},
        ]
        report = engine.create(capabilities=caps, known_dependency_ids=[])
        assert report["disabled_count"] == 1


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_capabilities_sorted_by_name(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        caps = [
            {"name": "zeta-cap"},
            {"name": "alpha-cap"},
            {"name": "middle-cap"},
        ]
        report = engine.create(capabilities=caps)
        names = [c["name"] for c in report["registry"]["capabilities"]]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capabilities=[
                {"name": "cap1", "capability_type": "validation"},
            ]
        )
        report_id = report["report_id"]

        evidence_dir = tmp_path / "capabilities" / report_id
        assert (evidence_dir / "capability_request.json").exists()
        assert (evidence_dir / "capability_result.json").exists()
        assert (evidence_dir / "capability_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_no_disabled(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capabilities=[
                {"name": "cap1", "status": "active"},
            ]
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capabilities" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_false_when_disabled(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capabilities=[
                {"name": "cap1", "status": "disabled"},
            ]
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capabilities" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(capabilities=[])
        report_id = report["report_id"]

        md = (tmp_path / "capabilities" / report_id / "capability_summary.md").read_text()
        assert "# Capability Definition Report" in md


# ---------------------------------------------------------------------------
# Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(capabilities=[])
        report_id = report["report_id"]

        loaded = engine.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id

    def test_list_reports(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        engine.create(capabilities=[])
        engine.create(capabilities=[{"name": "cap1"}])

        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        report = engine.create(capabilities=[])
        report_id = report["report_id"]

        md = engine.export_report(report_id)
        assert "# Capability Definition Report" in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        cap_dir = tmp_path / "capabilities"
        cap_dir.mkdir(exist_ok=True)
        link_name = cap_dir / "evil-link"
        make_symlink_or_skip(link_name, "/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_cap_path("evil-link")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = CapabilityDefinitionEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# CommandRegistry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "capability-create" in names
        assert "capabilities" in names
        assert "capability-show" in names
        assert "capability-export" in names


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_definition_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_definition.py"]
            == "tests/test_capability_definition.py"
        )
