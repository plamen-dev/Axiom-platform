"""Tests for the Axiom Context Preflight and Live System Map.

Exercises the context preflight in a controlled tmp_path repo structure
so results are deterministic. Tests cover:
- success with a fully populated canonical KB + integration docs;
- missing optional docs reported as unknown (not error);
- generated artifacts written under the intended artifact root;
- canonical documents are never mutated;
- JSON and Markdown outputs are well-formed;
- known caveats are present and correctly classified;
- Context Basis template is populated.
"""

from __future__ import annotations

import json
from pathlib import Path

from axiom_core.context_preflight import (
    _CANONICAL_DOCS,
    _CANONICAL_ROOT,
    _COMPONENT_FAMILIES,
    _IMPACT_LEDGER_FILES,
    _INTEGRATION_DOCS,
    _canonical_context,
    _evidence_topology,
    _integration_context,
    _known_caveats,
    _overlap_guardrails,
    _render_atlas_markdown,
    _render_markdown,
    _runner_substrate,
    _system_atlas,
    run_preflight,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_canonical(root: Path) -> None:
    """Create all canonical KB docs so tests can verify presence detection."""
    for rel in _CANONICAL_DOCS.values():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")
    for rel in _IMPACT_LEDGER_FILES.values():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


def _seed_integration(root: Path) -> None:
    """Create all integration docs."""
    for rel in _INTEGRATION_DOCS.values():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


def _seed_runner(root: Path) -> None:
    """Create runner/substrate dirs and files for detection."""
    (root / "tools" / "local_runner").mkdir(parents=True, exist_ok=True)
    for rel in [
        "src/axiom_core/runner/command_registry.py",
        "src/axiom_core/execution_chain_orchestrator.py",
        "src/axiom_core/validation/cli_validation_recorder.py",
        "src/axiom_core/evidence_promotion.py",
        "src/axiom_core/model_health_evidence.py",
    ]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


def _seed_full(root: Path) -> None:
    """Fully populated fake repo."""
    _seed_canonical(root)
    _seed_integration(root)
    _seed_runner(root)
    # Optional docs
    for rel in [
        "docs/runbooks/local-runner-runbook.md",
        "docs/runbooks/validation-loop-runbook.md",
        "docs/runbooks/evidence-log-maintenance.md",
        "docs/architecture/axiom-doctrine.md",
    ]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Section 2: Canonical context
# ---------------------------------------------------------------------------


class TestCanonicalContext:
    def test_all_present(self, tmp_path: Path) -> None:
        _seed_canonical(tmp_path)
        result = _canonical_context(tmp_path)
        assert result["canonical_root_exists"] is True
        for name, present in result["canonical_documents"].items():
            assert present is True, f"{name} should be present"
        for name, present in result["impact_ledger"].items():
            assert present is True, f"{name} should be present"
        assert result["open_investigations_present"] is True

    def test_empty_repo(self, tmp_path: Path) -> None:
        result = _canonical_context(tmp_path)
        assert result["canonical_root_exists"] is False
        for present in result["canonical_documents"].values():
            assert present is False
        for present in result["impact_ledger"].values():
            assert present is False

    def test_partial(self, tmp_path: Path) -> None:
        """Only some canonical docs — partial detection, no error."""
        p = tmp_path / _CANONICAL_ROOT / "00_Readme.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# readme\n", encoding="utf-8")
        result = _canonical_context(tmp_path)
        assert result["canonical_documents"]["00_Readme"] is True
        assert result["canonical_documents"]["10_Current_Strategic_Context"] is False


# ---------------------------------------------------------------------------
# Section 3: Integration context
# ---------------------------------------------------------------------------


class TestIntegrationContext:
    def test_all_present(self, tmp_path: Path) -> None:
        _seed_integration(tmp_path)
        result = _integration_context(tmp_path)
        for status in result["integration_documents"].values():
            assert status == "present"

    def test_missing_reports_as_unknown(self, tmp_path: Path) -> None:
        """Missing optional docs must be 'unknown', never error/exception."""
        result = _integration_context(tmp_path)
        for status in result["integration_documents"].values():
            assert status == "unknown"
        for status in result["optional_investigation_documents"].values():
            assert status == "unknown"


