"""Tests for axiom_core.model_health — Model Health and Capability Readiness Engine.

Covers:
1. Health report schema generation.
2. Readiness classification: READY.
3. Readiness classification: WARNING.
4. Readiness classification: BLOCKED.
5. Timestamp/currentness fields exist.
6. Markdown report generation.
7. Missing/null values handled safely.
8. Health run creates PR 31 artifact files and audit log entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.model_health import (
    CHECKER_VERSION,
    RULESET_VERSION,
    CapabilityReadiness,
    EnvironmentReport,
    HealthRunContext,
    ModelHealth,
    capture_environment,
    evaluate_all_readiness,
    evaluate_readiness,
    execute_health_run,
    generate_health_markdown,
    list_readiness_capabilities,
    register_readiness_check,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point AXIOM_ARTIFACTS_ROOT at a temp directory."""
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path))
    return tmp_path


def _healthy_model() -> ModelHealth:
    """A model that should produce READY for GridCreation."""
    return ModelHealth(
        generated_at_utc="2026-06-07T12:00:00+00:00",
        revit_version="2024",
        model_path=r"C:\Projects\Test.rvt",
        model_path_redacted="C:/Projects/Test.rvt",
        active_document_title="Test",
        active_view_name="Level 1",
        active_view_type="FloorPlan",
        grid_count=0,
        level_count=3,
        warning_count=5,
        stale_status="current",
    )


def _warning_model() -> ModelHealth:
    """A model that produces WARNING for GridCreation (existing grids)."""
    h = _healthy_model()
    h.grid_count = 12
    return h


def _blocked_model() -> ModelHealth:
    """A model that produces BLOCKED for GridCreation (no document)."""
    return ModelHealth(
        generated_at_utc="2026-06-07T12:00:00+00:00",
        active_document_title=None,
    )


# ===================================================================
# 1. Health report schema generation
# ===================================================================


class TestHealthReportSchema:
    def test_model_health_to_dict_has_all_fields(self):
        h = _healthy_model()
        d = h.to_dict()
        expected_keys = {
            "generated_at_utc",
            "checker_version",
            "ruleset_version",
            "revit_version",
            "model_path",
            "model_path_redacted",
            "model_last_modified_utc",
            "active_document_title",
            "active_view_name",
            "active_view_type",
            "worksharing_enabled",
            "linked_model_count",
            "level_count",
            "grid_count",
            "room_count",
            "space_count",
            "warning_count",
            "cad_import_count",
            "cad_link_count",
            "view_template_count",
            "sheet_count",
            "stale_status",
        }
        assert set(d.keys()) == expected_keys

    def test_model_health_json_serializable(self):
        h = _healthy_model()
        serialized = json.dumps(h.to_dict(), default=str)
        parsed = json.loads(serialized)
        assert parsed["revit_version"] == "2024"

    def test_checker_and_ruleset_versions_present(self):
        h = ModelHealth()
        assert h.checker_version == CHECKER_VERSION
        assert h.ruleset_version == RULESET_VERSION

    def test_environment_report_schema(self):
        env = capture_environment(revit_version="2024", revit_connected=True)
        d = env.to_dict()
        assert "generated_at_utc" in d
        assert "axiom_version" in d
        assert "python_version" in d
        assert "platform_system" in d
        assert d["revit_version"] == "2024"
        assert d["revit_connected"] is True


# ===================================================================
# 2. Readiness classification: READY
# ===================================================================


class TestReadinessReady:
    def test_grid_creation_ready_with_healthy_model(self):
        r = evaluate_readiness("GridCreation", _healthy_model())
        assert r.readiness == "READY"
        assert r.capability == "GridCreation"
        assert r.dry_run_available is True
        assert r.execute_available is True
        assert r.blocking_conditions == []

    def test_grid_creation_ready_no_warnings(self):
        r = evaluate_readiness("GridCreation", _healthy_model())
        assert r.warnings == []
        assert r.required_user_decisions == []


