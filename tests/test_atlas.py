"""Tests for the Axiom Atlas read-only viewer (axiom atlas)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.atlas import (
    build_atlas_data,
    render_atlas_html,
    write_atlas,
)
from axiom_core.runner.command_registry import command_names


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Workspace with a chain run, an intake record, and a tracked summary."""
    chain = tmp_path / "artifacts" / "execution_chain" / "run-1"
    chain.mkdir(parents=True)
    (chain / "self_model.json").write_text(
        json.dumps(
            {
                "modules": ["axiom_core.a", "axiom_core.b", "axiom_cli.c"],
                "edges": [
                    ["axiom_core.a", "axiom_core.b"],
                    ["axiom_cli.c", "axiom_core.a"],
                ],
                "metrics": {
                    "module_count": 3,
                    "import_edge_count": 2,
                    "isolated_module_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    intake = tmp_path / "artifacts" / "capability_evidence_intake" / "intake-1"
    intake.mkdir(parents=True)
    (intake / "report.json").write_text(
        json.dumps(
            {
                "intake_id": "intake-1",
                "capability_id": "self-model-build",
                "decision": "accepted",
                "prior_state": {
                    "confidence_level": "very_low",
                    "readiness": "blocked",
                    "score": 0.0,
                },
                "updated_state": {
                    "confidence_level": "very_high",
                    "readiness": "ready",
                    "score": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    runs = tmp_path / "artifacts" / "validation_runs" / "sum-1"
    runs.mkdir(parents=True)
    (runs / "evidence_summary.json").write_text(
        json.dumps(
            {
                "summary_id": "sum-1",
                "generated_at_utc": "2026-01-01T00:00:00+00:00",
                "capability_id": "self-model-build",
                "run_id": "run-1",
                "chain_status": "PASS",
                "quality_verdict": "SUBSTANTIVE",
                "decision": "accepted",
                "git_commit": "abc1234",
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


class TestBuildAtlasData:
    def test_collects_self_model_capabilities_and_summaries(
        self, workspace: Path
    ) -> None:
        data = build_atlas_data(workspace)
        assert data["self_model"]["source_run_id"] == "run-1"
        assert data["self_model"]["modules"] == [
            "axiom_core.a",
            "axiom_core.b",
            "axiom_cli.c",
        ]
        assert len(data["self_model"]["edges"]) == 2
        assert data["self_model"]["metrics"]["module_count"] == 3

        caps = data["capabilities"]
        assert len(caps) == 1
        assert caps[0]["capability_id"] == "self-model-build"
        assert caps[0]["confidence_level"] == "very_high"
        assert caps[0]["readiness"] == "ready"
        assert caps[0]["last_decision"] == "accepted"
        assert caps[0]["decision_counts"] == {"accepted": 1}

        summaries = data["evidence_summaries"]
        assert len(summaries) == 1
        assert summaries[0]["summary_id"] == "sum-1"
        assert summaries[0]["quality_verdict"] == "SUBSTANTIVE"
        assert summaries[0]["path"] == (
            "artifacts/validation_runs/sum-1/evidence_summary.json"
        )

    def test_empty_workspace_is_graceful(self, tmp_path: Path) -> None:
        data = build_atlas_data(tmp_path)
        assert data["self_model"]["modules"] == []
        assert data["self_model"]["edges"] == []
        assert data["capabilities"] == []
        assert data["evidence_summaries"] == []

    def test_no_absolute_paths_in_payload(self, workspace: Path) -> None:
        data = build_atlas_data(workspace)
        blob = json.dumps(data)
        assert str(workspace) not in blob
        for summary in data["evidence_summaries"]:
            assert not Path(summary["path"]).is_absolute()


class TestRenderAtlasHtml:
    def test_embeds_data_and_is_self_contained(self, workspace: Path) -> None:
        data = build_atlas_data(workspace)
        html = render_atlas_html(data)
        assert "__ATLAS_DATA__" not in html
        assert "axiom_core.a" in html
        assert "Axiom Atlas" in html
        # local-first: no external asset or telemetry references
        # (the SVG XML namespace identifier is not a network fetch)
        stripped = html.replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in stripped
        assert "https://" not in stripped
        lowered = html.lower()
        assert "cdn." not in lowered
        assert "<script src=" not in lowered
        assert '<link rel="stylesheet" href="http' not in lowered

    def test_script_injection_is_escaped(self, tmp_path: Path) -> None:
        chain = tmp_path / "artifacts" / "execution_chain" / "run-x"
        chain.mkdir(parents=True)
        (chain / "self_model.json").write_text(
            json.dumps(
                {
                    "modules": ["</script><script>alert(1)</script>"],
                    "edges": [],
                    "metrics": {},
                }
            ),
            encoding="utf-8",
        )
        html = render_atlas_html(build_atlas_data(tmp_path))
        assert "</script><script>alert(1)</script>" not in html


class TestWriteAtlas:
    def test_writes_html_and_data_with_relative_paths(
        self, workspace: Path
    ) -> None:
        html_rel, json_rel = write_atlas(workspace)
        assert html_rel == "artifacts/atlas/atlas.html"
        assert json_rel == "artifacts/atlas/atlas_data.json"
        assert (workspace / html_rel).is_file()
        payload = json.loads(
            (workspace / json_rel).read_text(encoding="utf-8")
        )
        assert payload["schema_version"] == "1.0"

    def test_read_only_over_source_artifacts(self, workspace: Path) -> None:
        before = {
            p: p.read_text(encoding="utf-8")
            for p in workspace.rglob("*.json")
        }
        write_atlas(workspace)
        for path, content in before.items():
            assert path.read_text(encoding="utf-8") == content


class TestGovernance:
    def test_atlas_is_cataloged_in_command_registry(self) -> None:
        assert "atlas" in command_names()