# ---------------------------------------------------------------------------
# Section 5: Evidence topology
# ---------------------------------------------------------------------------


class TestEvidenceTopology:
    def test_module_presence_detection(self, tmp_path: Path) -> None:
        _seed_runner(tmp_path)
        result = _evidence_topology(tmp_path)
        # At least one producer should report module_present
        present_count = sum(
            1 for p in result["known_producers"] if p.get("module_present")
        )
        assert present_count > 0

    def test_state_mutating_list(self, tmp_path: Path) -> None:
        result = _evidence_topology(tmp_path)
        assert len(result["state_mutating_consumers"]) >= 2
        assert "EvidencePromotionLoop" in result["state_mutating_consumers"]
        assert "CapabilityConfidenceEngine" in result["state_mutating_consumers"]

    def test_read_only_list(self, tmp_path: Path) -> None:
        result = _evidence_topology(tmp_path)
        assert len(result["read_only_or_traceability"]) >= 1


# ---------------------------------------------------------------------------
# Section 6: Runner substrate
# ---------------------------------------------------------------------------


class TestRunnerSubstrate:
    def test_all_present(self, tmp_path: Path) -> None:
        _seed_runner(tmp_path)
        result = _runner_substrate(tmp_path)
        assert result["local_runner_present"] is True
        assert result["command_registry_present"] is True
        assert result["execution_chain_present"] is True
        assert result["validation_recorder_present"] is True
        assert result["evidence_promotion_present"] is True
        assert result["model_health_evidence_present"] is True
        assert "Post-PR #151" in result["windows_local_evidence_note"]

    def test_empty_repo(self, tmp_path: Path) -> None:
        result = _runner_substrate(tmp_path)
        assert result["local_runner_present"] is False
        assert result["command_registry_present"] is False


# ---------------------------------------------------------------------------
# Section 7: Known caveats
# ---------------------------------------------------------------------------


class TestKnownCaveats:
    def test_caveats_present(self) -> None:
        caveats = _known_caveats()
        assert len(caveats) >= 6
        ids = {c["id"] for c in caveats}
        assert "CAV-001" in ids
        assert "CAV-006" in ids

    def test_evid001_partially_closed(self) -> None:
        caveats = _known_caveats()
        evid = next(c for c in caveats if c["id"] == "CAV-001")
        assert evid["status"] == "partially_closed"

    def test_gpr_unimplemented(self) -> None:
        caveats = _known_caveats()
        gpr = next(c for c in caveats if c["id"] == "CAV-002")
        assert gpr["status"] == "unimplemented"

    def test_windows_revalidation_pending(self) -> None:
        caveats = _known_caveats()
        win = next(c for c in caveats if c["id"] == "CAV-003")
        assert win["status"] == "revalidation_pending"

    def test_confidence_untouched(self) -> None:
        caveats = _known_caveats()
        conf = next(c for c in caveats if c["id"] == "CAV-004")
        assert conf["status"] == "untouched"

    def test_program34_out_of_scope(self) -> None:
        caveats = _known_caveats()
        p34 = next(c for c in caveats if c["id"] == "CAV-006")
        assert p34["status"] == "out_of_scope"
        assert "pending" not in p34["detail"].lower() or "should not" in p34["detail"].lower()


# ---------------------------------------------------------------------------
# Section 8: Overlap guardrails
# ---------------------------------------------------------------------------


class TestOverlapGuardrails:
    def test_areas_present(self) -> None:
        areas = _overlap_guardrails()
        assert len(areas) >= 6
        area_names = {a["area"] for a in areas}
        assert "Runner / Orchestrator" in area_names
        assert "Canonical / Ledger / Context docs" in area_names


# ---------------------------------------------------------------------------
# Full run_preflight integration
# ---------------------------------------------------------------------------


