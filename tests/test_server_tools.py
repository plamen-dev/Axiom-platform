"""Tests for axiom_core.server_tools — Capability Registry and MCP-Compatible Server Surface.

Covers:
1. Capability registry includes GridCreation.
2. Capability description returns stable schema.
3. Server diagnose returns expected fields.
4. Dry-run tool creates run artifact.
5. Unknown capability returns structured error.
6. Run history returns created runs.
7. Artifacts lookup returns manifest.
8. Tool outputs are JSON-serializable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.server_tools import (
    AXIOM_VERSION,
    AxiomCapabilityRegistry,
    EnhancedCapabilityMeta,
    axiom_capabilities_describe,
    axiom_capabilities_list,
    axiom_capability_readiness_get,
    axiom_model_health_get_latest,
    axiom_runs_create_dry_run,
    axiom_runs_get_artifacts,
    axiom_runs_list_history,
    axiom_server_diagnose,
    axiom_server_get_log_path,
    axiom_server_get_version,
    get_enhanced_registry,
)


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point AXIOM_ARTIFACTS_ROOT at a temp directory."""
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
    return tmp_path


# ===================================================================
# 1. Capability registry includes GridCreation
# ===================================================================


class TestCapabilityRegistry:
    def test_grid_creation_registered(self):
        registry = get_enhanced_registry()
        assert registry.is_registered("grid_creation")

    def test_registry_count(self):
        registry = get_enhanced_registry()
        assert registry.count >= 1

    def test_list_ids_includes_grid_creation(self):
        registry = get_enhanced_registry()
        assert "grid_creation" in registry.list_ids()

    def test_list_all_returns_meta_objects(self):
        registry = get_enhanced_registry()
        caps = registry.list_all()
        assert len(caps) >= 1
        assert all(isinstance(c, EnhancedCapabilityMeta) for c in caps)


# ===================================================================
# 2. Capability description returns stable schema
# ===================================================================


class TestCapabilityDescription:
    def test_describe_grid_creation(self):
        result = axiom_capabilities_describe("grid_creation")
        assert result["error"] is False
        cap = result["capability"]
        expected_keys = {
            "capability_id",
            "display_name",
            "version",
            "risk_level",
            "dry_run_supported",
            "execute_supported",
            "validation_supported",
            "rollback_supported",
            "requires_active_revit_document",
            "input_schema",
            "validation_contract",
            "artifact_outputs",
        }
        assert set(cap.keys()) == expected_keys

    def test_describe_schema_values(self):
        result = axiom_capabilities_describe("grid_creation")
        cap = result["capability"]
        assert cap["capability_id"] == "grid_creation"
        assert cap["display_name"] == "Grid Creation"
        assert cap["dry_run_supported"] is True
        assert cap["rollback_supported"] is False
        assert cap["requires_active_revit_document"] is True

    def test_describe_has_input_schema(self):
        result = axiom_capabilities_describe("grid_creation")
        schema = result["capability"]["input_schema"]
        assert "properties" in schema
        assert "HorizontalCount" in schema["properties"]


# ===================================================================
# 3. Server diagnose returns expected fields
# ===================================================================


class TestServerDiagnose:
    def test_diagnose_fields(self):
        result = axiom_server_diagnose()
        assert result["status"] == "healthy"
        assert result["axiom_version"] == AXIOM_VERSION
        assert "artifact_root" in result
        assert "audit_log_path" in result
        assert result["registered_capability_count"] >= 1
        assert result["external_calls_made"] is False

    def test_get_version(self):
        result = axiom_server_get_version()
        assert result["axiom_version"] == AXIOM_VERSION
        assert "api_version" in result

    def test_get_log_path(self):
        result = axiom_server_get_log_path()
        assert "audit_log_path" in result
        assert "exists" in result


# ===================================================================
# 4. Dry-run tool creates run artifact
# ===================================================================


class TestDryRunCreation:
    def test_create_dry_run_succeeds(self, tmp_artifacts: Path):
        result = axiom_runs_create_dry_run(
            capability_id="grid_creation",
            input_data={"HorizontalCount": 5, "VerticalCount": 5, "SpacingFeet": 30.0},
        )
        assert result["error"] is False
        assert result["status"] == "completed"
        assert result["capability_id"] == "grid_creation"
        assert result["mode"] == "dry_run"
        assert "run_id" in result
        assert "artifact_path" in result

    def test_dry_run_creates_artifact_folder(self, tmp_artifacts: Path):
        result = axiom_runs_create_dry_run(
            capability_id="grid_creation",
            input_data={"HorizontalCount": 3, "VerticalCount": 3, "SpacingFeet": 25.0},
        )
        folder = Path(result["artifact_path"])
        assert folder.is_dir()
        assert (folder / "run_metadata.json").is_file()
        assert (folder / "command_input.json").is_file()
        assert (folder / "execution_result.json").is_file()
        assert (folder / "external_calls.json").is_file()
        assert (folder / "artifact_manifest.json").is_file()
        assert (folder / "run_summary.md").is_file()

    def test_dry_run_writes_audit_log(self, tmp_artifacts: Path):
        result = axiom_runs_create_dry_run(capability_id="grid_creation")
        audit_log = tmp_artifacts / "audit" / "axiom_command_log.jsonl"
        assert audit_log.is_file()
        entries = [
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").strip().split("\n")
        ]
        run_entries = [e for e in entries if e["run_id"] == result["run_id"]]
        assert len(run_entries) == 2
        assert run_entries[0]["status"] == "started"
        assert run_entries[1]["status"] == "completed"


# ===================================================================
# 5. Unknown capability returns structured error
# ===================================================================


