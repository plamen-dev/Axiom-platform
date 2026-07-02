"""Tests for Knowledge Graph Auto-Ingest v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.graph_auto_ingest import GraphAutoIngestEngine

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _seed_intake(root, intake_id="intake-1", capability_id="self-model-build"):
    _write(
        root / "capability_evidence_intake" / intake_id / "report.json",
        {
            "intake_id": intake_id,
            "capability_id": capability_id,
            "decision": "accepted",
            "evidence_outcome": "pass",
            "state_changed": True,
            "evidence_path": "artifacts/execution_chain/run-1/evidence.json",
            "updated_state": {"confidence_level": "medium"},
        },
    )


def _seed_chain_run(root, run_dir="run-1", capability_id="self-model-build"):
    _write(
        root / "execution_chain" / run_dir / "evidence.json",
        {
            "evidence_id": f"ev-{run_dir}",
            "summary": "chain evidence",
            "metrics": {"module_count": 168},
            "quality": {"verdict": "SUBSTANTIVE"},
            "references": {"capability_id": capability_id},
        },
    )


def _seed_validation_run(root, run_id="clivr_1"):
    _write(
        root / "validation_evidence" / run_id / "validation_run.json",
        {
            "run_id": run_id,
            "plan_id": "m2_evidence_promotion",
            "name": "m2-smoke",
            "status": "passed",
            "passed": True,
            "commands_total": 2,
            "commands_passed": 2,
            "commands_failed": 0,
        },
    )


def _seed_github_import(root, report_id="gh-1", pr_number=1, canonical=112):
    _write(
        root / "github_metadata_import" / report_id / "report.json",
        {
            "report_id": report_id,
            "repository": "plamen-dev/Axiom-platform",
            "repository_pr_number": pr_number,
            "global_capability_number": canonical,
            "metadata_import": {
                "pr": {
                    "title": f"PR #{canonical} — Framework v1",
                    "author": "devin",
                    "status": "merged",
                    "merged_at": "2026-06-23T00:00:00Z",
                }
            },
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngest:
    def test_ingests_all_sources(self, tmp_path) -> None:
        _seed_intake(tmp_path)
        _seed_chain_run(tmp_path)
        _seed_validation_run(tmp_path)
        _seed_github_import(tmp_path)

        engine = GraphAutoIngestEngine(artifacts_root=str(tmp_path))
        summary = engine.ingest()

        assert summary["source_counts"] == {
            "evidence_intakes": 1,
            "chain_runs": 1,
            "validation_runs": 1,
            "github_pr_imports": 1,
        }
        # intake VALIDATION + capability + chain ARTIFACT (+ shared
        # capability deduped) + validation run + PR event = 5 nodes
        assert summary["node_count"] == 5
        assert summary["node_type_counts"] == {
            "ARTIFACT": 1,
            "CAPABILITY": 1,
            "EVENT": 1,
            "VALIDATION": 2,
        }
        assert summary["edge_type_counts"] == {
            "HAS_ARTIFACT": 1,
            "VALIDATES": 1,
        }
        assert summary["skipped_count"] == 0

    def test_shared_capability_node_deduped(self, tmp_path) -> None:
        _seed_intake(tmp_path, intake_id="intake-1")
        _seed_intake(tmp_path, intake_id="intake-2")

        summary = GraphAutoIngestEngine(
            artifacts_root=str(tmp_path)
        ).ingest()
        assert summary["node_type_counts"]["CAPABILITY"] == 1
        assert summary["node_type_counts"]["VALIDATION"] == 2
        assert summary["edge_type_counts"]["VALIDATES"] == 2

    def test_reruns_produce_same_structure(self, tmp_path) -> None:
        _seed_intake(tmp_path)
        _seed_chain_run(tmp_path)

        engine = GraphAutoIngestEngine(artifacts_root=str(tmp_path))
        first = engine.ingest()
        second = engine.ingest()

        assert first["report_id"] != second["report_id"]
        for key in (
            "source_counts",
            "node_count",
            "edge_count",
            "node_type_counts",
            "edge_type_counts",
        ):
            assert first[key] == second[key]

        first_report = engine._graph_engine.get_report(first["report_id"])
        second_report = engine._graph_engine.get_report(second["report_id"])
        assert [n["node_id"] for n in first_report["nodes"]] == [
            n["node_id"] for n in second_report["nodes"]
        ]
        assert [e["edge_id"] for e in first_report["edges"]] == [
            e["edge_id"] for e in second_report["edges"]
        ]

    def test_malformed_artifact_skipped_not_fatal(self, tmp_path) -> None:
        _seed_intake(tmp_path)
        bad = tmp_path / "execution_chain" / "bad-run" / "evidence.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("{not json", encoding="utf-8")

        summary = GraphAutoIngestEngine(
            artifacts_root=str(tmp_path)
        ).ingest()
        assert summary["source_counts"]["evidence_intakes"] == 1
        assert summary["skipped_count"] == 1
        assert "bad-run" in summary["skipped"][0]["file"]

    def test_missing_source_dirs_yield_empty_graph(self, tmp_path) -> None:
        summary = GraphAutoIngestEngine(
            artifacts_root=str(tmp_path)
        ).ingest()
        assert summary["node_count"] == 0
        assert summary["edge_count"] == 0
        assert summary["skipped_count"] == 0

    def test_intake_missing_ids_skipped(self, tmp_path) -> None:
        _write(
            tmp_path / "capability_evidence_intake" / "x" / "report.json",
            {"intake_id": "", "capability_id": ""},
        )
        summary = GraphAutoIngestEngine(
            artifacts_root=str(tmp_path)
        ).ingest()
        assert summary["source_counts"]["evidence_intakes"] == 0

    def test_github_pr_node_carries_canonical_number(self, tmp_path) -> None:
        _seed_github_import(tmp_path, pr_number=1, canonical=112)

        engine = GraphAutoIngestEngine(artifacts_root=str(tmp_path))
        summary = engine.ingest()
        report = engine._graph_engine.get_report(summary["report_id"])
        node = report["nodes"][0]
        assert node["node_type"] == "EVENT"
        assert node["raw_payload"]["global_capability_number"] == 112
        assert node["raw_payload"]["repository_pr_number"] == 1

    def test_upstream_artifacts_not_mutated(self, tmp_path) -> None:
        _seed_intake(tmp_path)
        path = (
            tmp_path
            / "capability_evidence_intake"
            / "intake-1"
            / "report.json"
        )
        before = path.read_text(encoding="utf-8")
        GraphAutoIngestEngine(artifacts_root=str(tmp_path)).ingest()
        assert path.read_text(encoding="utf-8") == before


class TestErrors:
    def test_missing_artifacts_root_is_created_lazily(self, tmp_path) -> None:
        root = tmp_path / "artifacts"
        summary = GraphAutoIngestEngine(artifacts_root=str(root)).ingest()
        assert summary["node_count"] == 0

    @pytest.mark.parametrize("count", [3])
    def test_multiple_chain_runs(self, tmp_path, count: int) -> None:
        for i in range(count):
            _seed_chain_run(tmp_path, run_dir=f"run-{i}")
        summary = GraphAutoIngestEngine(
            artifacts_root=str(tmp_path)
        ).ingest()
        assert summary["source_counts"]["chain_runs"] == count
        assert summary["node_type_counts"]["ARTIFACT"] == count
        assert summary["node_type_counts"]["CAPABILITY"] == 1