class TestRunPreflight:
    def test_full_run_produces_artifacts(self, tmp_path: Path) -> None:
        """Full preflight in a fake repo → JSON + Markdown generated."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_full(repo)
        art = tmp_path / "art"

        report = run_preflight(repo_root=str(repo), artifacts_root=str(art))

        assert "run_id" in report
        assert "generated_at_utc" in report
        assert "artifact_paths" in report

        json_path = Path(report["artifact_paths"]["json"])
        md_path = Path(report["artifact_paths"]["markdown"])
        assert json_path.is_file()
        assert md_path.is_file()

        # JSON is valid and round-trips
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["run_id"] == report["run_id"]

        # Markdown is non-empty and has expected sections
        md = md_path.read_text(encoding="utf-8")
        assert "Axiom Context Preflight Report" in md
        assert "Git / Repo State" in md
        assert "Canonical Context" in md
        assert "Evidence Topology" in md
        assert "Context Basis" in md

    def test_artifacts_under_intended_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        art = tmp_path / "myart"

        report = run_preflight(repo_root=str(repo), artifacts_root=str(art))

        json_path = report["artifact_paths"]["json"]
        assert json_path.startswith(str(art))
        assert "context_preflight" in json_path

    def test_canonical_not_mutated(self, tmp_path: Path) -> None:
        """Canonical docs must not be modified by running preflight."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_canonical(repo)

        # Record canonical file mtimes
        mtimes: dict[str, float] = {}
        for rel in _CANONICAL_DOCS.values():
            p = repo / rel
            mtimes[rel] = p.stat().st_mtime

        run_preflight(repo_root=str(repo), artifacts_root=str(tmp_path / "art"))

        # Assert all canonical files unchanged
        for rel, mtime in mtimes.items():
            assert (repo / rel).stat().st_mtime == mtime, f"{rel} was mutated!"

    def test_missing_optional_docs_no_error(self, tmp_path: Path) -> None:
        """Empty repo: all optional docs reported as unknown, no exception."""
        repo = tmp_path / "repo"
        repo.mkdir()

        report = run_preflight(
            repo_root=str(repo), artifacts_root=str(tmp_path / "art")
        )

        ic = report["integration_context"]
        for status in ic["integration_documents"].values():
            assert status == "unknown"
        for status in ic["optional_investigation_documents"].values():
            assert status == "unknown"

    def test_all_nine_sections_present(self, tmp_path: Path) -> None:
        """Report dict has all 9 sections."""
        repo = tmp_path / "repo"
        repo.mkdir()

        report = run_preflight(
            repo_root=str(repo), artifacts_root=str(tmp_path / "art")
        )

        expected_keys = [
            "git_state",
            "canonical_context",
            "integration_context",
            "cli_command_map",
            "evidence_topology",
            "runner_substrate",
            "known_caveats",
            "overlap_guardrails",
            "context_basis_template",
        ]
        for key in expected_keys:
            assert key in report, f"Missing section: {key}"

    def test_context_basis_template_populated(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_full(repo)

        report = run_preflight(
            repo_root=str(repo), artifacts_root=str(tmp_path / "art")
        )

        cb = report["context_basis_template"]
        assert cb["live_repo_scan_used"] is True
        assert len(cb["files_and_reports_considered"]) > 0
        assert len(cb["existing_components_checked"]) > 0


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRendering:
    def test_render_has_all_sections(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_full(repo)

        report = run_preflight(
            repo_root=str(repo), artifacts_root=str(tmp_path / "art")
        )
        md = _render_markdown(report)

        for section in [
            "## 1. Git / Repo State",
            "## 2. Canonical Context",
            "## 3. Integration / Investigation Context",
            "## 4. Command / CLI Map",
            "## 5. Evidence Topology Summary",
            "## 6. Runner / Execution Substrate Summary",
            "## 7. Known Caveats / Unresolved Gaps",
            "## 8. Overlap / Duplication Guardrails",
            "## 9. Context Basis Template",
        ]:
            assert section in md, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Section 10: System Atlas
# ---------------------------------------------------------------------------


class TestSystemAtlas:
    def test_component_families_count(self) -> None:
        """At least 18 component families are defined."""
        assert len(_COMPONENT_FAMILIES) >= 18

    def test_families_have_required_fields(self) -> None:
        required = {"name", "aliases", "primary_files", "purpose", "workflow_edge", "status", "overlap_risk"}
        for family in _COMPONENT_FAMILIES:
            missing = required - set(family.keys())
            assert not missing, f"Family {family.get('name', '?')} missing: {missing}"

    def test_atlas_file_presence_detection(self, tmp_path: Path) -> None:
        """Atlas checks file presence against repo root."""
        # Seed a subset of files
        (tmp_path / "src" / "axiom_core").mkdir(parents=True)
        (tmp_path / "src" / "axiom_core" / "schemas.py").write_text("# stub\n")
        (tmp_path / "src" / "axiom_core" / "orchestrator.py").write_text("# stub\n")

        atlas = _system_atlas(tmp_path)
        assert atlas["family_count"] >= 18

        # schemas.py should be detected as present for the Job/Plan family
        job_family = next(
            f for f in atlas["families"]
            if "Job" in f["name"]
        )
        assert "src/axiom_core/schemas.py" in job_family["files_present"]

    def test_atlas_missing_files_reported(self, tmp_path: Path) -> None:
        """Files that don't exist are reported in files_missing."""
        atlas = _system_atlas(tmp_path)
        total_missing = sum(len(f["files_missing"]) for f in atlas["families"])
        assert total_missing > 0, "Empty repo should have many missing files"

    def test_atlas_markdown_rendering(self, tmp_path: Path) -> None:
        atlas = _system_atlas(tmp_path)
        md = _render_atlas_markdown(atlas)
        assert "# Axiom System Atlas" in md
        assert "Component families:" in md
        # Each family should appear as a heading
        for family in _COMPONENT_FAMILIES:
            assert f"## {family['name']}" in md

    def test_atlas_reference_docs_listed(self, tmp_path: Path) -> None:
        atlas = _system_atlas(tmp_path)
        refs = atlas.get("reference_docs", [])
        assert len(refs) >= 3
        assert any("Duplicate_Alias_Map" in r for r in refs)
        assert any("PR_Purpose_Map" in r for r in refs)

    def test_atlas_data_source_documented(self, tmp_path: Path) -> None:
        atlas = _system_atlas(tmp_path)
        assert "data_source" in atlas
        assert "design pass" in atlas["data_source"].lower()

    def test_atlas_includes_old_foundation_components(self) -> None:
        """Old-foundation scan: pipe/spine/bridge/MCP/agents families are present."""
        all_aliases = {a.lower() for f in _COMPONENT_FAMILIES for a in f["aliases"]}
        for alias in ("pipeclient", "mcplayer", "automationbridge", "run spine", "axiompipeserver"):
            assert alias in all_aliases, f"Old-foundation alias missing from atlas: {alias}"
        all_files = {p for f in _COMPONENT_FAMILIES for p in f["primary_files"]}
        for rel in (
            "src/axiom_core/run_spine.py",
            "src/axiom_core/mcp_layer.py",
            "src/axiom_core/automation_bridge.py",
            "src/axiom_core/pipe_client.py",
        ):
            assert rel in all_files, f"Old-foundation file missing from atlas: {rel}"


# ---------------------------------------------------------------------------
# System Atlas in full preflight run
# ---------------------------------------------------------------------------


class TestPreflightWithAtlas:
    def test_atlas_artifacts_generated(self, tmp_path: Path) -> None:
        """Full preflight generates system_atlas.json + .md alongside preflight."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_full(repo)
        art = tmp_path / "art"

        report = run_preflight(repo_root=str(repo), artifacts_root=str(art))

        assert "system_atlas_json" in report["artifact_paths"]
        assert "system_atlas_markdown" in report["artifact_paths"]

        atlas_json_path = Path(report["artifact_paths"]["system_atlas_json"])
        atlas_md_path = Path(report["artifact_paths"]["system_atlas_markdown"])
        assert atlas_json_path.is_file()
        assert atlas_md_path.is_file()

        # Atlas JSON is valid
        atlas = json.loads(atlas_json_path.read_text(encoding="utf-8"))
        assert atlas["family_count"] >= 18
        assert len(atlas["families"]) >= 18

        # Atlas Markdown has expected content
        atlas_md = atlas_md_path.read_text(encoding="utf-8")
        assert "Axiom System Atlas" in atlas_md

    def test_preflight_report_includes_atlas_summary(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        art = tmp_path / "art"

        report = run_preflight(repo_root=str(repo), artifacts_root=str(art))

        assert "system_atlas_summary" in report
        assert report["system_atlas_summary"]["family_count"] >= 18