class TestUnknownCapability:
    def test_describe_unknown_returns_error(self):
        result = axiom_capabilities_describe("nonexistent_cap")
        assert result["error"] is True
        assert result["error_type"] == "CapabilityNotFound"
        assert "available_capabilities" in result

    def test_dry_run_unknown_returns_error(self, tmp_artifacts: Path):
        result = axiom_runs_create_dry_run(capability_id="nonexistent_cap")
        assert result["error"] is True
        assert result["error_type"] == "CapabilityNotFound"


# ===================================================================
# 6. Run history returns created runs
# ===================================================================


class TestRunHistory:
    def test_list_history_empty(self, tmp_artifacts: Path):
        result = axiom_runs_list_history()
        assert result["count"] == 0
        assert result["runs"] == []

    def test_list_history_after_dry_run(self, tmp_artifacts: Path):
        axiom_runs_create_dry_run(capability_id="grid_creation")
        axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_list_history()
        assert result["count"] >= 2

    def test_list_history_with_limit(self, tmp_artifacts: Path):
        axiom_runs_create_dry_run(capability_id="grid_creation")
        axiom_runs_create_dry_run(capability_id="grid_creation")
        axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_list_history(limit=2)
        assert result["count"] == 2
        assert result["limit"] == 2

    def test_list_history_filter_by_display_name(self, tmp_artifacts: Path):
        axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_list_history(capability="Grid Creation")
        assert result["count"] >= 1
        for run in result["runs"]:
            assert run["capability"] == "Grid Creation"

    def test_list_history_filter_by_capability_id(self, tmp_artifacts: Path):
        axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_list_history(capability="grid_creation")
        assert result["count"] >= 1


# ===================================================================
# 7. Artifacts lookup returns manifest
# ===================================================================


class TestArtifactsLookup:
    def test_get_artifacts_for_run(self, tmp_artifacts: Path):
        dry_run = axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_get_artifacts(dry_run["run_id"])
        assert result["error"] is False
        assert result["run_id"] == dry_run["run_id"]
        assert result["manifest"] is not None
        assert result["file_count"] >= 6

    def test_get_artifacts_unknown_run(self, tmp_artifacts: Path):
        result = axiom_runs_get_artifacts("nonexistent_run_id")
        assert result["error"] is True
        assert result["error_type"] == "RunNotFound"

    def test_get_artifacts_path_traversal_rejected(self, tmp_artifacts: Path):
        result = axiom_runs_get_artifacts("../../etc")
        assert result["error"] is True
        assert result["error_type"] == "InvalidRunId"

    def test_get_artifacts_dotdot_in_id_rejected(self, tmp_artifacts: Path):
        result = axiom_runs_get_artifacts("../secrets")
        assert result["error"] is True
        assert result["error_type"] == "InvalidRunId"

    def test_artifacts_include_expected_files(self, tmp_artifacts: Path):
        dry_run = axiom_runs_create_dry_run(capability_id="grid_creation")
        result = axiom_runs_get_artifacts(dry_run["run_id"])
        expected = {
            "run_metadata.json",
            "command_input.json",
            "execution_result.json",
            "external_calls.json",
            "artifact_manifest.json",
            "run_summary.md",
        }
        assert expected.issubset(set(result["files"]))


# ===================================================================
# 8. Tool outputs are JSON-serializable
# ===================================================================


class TestJsonSerializable:
    def test_diagnose_serializable(self):
        result = axiom_server_diagnose()
        assert json.dumps(result, default=str)

    def test_version_serializable(self):
        result = axiom_server_get_version()
        assert json.dumps(result, default=str)

    def test_capabilities_list_serializable(self):
        result = axiom_capabilities_list()
        assert json.dumps(result, default=str)

    def test_describe_serializable(self):
        result = axiom_capabilities_describe("grid_creation")
        assert json.dumps(result, default=str)

    def test_dry_run_serializable(self, tmp_artifacts: Path):
        result = axiom_runs_create_dry_run(capability_id="grid_creation")
        assert json.dumps(result, default=str)

    def test_history_serializable(self, tmp_artifacts: Path):
        result = axiom_runs_list_history()
        assert json.dumps(result, default=str)

    def test_error_serializable(self):
        result = axiom_capabilities_describe("nope")
        assert json.dumps(result, default=str)


# ===================================================================
# Optional: model health / readiness from artifacts
# ===================================================================


class TestOptionalHealthTools:
    def test_health_get_latest_no_runs(self, tmp_artifacts: Path):
        result = axiom_model_health_get_latest()
        assert result["error"] is True
        assert result["error_type"] == "NoHealthRunsFound"

    def test_readiness_get_no_runs(self, tmp_artifacts: Path):
        result = axiom_capability_readiness_get()
        assert result["error"] is True
        assert result["error_type"] == "NoHealthRunsFound"


# ===================================================================
# Registry operations
# ===================================================================


class TestRegistryOperations:
    def test_register_custom_capability(self):
        registry = AxiomCapabilityRegistry()
        registry.register(
            EnhancedCapabilityMeta(
                capability_id="test_cap",
                display_name="Test Capability",
            )
        )
        assert registry.is_registered("test_cap")
        assert registry.count == 1
        meta = registry.get("test_cap")
        assert meta is not None
        assert meta.display_name == "Test Capability"

    def test_get_nonexistent_returns_none(self):
        registry = AxiomCapabilityRegistry()
        assert registry.get("nope") is None

    def test_capabilities_list_tool(self):
        result = axiom_capabilities_list()
        assert "capabilities" in result
        assert result["count"] >= 1
        cap = result["capabilities"][0]
        assert "capability_id" in cap
        assert "display_name" in cap
