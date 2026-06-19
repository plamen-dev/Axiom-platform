"""Tests for TestSelectionEngine v1 (PR #66)."""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def tmp_env(tmp_path):
    """Set up temporary environment."""
    db_path = str(tmp_path / "test.db")
    artifacts = str(tmp_path / "artifacts")
    os.environ["AXIOM_DB_PATH"] = db_path
    os.environ["AXIOM_ARTIFACTS_ROOT"] = artifacts
    yield {"db_path": db_path, "artifacts": artifacts}
    os.environ.pop("AXIOM_DB_PATH", None)
    os.environ.pop("AXIOM_ARTIFACTS_ROOT", None)


@pytest.fixture()
def engine(tmp_env):
    """Provide a TestSelectionEngine."""
    from axiom_core.test_selection_engine import TestSelectionEngine

    return TestSelectionEngine(
        db_path=tmp_env["db_path"],
        artifacts_root=tmp_env["artifacts"],
    )


# ---------------------------------------------------------------------------
# Test: Direct file mapping
# ---------------------------------------------------------------------------


class TestDirectMapping:
    """Test direct file → test mapping."""

    def test_known_source_file(self, engine):
        """Known source file maps to its test."""
        plan = engine.select_from_files(
            ["src/axiom_core/knowledge_graph.py"],
        )
        assert plan.strategy == "targeted"
        assert len(plan.selected_tests) == 1
        assert plan.selected_tests[0].test_path == "tests/test_knowledge_graph.py"
        assert plan.selected_tests[0].reason == "direct_mapping"

    def test_multiple_files(self, engine):
        """Multiple files map to their respective tests."""
        plan = engine.select_from_files([
            "src/axiom_core/knowledge_graph.py",
            "src/axiom_core/patch_proposal.py",
        ])
        assert plan.strategy == "targeted"
        paths = {t.test_path for t in plan.selected_tests}
        assert "tests/test_knowledge_graph.py" in paths
        assert "tests/test_patch_proposal.py" in paths

    def test_cli_main_maps_to_command_registry(self, engine):
        """CLI main.py maps to command registry tests."""
        plan = engine.select_from_files(["src/axiom_cli/main.py"])
        assert plan.strategy == "targeted"
        assert plan.selected_tests[0].test_path == "tests/test_command_registry.py"

    def test_test_file_itself(self, engine):
        """Changed test files are included directly."""
        plan = engine.select_from_files(["tests/test_agents.py"])
        assert plan.strategy == "targeted"
        assert plan.selected_tests[0].test_path == "tests/test_agents.py"


# ---------------------------------------------------------------------------
# Test: Module-level mapping
# ---------------------------------------------------------------------------


class TestModuleMapping:
    """Test module-level prefix mapping."""

    def test_inventory_module(self, engine):
        """Inventory module files map to inventory tests."""
        plan = engine.select_from_files(
            ["src/axiom_core/inventory/some_file.py"],
        )
        assert plan.strategy == "targeted"
        paths = {t.test_path for t in plan.selected_tests}
        assert "tests/test_inventory.py" in paths
        assert "tests/test_extraction_planner.py" in paths

    def test_discovery_module(self, engine):
        """Discovery module files map to discovery tests."""
        plan = engine.select_from_files(
            ["src/axiom_core/discovery/harness.py"],
        )
        assert plan.strategy == "targeted"
        paths = {t.test_path for t in plan.selected_tests}
        assert "tests/test_discovery_harness.py" in paths

    def test_self_mapping(self, engine):
        """test_selection_engine.py has a direct mapping to its test."""
        plan = engine.select_from_files(
            ["src/axiom_core/test_selection_engine.py"],
        )
        assert plan.strategy == "targeted"
        assert plan.selected_tests[0].test_path == "tests/test_test_selection_engine.py"
        assert plan.selected_tests[0].reason == "direct_mapping"

    def test_convention_based_fallback(self, engine):
        """Unknown files use convention: test_<stem>.py."""
        plan = engine.select_from_files(
            ["src/axiom_core/some_future_module.py"],
        )
        assert plan.strategy == "targeted"
        assert plan.selected_tests[0].test_path == "tests/test_some_future_module.py"
        assert plan.selected_tests[0].reason == "module_match"


# ---------------------------------------------------------------------------
# Test: Ruff inclusion
# ---------------------------------------------------------------------------


class TestRuffInclusion:
    """Test automatic ruff inclusion for Python changes."""

    def test_python_files_include_ruff(self, engine):
        """Python file changes trigger ruff inclusion."""
        plan = engine.select_from_files(
            ["src/axiom_core/knowledge_graph.py"],
        )
        assert plan.include_ruff is True
        assert "src/axiom_core/knowledge_graph.py" in plan.ruff_targets

    def test_non_python_files_no_ruff(self, engine):
        """Non-Python files don't trigger ruff (but fall back to full suite)."""
        plan = engine.select_from_files(["README.md"])
        # Non-.py files with no mapping → full suite fallback
        assert plan.strategy == "full_suite"


# ---------------------------------------------------------------------------
# Test: High-risk areas
# ---------------------------------------------------------------------------


