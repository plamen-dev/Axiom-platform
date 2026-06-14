"""Tests for the Local Audit, Evidence, and Run Spine (PR #31).

Covers: run ID generation, artifact folder creation, JSONL audit append,
manifest generation, dry-run file production, failed-run file production,
external call declaration defaults, and run history query.
"""

import json
from pathlib import Path

from axiom_core.run_spine import (
    AuditEntry,
    ExternalCallDeclaration,
    RunContext,
    append_audit_entry,
    create_run_folder,
    execute_run,
    generate_run_id,
    list_runs,
    write_artifact_manifest,
    write_external_calls,
)

# ---------------------------------------------------------------------------
# 1. Run ID generation
# ---------------------------------------------------------------------------


class TestRunIdGeneration:
    def test_format_contains_timestamp_and_capability(self):
        run_id = generate_run_id("GridCreation", "dry_run")
        parts = run_id.split("_")
        # YYYYMMDD_HHMMSS_gridcreation_dry_run_<hex8>
        assert len(parts) >= 5
        assert parts[0].isdigit() and len(parts[0]) == 8  # date
        assert parts[1].isdigit() and len(parts[1]) == 6  # time
        assert "gridcreation" in run_id.lower()
        assert "dry_run" in run_id
        # Unique hex suffix at the end
        assert len(parts[-1]) == 8
        int(parts[-1], 16)  # must be valid hex

    def test_same_capability_same_second_unique_ids(self):
        id1 = generate_run_id("GridCreation", "dry_run")
        id2 = generate_run_id("GridCreation", "dry_run")
        assert id1 != id2

    def test_different_capabilities_produce_different_ids(self):
        id1 = generate_run_id("GridCreation", "dry_run")
        id2 = generate_run_id("InventoryModel", "execute")
        assert id1 != id2
        assert "gridcreation" in id1
        assert "inventorymodel" in id2

    def test_mode_included_in_id(self):
        run_id = generate_run_id("CreateLevels", "execute")
        assert "execute" in run_id


# ---------------------------------------------------------------------------
# 2. Artifact folder creation
# ---------------------------------------------------------------------------


class TestArtifactFolderCreation:
    def test_creates_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        run_id = "20260606_153012_grid_creation_dry_run"
        folder = create_run_folder(run_id)
        assert folder.is_dir()
        assert folder.name == run_id
        assert folder.parent.name == "Runs"

    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        run_id = "20260606_153012_test_run"
        folder1 = create_run_folder(run_id)
        folder2 = create_run_folder(run_id)
        assert folder1 == folder2
        assert folder1.is_dir()


# ---------------------------------------------------------------------------
# 3. Audit JSONL append
# ---------------------------------------------------------------------------


class TestAuditJSONLAppend:
    def test_appends_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        entry = AuditEntry(
            timestamp_utc="2026-06-06T15:30:12+00:00",
            run_id="test_run_001",
            source="cli",
            capability="GridCreation",
            mode="dry_run",
            risk_level="low",
            user="testuser",
            input_summary="{}",
            artifact_path="/tmp/test",
            status="started",
        )
        log_path = append_audit_entry(entry)
        assert log_path.is_file()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["run_id"] == "test_run_001"
        assert data["capability"] == "GridCreation"
        assert data["status"] == "started"

    def test_multiple_appends(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        for i in range(3):
            entry = AuditEntry(
                timestamp_utc=f"2026-06-06T15:3{i}:00+00:00",
                run_id=f"run_{i}",
                capability="GridCreation",
            )
            append_audit_entry(entry)
        log_path = tmp_path / "audit" / "axiom_command_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_audit_entry_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        entry = AuditEntry(
            timestamp_utc="2026-06-06T15:30:12+00:00",
            run_id="test_fields",
            source="revit_ui",
            capability="InventoryModel",
            mode="execute",
            risk_level="medium",
            model_path="C:\\Models\\test.rvt",
            model_path_redacted="C:/Models/test.rvt",
            user="builder",
            input_summary='{"category": "Walls"}',
            artifact_path="/runs/test_fields",
            status="completed",
            external_calls_made=False,
        )
        append_audit_entry(entry)
        log_path = tmp_path / "audit" / "axiom_command_log.jsonl"
        data = json.loads(log_path.read_text().strip())
        assert data["source"] == "revit_ui"
        assert data["external_calls_made"] is False
        assert data["model_path_redacted"] == "C:/Models/test.rvt"
        assert "model_path" not in data


# ---------------------------------------------------------------------------
# 4. Manifest generation
# ---------------------------------------------------------------------------


class TestManifestGeneration:
    def test_lists_all_files(self, tmp_path):
        (tmp_path / "run_metadata.json").write_text("{}")
        (tmp_path / "command_input.json").write_text("{}")
        (tmp_path / "execution_result.json").write_text("{}")
        manifest_path = write_artifact_manifest(tmp_path, "test_run")
        assert manifest_path.is_file()
        data = json.loads(manifest_path.read_text())
        assert data["run_id"] == "test_run"
        assert "run_metadata.json" in data["files"]
        assert "command_input.json" in data["files"]
        assert "execution_result.json" in data["files"]
        # Manifest itself is excluded
        assert "artifact_manifest.json" not in data["files"]

    def test_manifest_has_timestamp(self, tmp_path):
        (tmp_path / "test.json").write_text("{}")
        write_artifact_manifest(tmp_path, "run_x")
        data = json.loads((tmp_path / "artifact_manifest.json").read_text())
        assert data["created_at_utc"] != ""


# ---------------------------------------------------------------------------
# 5. Dry-run creates required files
# ---------------------------------------------------------------------------


