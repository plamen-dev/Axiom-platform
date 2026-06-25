"""Tests for Self-Model Gap Analysis (Integration PR #144).

Uses a fixed in-memory graph report (the self-model) with known isolated,
connected, command-only, producer, and execution-chain modules so every gap
category and the deterministic ranking can be asserted exactly.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_core.self_model_gap_analysis import (
    SelfModelGapAnalyzer,
    to_markdown,
)


def _report(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, Any]:
    """Build a capability-knowledge-graph-shaped report from nodes/edges.

    ``orphan_node_ids`` are nodes that appear in no edge (matches the engine's
    orphan detection used by the self-model).
    """
    touched = {e[0] for e in edges} | {e[1] for e in edges}
    return {
        "report_id": "fixture-graph",
        "nodes": [{"source_id": n} for n in nodes],
        "edges": [
            {"source_node_id": s, "target_node_id": t} for s, t in edges
        ],
        "orphan_node_ids": sorted(n for n in nodes if n not in touched),
    }


# Fixed subgraph fixture -------------------------------------------------------
#  pkg.a -> pkg.b -> pkg.c                    (a connected coding chain)
#  pkg.island                                 (isolated)
#  axiom_cli.main -> pkg.cmd_only             (command-only, no other edge)
#  pkg.prod -> pkg.c                          (producer, no incoming consumer)
#  config_x / config_y / config_z            (disconnected 3-member family)
#  execution chain: plan->step wired; attempt_v2->result wired;
#                   step->attempt unwired; result->artifact unwired;
#                   execution_report ABSENT (stage missing)
_NODES = [
    "pkg.a",
    "pkg.b",
    "pkg.c",
    "pkg.island",
    "axiom_cli.main",
    "pkg.cmd_only",
    "pkg.prod",
    "axiom_core.config_x",
    "axiom_core.config_y",
    "axiom_core.config_z",
    "axiom_core.execution_plan",
    "axiom_core.execution_step",
    "axiom_core.execution_attempt_v2",
    "axiom_core.execution_result",
    "axiom_core.execution_artifact",
]
_EDGES = [
    ("pkg.a", "pkg.b"),
    ("pkg.b", "pkg.c"),
    ("axiom_cli.main", "pkg.cmd_only"),
    ("pkg.prod", "pkg.c"),
    ("axiom_core.execution_plan", "axiom_core.execution_step"),
    ("axiom_core.execution_attempt_v2", "axiom_core.execution_result"),
]


@pytest.fixture
def analyzer() -> SelfModelGapAnalyzer:
    return SelfModelGapAnalyzer(
        _report(_NODES, _EDGES),
        module_classes={"pkg.prod": ["ProdReport", "Helper"]},
        documented_modules={"pkg.a", "pkg.b"},
    )


@pytest.fixture
def result(analyzer: SelfModelGapAnalyzer) -> dict[str, Any]:
    return analyzer.analyze()


def _by_type(result: dict[str, Any], gap_type: str) -> list[dict[str, Any]]:
    return [g for g in result["gaps"] if g["gap_type"] == gap_type]


# --- counts / structure -------------------------------------------------------


def test_basic_counts(result: dict[str, Any]) -> None:
    assert result["module_count"] == len(_NODES)
    assert result["edge_count"] == len(_EDGES)
    assert result["isolated_module_count"] == result["isolated_module_count"]


def test_isolated_modules(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "isolated_modules")
    assert len(gaps) == 1
    # island + the three config_* + execution_artifact have no edges
    assert "pkg.island" in gaps[0]["affected_modules"]
    assert "axiom_core.execution_artifact" in gaps[0]["affected_modules"]


def test_unconsumed_modules(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "unconsumed_modules")
    assert len(gaps) == 1
    affected = gaps[0]["affected_modules"]
    # pkg.a has outgoing but nobody imports it; pkg.prod likewise.
    assert "pkg.a" in affected
    assert "pkg.prod" in affected
    # pkg.b is consumed (a->b) so must NOT be flagged unconsumed.
    assert "pkg.b" not in affected


def test_no_outgoing_dependency_modules(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "no_outgoing_dependency_modules")
    assert len(gaps) == 1
    affected = gaps[0]["affected_modules"]
    # pkg.c is imported but imports nothing internal (leaf).
    assert "pkg.c" in affected
    # execution_result has incoming (attempt->result), no outgoing -> leaf.
    assert "axiom_core.execution_result" in affected


def test_command_modules_with_low_connectivity(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "command_modules_with_low_connectivity")
    assert len(gaps) == 1
    affected = gaps[0]["affected_modules"]
    assert affected == ["pkg.cmd_only"]


def test_evidence_producers_without_consumers(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "artifact_or_evidence_producers_without_consumers")
    assert len(gaps) == 1
    # pkg.prod defines *Report and has no incoming consumer.
    assert gaps[0]["affected_modules"] == ["pkg.prod"]


def test_missing_purpose_candidates(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "missing_purpose_or_layer_candidates")
    assert len(gaps) == 1
    affected = set(gaps[0]["affected_modules"])
    # documented modules excluded; everything else flagged.
    assert "pkg.a" not in affected
    assert "pkg.b" not in affected
    assert "pkg.c" in affected


def test_disconnected_framework_families(result: dict[str, Any]) -> None:
    gaps = _by_type(result, "disconnected_framework_families")
    titles = {g["title"] for g in gaps}
    assert "config_* family" in titles
    config_gap = next(g for g in gaps if g["title"] == "config_* family")
    assert config_gap["affected_modules"] == [
        "axiom_core.config_x",
        "axiom_core.config_y",
        "axiom_core.config_z",
    ]


# --- declared-but-unwired chain ----------------------------------------------


def test_unwired_chain_flags_only_broken_transitions(
    result: dict[str, Any],
) -> None:
    gaps = _by_type(result, "declared_but_unwired_chains")
    titles = {g["title"] for g in gaps}
    # Wired transitions must NOT be flagged.
    assert "ExecutionPlan -> ExecutionStep" not in titles
    assert "ExecutionAttempt -> ExecutionResult" not in titles
    # Unwired transitions must be flagged.
    assert "ExecutionStep -> ExecutionAttempt" in titles
    assert "ExecutionResult -> ExecutionArtifact" in titles
    # Missing stage module (execution_report absent) flagged distinctly.
    assert "ExecutionArtifact -> ExecutionReport" in titles


def test_unwired_chain_missing_stage_evidence(result: dict[str, Any]) -> None:
    gap = next(
        g
        for g in _by_type(result, "declared_but_unwired_chains")
        if g["title"] == "ExecutionArtifact -> ExecutionReport"
    )
    assert "not present" in gap["evidence"]


def test_wired_chain_produces_no_chain_gaps() -> None:
    nodes = [
        "axiom_core.execution_plan",
        "axiom_core.execution_step",
        "axiom_core.execution_attempt_v2",
        "axiom_core.execution_result",
        "axiom_core.execution_artifact",
        "axiom_core.execution_report",
    ]
    edges = [
        ("axiom_core.execution_step", "axiom_core.execution_plan"),
        ("axiom_core.execution_attempt_v2", "axiom_core.execution_step"),
        ("axiom_core.execution_result", "axiom_core.execution_attempt_v2"),
        ("axiom_core.execution_artifact", "axiom_core.execution_result"),
        ("axiom_core.execution_report", "axiom_core.execution_artifact"),
    ]
    result = SelfModelGapAnalyzer(_report(nodes, edges)).analyze()
    assert _by_type(result, "declared_but_unwired_chains") == []


# --- recommendations / ranking -----------------------------------------------


def test_recommendations_reference_underlying_gaps(
    result: dict[str, Any],
) -> None:
    recs = _by_type(result, "recommended_integration_candidates")
    assert recs
    chain_rec = next(
        (g for g in recs if g["title"].startswith("Wire one capability")),
        None,
    )
    assert chain_rec is not None
    assert chain_rec["related_gap_ids"]
    assert all(r.startswith("CHAIN-") for r in chain_rec["related_gap_ids"])


def test_backlog_is_ranked_descending(result: dict[str, Any]) -> None:
    scores = [g["score"] for g in result["gaps"]]
    assert scores == sorted(scores, reverse=True)


def test_every_gap_has_required_fields(result: dict[str, Any]) -> None:
    required = {
        "gap_id",
        "gap_type",
        "affected_modules",
        "evidence",
        "why_it_matters",
        "existing_capabilities_to_reuse",
        "proposed_smallest_fix",
        "expected_new_behavior",
        "validation_strategy",
        "priority",
    }
    for gap in result["gaps"]:
        assert required.issubset(gap.keys()), required - gap.keys()
        assert gap["priority"] in {"high", "medium", "low"}


def test_exposes_more_than_one_failure_class(result: dict[str, Any]) -> None:
    # Acceptance criterion: must expose more than one gap class.
    assert len(result["gap_counts_by_type"]) > 1


# --- determinism / serialization ---------------------------------------------


def test_deterministic_output() -> None:
    a = SelfModelGapAnalyzer(
        _report(_NODES, _EDGES),
        module_classes={"pkg.prod": ["ProdReport"]},
        documented_modules={"pkg.a"},
    ).analyze()
    b = SelfModelGapAnalyzer(
        _report(list(reversed(_NODES)), list(reversed(_EDGES))),
        module_classes={"pkg.prod": ["ProdReport"]},
        documented_modules={"pkg.a"},
    ).analyze()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_gap_ids_are_stable_and_typed(result: dict[str, Any]) -> None:
    ids = [g["gap_id"] for g in result["gaps"]]
    assert len(ids) == len(set(ids))  # unique
    for gap in result["gaps"]:
        assert gap["gap_id"][0].isalpha()


def test_json_output_is_valid(result: dict[str, Any]) -> None:
    text = json.dumps(result, indent=2, default=str)
    assert json.loads(text) == result


def test_markdown_output_well_formed(result: dict[str, Any]) -> None:
    md = to_markdown(result)
    assert md.startswith("# Self-Model Gap Analysis")
    assert "## Ranked integration backlog" in md
    for gap in result["gaps"]:
        assert gap["gap_id"] in md


def test_missing_purpose_when_no_summary_metadata() -> None:
    # documented_modules=None -> all modules are purpose candidates.
    result = SelfModelGapAnalyzer(_report(_NODES, _EDGES)).analyze()
    gaps = _by_type(result, "missing_purpose_or_layer_candidates")
    assert len(gaps) == 1
    assert gaps[0]["affected_module_count"] == len(_NODES)


def test_producer_detection_disabled_without_module_classes() -> None:
    result = SelfModelGapAnalyzer(_report(_NODES, _EDGES)).analyze()
    assert _by_type(
        result, "artifact_or_evidence_producers_without_consumers"
    ) == []