# ===================================================================
# 3. Readiness classification: WARNING
# ===================================================================


class TestReadinessWarning:
    def test_existing_grids_produce_warning(self):
        r = evaluate_readiness("GridCreation", _warning_model())
        assert r.readiness == "WARNING"
        assert any("grids" in w.lower() for w in r.warnings)
        assert any("grids" in d.lower() for d in r.required_user_decisions)

    def test_missing_revit_version_produces_warning(self):
        h = _healthy_model()
        h.revit_version = None
        r = evaluate_readiness("GridCreation", h)
        assert r.readiness == "WARNING"
        assert any("revit version" in w.lower() for w in r.warnings)

    def test_unknown_view_type_produces_warning(self):
        h = _healthy_model()
        h.active_view_type = "Drafting"
        r = evaluate_readiness("GridCreation", h)
        assert r.readiness == "WARNING"
        assert any("view type" in w.lower() for w in r.warnings)

    def test_warning_still_allows_execution(self):
        r = evaluate_readiness("GridCreation", _warning_model())
        assert r.execute_available is True


# ===================================================================
# 4. Readiness classification: BLOCKED
# ===================================================================


class TestReadinessBlocked:
    def test_no_document_produces_blocked(self):
        r = evaluate_readiness("GridCreation", _blocked_model())
        assert r.readiness == "BLOCKED"
        assert any("no active" in b.lower() for b in r.blocking_conditions)

    def test_blocked_disables_execution(self):
        r = evaluate_readiness("GridCreation", _blocked_model())
        assert r.execute_available is False

    def test_3d_view_produces_blocked(self):
        h = _healthy_model()
        h.active_view_type = "ThreeD"
        r = evaluate_readiness("GridCreation", h)
        assert r.readiness == "BLOCKED"

    def test_schedule_view_produces_blocked(self):
        h = _healthy_model()
        h.active_view_type = "Schedule"
        r = evaluate_readiness("GridCreation", h)
        assert r.readiness == "BLOCKED"


# ===================================================================
# 5. Timestamp/currentness fields exist
# ===================================================================


class TestTimestampFields:
    def test_generated_at_utc_populated(self):
        h = _healthy_model()
        assert h.generated_at_utc != ""

    def test_stale_status_has_value(self):
        h = ModelHealth()
        assert h.stale_status in {"current", "stale", "unknown"}

    def test_environment_timestamp_populated(self):
        env = capture_environment()
        assert env.generated_at_utc != ""
        assert "T" in env.generated_at_utc


# ===================================================================
# 6. Markdown report generation
# ===================================================================


class TestMarkdownGeneration:
    def test_markdown_contains_header(self):
        h = _healthy_model()
        rs = [evaluate_readiness("GridCreation", h)]
        md = generate_health_markdown(h, rs)
        assert "# Axiom Model Health Report" in md

    def test_markdown_contains_health_summary(self):
        h = _healthy_model()
        rs = [evaluate_readiness("GridCreation", h)]
        md = generate_health_markdown(h, rs)
        assert "## Health Summary" in md
        assert "| Field | Value |" in md

    def test_markdown_contains_capability_section(self):
        h = _healthy_model()
        rs = [evaluate_readiness("GridCreation", h)]
        md = generate_health_markdown(h, rs)
        assert "### GridCreation" in md
        assert "**Status:** READY" in md

    def test_markdown_blocked_shows_conditions(self):
        h = _blocked_model()
        rs = [evaluate_readiness("GridCreation", h)]
        md = generate_health_markdown(h, rs)
        assert "**Status:** BLOCKED" in md
        assert "**Blocking conditions:**" in md

    def test_markdown_null_fields_show_na(self):
        h = ModelHealth()
        md = generate_health_markdown(h, [])
        assert "N/A" in md


# ===================================================================
# 7. Missing/null values handled safely
# ===================================================================