class TestDryRunCreatesRequiredFiles:
    def test_dry_run_produces_all_required_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        ctx = RunContext(
            capability="GridCreation",
            mode="dry_run",
            source="test",
            input_data={"HorizontalCount": 5, "VerticalCount": 5},
        )
        result = execute_run(ctx)
        assert result.status == "completed"
        folder = Path(result.artifact_path)
        assert folder.is_dir()
        # Required files
        required = [
            "run_metadata.json",
            "command_input.json",
            "execution_result.json",
            "external_calls.json",
            "artifact_manifest.json",
            "run_summary.md",
        ]
        for fname in required:
            assert (folder / fname).is_file(), f"Missing: {fname}"

    def test_dry_run_does_not_mutate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        ctx = RunContext(capability="GridCreation", mode="dry_run")
        result = execute_run(ctx)
        exec_result = json.loads(
            (Path(result.artifact_path) / "execution_result.json").read_text()
        )
        assert exec_result["mode"] == "dry_run"
        assert "No model mutation" in exec_result.get("note", "")

    def test_dry_run_writes_audit_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        ctx = RunContext(capability="GridCreation", mode="dry_run", source="test")
        execute_run(ctx)
        log_path = tmp_path / "audit" / "axiom_command_log.jsonl"
        assert log_path.is_file()
        lines = log_path.read_text().strip().split("\n")
        # Two entries: started + completed
        assert len(lines) == 2
        started = json.loads(lines[0])
        completed = json.loads(lines[1])
        assert started["status"] == "started"
        assert completed["status"] == "completed"
        # Completion entry must have its own timestamp (not reuse start time)
        assert completed["timestamp_utc"] >= started["timestamp_utc"]


# ---------------------------------------------------------------------------
# 6. Failed run still creates required files
# ---------------------------------------------------------------------------


class TestFailedRunCreatesRequiredFiles:
    def test_failed_run_still_produces_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))

        def failing_executor(ctx):
            raise RuntimeError("Simulated capability failure")

        ctx = RunContext(
            capability="GridCreation",
            mode="execute",
            source="test",
            input_data={"HorizontalCount": 3},
        )
        result = execute_run(ctx, executor=failing_executor)
        assert result.status == "failed"
        folder = Path(result.artifact_path)
        assert folder.is_dir()
        # All required files still exist
        required = [
            "run_metadata.json",
            "command_input.json",
            "execution_result.json",
            "error_result.json",
            "external_calls.json",
            "artifact_manifest.json",
            "run_summary.md",
        ]
        for fname in required:
            assert (folder / fname).is_file(), f"Missing on failure: {fname}"
        # Error captured
        err = json.loads((folder / "error_result.json").read_text())
        assert err["error_type"] == "RuntimeError"
        assert "Simulated" in err["error_message"]

    def test_failed_run_audit_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))

        def failing_executor(ctx):
            raise ValueError("Bad input")

        ctx = RunContext(capability="CreateLevels", mode="execute")
        execute_run(ctx, executor=failing_executor)
        log_path = tmp_path / "audit" / "axiom_command_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        final = json.loads(lines[-1])
        assert final["status"] == "failed"


# ---------------------------------------------------------------------------
# 7. External call declaration defaults to false
# ---------------------------------------------------------------------------


class TestExternalCallDeclaration:
    def test_default_no_external_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        ctx = RunContext(capability="GridCreation", mode="dry_run")
        result = execute_run(ctx)
        ext_path = Path(result.artifact_path) / "external_calls.json"
        data = json.loads(ext_path.read_text())
        assert data["external_calls_made"] is False
        assert data["services"] == []
        assert "Local-only" in data["notes"]

    def test_declaration_model(self):
        decl = ExternalCallDeclaration()
        d = decl.to_dict()
        assert d["external_calls_made"] is False
        assert d["services"] == []

    def test_custom_declaration(self, tmp_path):
        decl = ExternalCallDeclaration(
            external_calls_made=True,
            services=["revit_pipe"],
            notes="Called local Revit pipe.",
        )
        write_external_calls(tmp_path, decl)
        data = json.loads((tmp_path / "external_calls.json").read_text())
        assert data["external_calls_made"] is True
        assert "revit_pipe" in data["services"]


# ---------------------------------------------------------------------------
# 8. Run history can discover completed runs
# ---------------------------------------------------------------------------


class TestRunHistoryQuery:
    def test_lists_completed_runs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        # Execute two runs
        ctx1 = RunContext(capability="GridCreation", mode="dry_run", source="test")
        ctx2 = RunContext(capability="InventoryModel", mode="execute", source="test")
        execute_run(ctx1)
        execute_run(ctx2)
        runs = list_runs()
        assert len(runs) >= 2
        caps = [r["capability"] for r in runs]
        assert "GridCreation" in caps
        assert "InventoryModel" in caps

    def test_empty_history(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        runs = list_runs()
        assert runs == []

    def test_limit_respected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        for i in range(5):
            ctx = RunContext(capability=f"Cap{i}", mode="dry_run", source="test")
            execute_run(ctx)
        runs = list_runs(limit=3)
        assert len(runs) == 3

    def test_history_ordered_recent_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
        # Create folders with different timestamps manually
        runs_dir = tmp_path / "Runs"
        runs_dir.mkdir(parents=True)
        for name in ["20260101_000000_a_dry_run", "20260601_000000_b_dry_run"]:
            d = runs_dir / name
            d.mkdir()
            meta = {"run_id": name, "capability": name.split("_")[2]}
            (d / "run_metadata.json").write_text(json.dumps(meta))
        runs = list_runs()
        assert runs[0]["run_id"] == "20260601_000000_b_dry_run"
