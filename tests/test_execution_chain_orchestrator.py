"""Tests for the Execution Chain Orchestrator (PR #146 — M4).

These prove the M4 vertical slice: one deterministic capability
(``self-model-build``) moves through the existing execution stack
(ExecutionPlan -> ExecutionStep -> ExecutionAttempt -> ExecutionResult ->
ExecutionArtifact -> Evidence -> ExecutionReport) as a real producer/consumer
chain. The central assertion is *id equality* at every transition:

    downstream.reference(type == Upstream).reference_value == upstream.<id>

Docstring-level "read-only consumption" is explicitly NOT accepted here: every
transition is checked against the real created objects.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.execution_chain_orchestrator import (
    ExecutionChainError,
    ExecutionChainOrchestrator,
)
from axiom_core.self_model_gap_analysis import SelfModelGapAnalyzer
from click.testing import CliRunner


@pytest.fixture
def orchestrator(tmp_path: Any) -> ExecutionChainOrchestrator:
    return ExecutionChainOrchestrator(
        repo_root=".", artifacts_root=str(tmp_path / "artifacts")
    )


def _ref_value(obj: dict[str, Any], reference_type: str) -> str:
    for ref in obj.get("references", []):
        if ref.get("reference_type") == reference_type:
            return str(ref.get("reference_value", ""))
    return ""


# ---------------------------------------------------------------------------
# Full chain + status
# ---------------------------------------------------------------------------


def test_full_chain_runs_and_passes(orchestrator: ExecutionChainOrchestrator) -> None:
    trace = orchestrator.run("self-model-build")
    assert trace.status == "PASS"
    for stage_id in (
        trace.plan_id,
        trace.step_id,
        trace.attempt_id,
        trace.result_id,
        trace.artifact_id,
        trace.evidence_id,
        trace.report_id,
    ):
        assert stage_id, "every stage must yield a real id"
    assert trace.capability_output["module_count"] > 0
    assert trace.capability_output["import_edge_count"] > 0


# ---------------------------------------------------------------------------
# ID-flow equality, transition by transition (the core M4 proof)
# ---------------------------------------------------------------------------


def test_id_flow_equality_per_transition(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    objects = trace.objects

    # Each downstream object's typed reference must equal the real upstream id.
    assert _ref_value(objects["step"], "PLAN") == trace.plan_id
    assert _ref_value(objects["attempt"], "STEP") == trace.step_id
    assert _ref_value(objects["result"], "ATTEMPT") == trace.attempt_id
    assert _ref_value(objects["artifact"], "RESULT") == trace.result_id
    assert _ref_value(objects["report"], "RESULT") == trace.result_id
    assert _ref_value(objects["report"], "ARTIFACT") == trace.artifact_id

    # And it must NOT be a placeholder: the reference value is a real uuid id.
    assert _ref_value(objects["step"], "PLAN") != ""
    assert trace.plan_id != trace.step_id != trace.attempt_id


def test_transitions_record_each_edge(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    edges = {
        (t.upstream_stage, t.downstream_stage, t.reference_type): t
        for t in trace.transitions
    }
    assert ("ExecutionPlan", "ExecutionStep", "PLAN") in edges
    assert ("ExecutionStep", "ExecutionAttempt", "STEP") in edges
    assert ("ExecutionAttempt", "ExecutionResult", "ATTEMPT") in edges
    assert ("ExecutionResult", "ExecutionArtifact", "RESULT") in edges
    assert ("ExecutionResult", "ExecutionReport", "RESULT") in edges
    assert ("ExecutionArtifact", "ExecutionReport", "ARTIFACT") in edges
    assert all(t.ok for t in trace.transitions)


# ---------------------------------------------------------------------------
# Evidence + report references
# ---------------------------------------------------------------------------


def test_evidence_references_result_and_artifact(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    refs = trace.evidence_reference["references"]
    assert refs["result_id"] == trace.result_id
    assert refs["artifact_id"] == trace.artifact_id
    assert refs["capability_id"] == trace.capability_id


def test_report_references_result_artifact_evidence(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    report = trace.objects["report"]
    assert _ref_value(report, "RESULT") == trace.result_id
    assert _ref_value(report, "ARTIFACT") == trace.artifact_id
    assert _ref_value(report, "FILE") == trace.evidence_id
    assert report["report_type"] == "FINAL_SUMMARY"
    assert report["status"] == "COMPLETE"
    assert report["sections"], "report must have at least one section"


# ---------------------------------------------------------------------------
# End-to-end trace resolution
# ---------------------------------------------------------------------------


def test_end_to_end_trace_resolves(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    resolved = trace.resolve_chain()
    assert resolved == [
        trace.report_id,
        trace.artifact_id,
        trace.result_id,
        trace.attempt_id,
        trace.step_id,
        trace.plan_id,
    ]
    assert len(set(resolved)) == len(resolved), "ids must be distinct"


def test_records_persisted_and_resolvable_from_disk(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    # Proves the records are NOT fabricated only inside the orchestrator
    # response: the terminal report resolves back to the plan by re-reading the
    # engines' persisted report.json files from artifacts_root.
    trace = orchestrator.run("self-model-build")
    resolved = orchestrator.resolve_persisted(trace)
    assert resolved == [
        trace.report_id,
        trace.artifact_id,
        trace.result_id,
        trace.attempt_id,
        trace.step_id,
        trace.plan_id,
    ]


# ---------------------------------------------------------------------------
# Missing-upstream handling
# ---------------------------------------------------------------------------


def test_missing_upstream_empty_container_raises() -> None:
    with pytest.raises(ExecutionChainError):
        ExecutionChainOrchestrator._extract({"plans": []}, "plans", "plan_id")


def test_missing_upstream_missing_id_raises() -> None:
    with pytest.raises(ExecutionChainError):
        ExecutionChainOrchestrator._extract(
            {"plans": [{"plan_id": ""}]}, "plans", "plan_id"
        )


def test_unsupported_capability_raises(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    with pytest.raises(ExecutionChainError):
        orchestrator.run("set-parameter-value")


def test_broken_id_flow_is_rejected(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    # If a downstream reference does not match its upstream, the guard fires.
    trace = orchestrator.run("self-model-build")
    trace.transitions[0].reference_value = "tampered"
    with pytest.raises(ExecutionChainError):
        orchestrator._assert_id_flow(trace)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_output(orchestrator: ExecutionChainOrchestrator) -> None:
    first = orchestrator.run("self-model-build").deterministic_view()
    second = orchestrator.run("self-model-build").deterministic_view()
    assert first == second


def test_code_inventory_alias_runs(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("code-inventory")
    # Both names resolve to the same canonical capability id and pass.
    assert trace.capability_id == "self-model-build"
    assert trace.status == "PASS"


# ---------------------------------------------------------------------------
# M2 / M3 hooks recorded (not implemented)
# ---------------------------------------------------------------------------


def test_m2_and_m3_hooks_recorded(
    orchestrator: ExecutionChainOrchestrator,
) -> None:
    trace = orchestrator.run("self-model-build")
    assert trace.m2_hook["evidence_produced"]["evidence_id"] == trace.evidence_id
    assert "promotion_status" in trace.m2_hook["could_affect"]
    assert trace.m3_hook["layer"] == "self_model"
    assert "code-inventory" in trace.m3_hook["consumes"]


# ---------------------------------------------------------------------------
# Gap-analysis before/after: the metric responds to real adjacent wiring
# ---------------------------------------------------------------------------


def _chain_graph_report(edges: list[tuple[str, str]]) -> dict[str, Any]:
    stages = [
        "axiom_core.execution_plan",
        "axiom_core.execution_step",
        "axiom_core.execution_attempt_v2",
        "axiom_core.execution_result",
        "axiom_core.execution_artifact",
        "axiom_core.execution_report",
    ]
    touched = {e[0] for e in edges} | {e[1] for e in edges}
    return {
        "report_id": "fixture",
        "nodes": [{"source_id": s} for s in stages],
        "edges": [
            {"source_node_id": a, "target_node_id": b} for a, b in edges
        ],
        "orphan_node_ids": [s for s in stages if s not in touched],
    }


def _unwired_count(report: dict[str, Any]) -> int:
    analysis = SelfModelGapAnalyzer(report=report).analyze()
    return sum(
        1
        for g in analysis["gaps"]
        if g["gap_type"] == "declared_but_unwired_chains"
    )


def test_gap_metric_responds_to_real_wiring() -> None:
    # Before: stages present but no adjacent import edge -> 5 unwired transitions.
    before = _chain_graph_report(edges=[])
    assert _unwired_count(before) == 5

    # After: one real adjacent edge per transition -> 0 unwired transitions.
    wired = [
        ("axiom_core.execution_step", "axiom_core.execution_plan"),
        ("axiom_core.execution_attempt_v2", "axiom_core.execution_step"),
        ("axiom_core.execution_result", "axiom_core.execution_attempt_v2"),
        ("axiom_core.execution_artifact", "axiom_core.execution_result"),
        ("axiom_core.execution_report", "axiom_core.execution_artifact"),
    ]
    after = _chain_graph_report(edges=wired)
    assert _unwired_count(after) == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_execution_chain_run_json(tmp_path: Any) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "execution-chain-run",
            "--capability",
            "self-model-build",
            "--artifacts-root",
            str(tmp_path / "artifacts"),
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "PASS"
    for key in (
        "plan_id",
        "step_id",
        "attempt_id",
        "result_id",
        "artifact_id",
        "evidence_id",
        "report_id",
    ):
        assert payload[key], f"{key} must be present in CLI json output"
    # Trace resolves report -> ... -> plan via the emitted transitions.
    assert all(t["ok"] for t in payload["transitions"])


def test_cli_execution_chain_run_console(tmp_path: Any) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "execution-chain-run",
            "--artifacts-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ID-flow status" in result.output
    assert "PASS" in result.output