class TestNullSafety:
    def test_empty_model_health_serializes(self):
        h = ModelHealth()
        d = h.to_dict()
        assert d["revit_version"] is None
        assert d["model_path"] is None
        assert d["grid_count"] is None

    def test_empty_model_health_json_round_trip(self):
        h = ModelHealth()
        s = json.dumps(h.to_dict(), default=str)
        parsed = json.loads(s)
        assert parsed["stale_status"] == "unknown"

    def test_readiness_with_all_none_fields(self):
        h = ModelHealth()
        r = evaluate_readiness("GridCreation", h)
        assert r.readiness == "BLOCKED"
        assert r.capability == "GridCreation"

    def test_unknown_capability_returns_unknown(self):
        h = _healthy_model()
        r = evaluate_readiness("NonExistent", h)
        assert r.readiness == "UNKNOWN"
        assert any("no readiness check" in w.lower() for w in r.warnings)

    def test_evaluate_all_includes_registered(self):
        results = evaluate_all_readiness(_healthy_model())
        caps = [r.capability for r in results]
        assert "GridCreation" in caps


# ===================================================================
# 8. Health run creates PR 31 artifact files and audit log entry
# ===================================================================


class TestHealthRunSpineIntegration:
    def test_health_run_creates_standard_spine_files(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            model_path=r"C:\Test\Model.rvt",
            revit_version="2024",
            active_document_title="Model",
            active_view_name="Level 1",
            active_view_type="FloorPlan",
        ))
        folder = Path(result.artifact_path)
        assert (folder / "run_metadata.json").is_file()
        assert (folder / "command_input.json").is_file()
        assert (folder / "execution_result.json").is_file()
        assert (folder / "external_calls.json").is_file()
        assert (folder / "artifact_manifest.json").is_file()
        assert (folder / "run_summary.md").is_file()

    def test_health_run_creates_health_specific_files(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            active_view_type="FloorPlan",
        ))
        folder = Path(result.artifact_path)
        assert (folder / "axiom_environment_report.json").is_file()
        assert (folder / "axiom_model_health.json").is_file()
        assert (folder / "axiom_model_health.md").is_file()
        assert (folder / "axiom_capability_readiness.json").is_file()

    def test_health_run_writes_audit_log(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
        ))
        audit_log = tmp_artifacts / "audit" / "axiom_command_log.jsonl"
        assert audit_log.is_file()
        entries = [
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").strip().split("\n")
        ]
        run_entries = [e for e in entries if e["run_id"] == result.run_id]
        assert len(run_entries) == 2
        assert run_entries[0]["status"] == "started"
        assert run_entries[1]["status"] == "completed"

    def test_health_run_audit_timestamps_differ(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
        ))
        audit_log = tmp_artifacts / "audit" / "axiom_command_log.jsonl"
        entries = [
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").strip().split("\n")
        ]
        run_entries = [e for e in entries if e["run_id"] == result.run_id]
        assert run_entries[1]["timestamp_utc"] >= run_entries[0]["timestamp_utc"]

    def test_health_run_metadata_shows_model_health(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            revit_version="2024",
            active_document_title="Test",
        ))
        folder = Path(result.artifact_path)
        meta = json.loads((folder / "run_metadata.json").read_text(encoding="utf-8"))
        assert meta["capability"] == "ModelHealth"
        assert meta["mode"] == "diagnose"
        assert meta["status"] == "completed"

    def test_health_run_result_object(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            active_view_type="FloorPlan",
            revit_version="2024",
        ))
        assert result.status == "completed"
        assert result.error is None
        assert isinstance(result.health, ModelHealth)
        assert isinstance(result.environment, EnvironmentReport)
        assert len(result.readiness_results) >= 1

    def test_health_run_readiness_json_content(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            active_view_type="FloorPlan",
            revit_version="2024",
            capabilities=["GridCreation"],
        ))
        folder = Path(result.artifact_path)
        rd = json.loads(
            (folder / "axiom_capability_readiness.json").read_text(encoding="utf-8")
        )
        assert "generated_at_utc" in rd
        assert len(rd["capabilities"]) == 1
        assert rd["capabilities"][0]["capability"] == "GridCreation"
        assert rd["capabilities"][0]["readiness"] == "READY"

    def test_health_run_empty_capabilities_evaluates_none(self, tmp_artifacts: Path):
        """Empty list means evaluate zero capabilities (not all)."""
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            capabilities=[],
        ))
        folder = Path(result.artifact_path)
        rd = json.loads(
            (folder / "axiom_capability_readiness.json").read_text(encoding="utf-8")
        )
        assert rd["capabilities"] == []

    def test_health_run_none_capabilities_evaluates_all(self, tmp_artifacts: Path):
        """None capabilities means evaluate all registered."""
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            capabilities=None,
        ))
        assert len(result.readiness_results) >= 1

    def test_health_run_audit_model_path_redacted(self, tmp_artifacts: Path):
        """model_path_redacted auto-computed when not provided."""
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            model_path=r"C:\Users\plamen\Projects\Test.rvt",
        ))
        audit_log = tmp_artifacts / "audit" / "axiom_command_log.jsonl"
        entries = [
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").strip().split("\n")
        ]
        run_entries = [e for e in entries if e["run_id"] == result.run_id]
        for entry in run_entries:
            assert "plamen" not in entry.get("model_path_redacted", "")

    def test_health_run_manifest_includes_health_files(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
        ))
        folder = Path(result.artifact_path)
        manifest = json.loads(
            (folder / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        files = manifest["files"]
        assert "axiom_model_health.json" in files
        assert "axiom_capability_readiness.json" in files
        assert "axiom_environment_report.json" in files
        assert "axiom_model_health.md" in files


# ===================================================================
# Readiness registry extensibility
# ===================================================================


class TestReadinessRegistry:
    def test_list_readiness_capabilities_includes_grid_creation(self):
        assert "GridCreation" in list_readiness_capabilities()

    def test_unknown_capability_defaults_execute_false(self):
        r = evaluate_readiness("NonExistent", _healthy_model())
        assert r.readiness == "UNKNOWN"
        assert r.execute_available is False

    def test_default_capability_readiness_execute_false(self):
        r = CapabilityReadiness(capability="Test")
        assert r.execute_available is False

    def test_register_custom_readiness_check(self):
        def _custom_check(health: ModelHealth) -> CapabilityReadiness:
            return CapabilityReadiness(
                capability="CustomCap",
                readiness="READY",
                execute_available=True,
            )

        register_readiness_check("CustomCap", _custom_check)
        try:
            assert "CustomCap" in list_readiness_capabilities()
            r = evaluate_readiness("CustomCap", _healthy_model())
            assert r.readiness == "READY"
        finally:
            from axiom_core.model_health import _readiness_checks
            _readiness_checks.pop("CustomCap", None)


# ===================================================================
# Audit trail: capabilities_requested in command_input.json
# ===================================================================


class TestCapabilitiesRequestedAudit:
    """Verify command_input.json records the correct capabilities_requested."""

    def test_none_capabilities_records_all_registered(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            capabilities=None,
        ))
        inp = json.loads(
            (Path(result.artifact_path) / "command_input.json").read_text(
                encoding="utf-8"
            )
        )
        assert inp["capabilities_requested"] == list_readiness_capabilities()

    def test_empty_capabilities_records_empty_list(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            capabilities=[],
        ))
        inp = json.loads(
            (Path(result.artifact_path) / "command_input.json").read_text(
                encoding="utf-8"
            )
        )
        assert inp["capabilities_requested"] == []

    def test_explicit_capabilities_records_exact_list(self, tmp_artifacts: Path):
        result = execute_health_run(HealthRunContext(
            active_document_title="Model",
            capabilities=["GridCreation"],
        ))
        inp = json.loads(
            (Path(result.artifact_path) / "command_input.json").read_text(
                encoding="utf-8"
            )
        )
        assert inp["capabilities_requested"] == ["GridCreation"]