class TestHighRiskAreas:
    """Test full-suite escalation for high-risk areas."""

    def test_database_py(self, engine):
        """database.py triggers full suite."""
        plan = engine.select_from_files(["src/axiom_core/database.py"])
        assert plan.strategy == "full_suite"
        assert "High-risk" in plan.full_suite_reason

    def test_models_py(self, engine):
        """models.py triggers full suite."""
        plan = engine.select_from_files(["src/axiom_core/models.py"])
        assert plan.strategy == "full_suite"

    def test_persistence_py(self, engine):
        """persistence.py triggers full suite."""
        plan = engine.select_from_files(["src/axiom_core/persistence.py"])
        assert plan.strategy == "full_suite"

    def test_runner_module(self, engine):
        """Runner module files trigger full suite."""
        plan = engine.select_from_files(
            ["src/axiom_core/runner/some_new_runner.py"],
        )
        assert plan.strategy == "full_suite"
        assert "'/runner/'" in plan.full_suite_reason

    def test_schemas_py(self, engine):
        """schemas.py triggers full suite."""
        plan = engine.select_from_files(["src/axiom_core/schemas.py"])
        assert plan.strategy == "full_suite"


# ---------------------------------------------------------------------------
# Test: Full suite fallback
# ---------------------------------------------------------------------------


class TestFullSuiteFallback:
    """Test full suite fallback scenarios."""

    def test_force_full_suite(self, engine):
        """Force full suite via flag."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest(
            changed_files=["src/axiom_core/knowledge_graph.py"],
            force_full_suite=True,
        )
        plan = engine.select_tests(request)
        assert plan.strategy == "full_suite"
        assert "force_full_suite" in plan.full_suite_reason

    def test_no_changed_files(self, engine):
        """No changed files falls back to full suite."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest()
        plan = engine.select_tests(request)
        assert plan.strategy == "full_suite"
        assert "No changed files" in plan.full_suite_reason

    def test_no_test_mapping(self, engine):
        """Files with no Python → full suite."""
        plan = engine.select_from_files(["docs/README.md"])
        assert plan.strategy == "full_suite"


# ---------------------------------------------------------------------------
# Test: Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Test that output is deterministic."""

    def test_deterministic_test_order(self, engine):
        """Selected tests are ordered deterministically."""
        plan1 = engine.select_from_files([
            "src/axiom_core/patch_proposal.py",
            "src/axiom_core/knowledge_graph.py",
        ])
        plan2 = engine.select_from_files([
            "src/axiom_core/knowledge_graph.py",
            "src/axiom_core/patch_proposal.py",
        ])
        paths1 = [t.test_path for t in plan1.selected_tests]
        paths2 = [t.test_path for t in plan2.selected_tests]
        assert paths1 == paths2

    def test_deterministic_ruff_targets(self, engine):
        """Ruff targets are sorted."""
        plan = engine.select_from_files([
            "src/axiom_core/patch_proposal.py",
            "src/axiom_core/knowledge_graph.py",
        ])
        assert plan.ruff_targets == sorted(plan.ruff_targets)


# ---------------------------------------------------------------------------
# Test: Evidence bundle
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    """Test evidence artifact writing."""

    def test_evidence_files_created(self, engine, tmp_env):
        """All 4 evidence files are written."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest(
            changed_files=["src/axiom_core/knowledge_graph.py"],
        )
        plan = engine.select_tests(request)
        run_dir = engine.write_evidence(plan, request)

        from pathlib import Path

        d = Path(run_dir)
        assert (d / "selection_request.json").exists()
        assert (d / "selection_result.json").exists()
        assert (d / "selection_summary.md").exists()
        assert (d / "pass_fail.json").exists()

    def test_evidence_request_valid(self, engine, tmp_env):
        """selection_request.json is valid JSON."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest(
            changed_files=["src/axiom_core/knowledge_graph.py"],
        )
        plan = engine.select_tests(request)
        run_dir = engine.write_evidence(plan, request)

        from pathlib import Path

        req = json.loads(
            (Path(run_dir) / "selection_request.json").read_text(),
        )
        assert req["plan_id"] == plan.plan_id
        assert "request" in req

    def test_pass_fail_valid(self, engine, tmp_env):
        """pass_fail.json has passed=True."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest(
            changed_files=["src/axiom_core/knowledge_graph.py"],
        )
        plan = engine.select_tests(request)
        run_dir = engine.write_evidence(plan, request)

        from pathlib import Path

        pf = json.loads((Path(run_dir) / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# Test: Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Test ID validation."""

    def test_work_item_traversal(self, engine):
        """Path traversal in work_item_id is rejected."""
        with pytest.raises(ValueError, match="must not contain"):
            engine.select_from_work_item("../../etc/passwd")

    def test_proposal_traversal(self, engine):
        """Path traversal in proposal_id is rejected."""
        with pytest.raises(ValueError, match="must not contain"):
            engine.select_from_proposal("../../etc/passwd")


# ---------------------------------------------------------------------------
# Test: JSON serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test to_dict serialization."""

    def test_plan_to_dict(self, engine):
        """SelectedTestPlan serializes correctly."""
        plan = engine.select_from_files(
            ["src/axiom_core/knowledge_graph.py"],
        )
        data = plan.to_dict()
        assert "plan_id" in data
        assert "strategy" in data
        assert "selected_tests" in data
        assert "include_ruff" in data
        assert "test_count" in data
        assert data["test_count"] == len(data["selected_tests"])

    def test_request_to_dict(self):
        """TestSelectionRequest serializes correctly."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        req = TestSelectionRequest(
            changed_files=["foo.py"],
            work_item_id="wi-1",
        )
        data = req.to_dict()
        assert data["changed_files"] == ["foo.py"]
        assert data["work_item_id"] == "wi-1"

    def test_full_suite_includes_ruff(self, engine):
        """Full suite plans include ruff on src/ and tests/."""
        from axiom_core.test_selection_engine import TestSelectionRequest

        request = TestSelectionRequest(force_full_suite=True)
        plan = engine.select_tests(request)
        assert plan.include_ruff is True
        assert "src/" in plan.ruff_targets
        assert "tests/" in plan.ruff_targets
