"""Tests for the Promotion Eligibility Engine (PR #30).

Eligibility/governance only: these prove the engine can decide whether a
capability is promotion-eligible by summarizing the Capability State Registry,
Validation Registry, Command Registry, and failure-classification artifacts into
a deterministic decision. Nothing here promotes a capability, mutates state or a
registry, executes, retries, or schedules anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from axiom_cli.main import cli
from axiom_core.runner.capability_state import CapabilityStateRegistry
from axiom_core.runner.command_registry import (
    CommandClass,
    SafetyLevel,
    get_command,
)
from axiom_core.runner.promotion_eligibility import (
    PromotionCriteria,
    PromotionDecision,
    PromotionEligibilityEngine,
    PromotionEvidenceSummary,
    PromotionStatus,
    promotion_run_id,
    write_promotion_decisions,
)
from click.testing import CliRunner

TS = "2026-05-06T12:00:00+00:00"


# --- helpers ---------------------------------------------------------------


def _exec_bundle(base: Path, capability: str, run_id: str, outcome: str,
                 *, reason: str = "", classification: dict | None = None) -> Path:
    run_dir = base / capability / run_id
    (run_dir / "command_outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "pass_fail.json").write_text(
        json.dumps({"outcome": outcome, "capability_name": capability}),
        encoding="utf-8")
    (run_dir / "capability_result.json").write_text(
        json.dumps({
            "capability_name": capability,
            "outcome": outcome,
            "started_at": TS,
            "finished_at": TS,
            "reason": reason,
        }),
        encoding="utf-8")
    if classification is not None:
        (run_dir / "failure_classification.json").write_text(
            json.dumps(classification), encoding="utf-8")
    return run_dir


def _registry(tmp_path: Path) -> CapabilityStateRegistry:
    return CapabilityStateRegistry(
        capability_runs_base=tmp_path / "capability_runs",
        validation_evidence_base=tmp_path / "validation_evidence",
    )


def _engine(tmp_path: Path, criteria: PromotionCriteria | None = None
            ) -> PromotionEligibilityEngine:
    return PromotionEligibilityEngine(
        state_registry=_registry(tmp_path), criteria=criteria)


def _cli_base(tmp_path: Path) -> list[str]:
    return [
        "--db-path", str(tmp_path / "absent.db"),
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ]


# --- engine: core statuses -------------------------------------------------


def test_readonly_capability_with_passing_evidence_is_eligible(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.ELIGIBLE
    assert decision.eligible is True
    assert decision.evidence.successful_runs == 1
    assert decision.evidence.is_mutation is False
    assert decision.blockers == []


def test_missing_evidence_is_needs_more_evidence(tmp_path):
    # InventoryModel is known/executable but has no evidence bundle.
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.NEEDS_MORE_EVIDENCE
    assert decision.eligible is False
    assert any(b.code == "no_evidence_bundle" for b in decision.blockers)


def test_insufficient_successes_is_needs_more_evidence(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    criteria = PromotionCriteria(minimum_successful_runs=2)
    decision = _engine(tmp_path, criteria).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.NEEDS_MORE_EVIDENCE
    assert any(b.code == "insufficient_successes" for b in decision.blockers)


def test_recent_failure_is_failed_recently(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "failed")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.FAILED_RECENTLY
    assert decision.eligible is False


def test_blocked_status_is_blocked(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "blocked")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.BLOCKED


def test_unsupported_status_is_blocked(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "unsupported")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.BLOCKED


def test_refused_outcome_is_policy_refused(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "refused")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.POLICY_REFUSED


def test_mutation_capability_is_policy_refused(tmp_path):
    # SetParameterValue is a mutation capability — not eligible in v1 even with
    # a passing run.
    _exec_bundle(tmp_path / "capability_runs", "SetParameterValue", "crun_1",
                 "passed")
    decision = _engine(tmp_path).evaluate("SetParameterValue")
    assert decision.status is PromotionStatus.POLICY_REFUSED
    assert decision.eligible is False
    assert decision.evidence.is_mutation is True
    assert any(b.code == "mutation_not_eligible" for b in decision.blockers)


def test_unknown_capability_is_unknown(tmp_path):
    decision = _engine(tmp_path).evaluate("NopeNotReal")
    assert decision.status is PromotionStatus.UNKNOWN
    assert decision.eligible is False
    assert decision.evidence.known is False
    assert any(b.code == "unknown_capability" for b in decision.blockers)


# --- engine: failure classification consumption ----------------------------


def test_policy_violation_classification_blocks(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed",
                 classification={"category": "policy_violation", "severity": "error"})
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.BLOCKED
    assert decision.evidence.failure_classification_present is True
    assert decision.evidence.latest_failure_category == "policy_violation"
    assert any(b.code == "policy_violation" for b in decision.blockers)


def test_critical_classification_blocks(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed",
                 classification={"category": "transport_failed", "severity": "critical"})
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.BLOCKED
    assert any(b.code == "critical_failure" for b in decision.blockers)


def test_missing_classification_handled_conservatively(tmp_path):
    # No failure_classification.json next to a passing bundle: the engine does
    # not crash and does not invent a blocker — a clean pass stays eligible.
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.ELIGIBLE
    assert decision.evidence.failure_classification_present is False
    assert decision.evidence.latest_failure_category is None


def test_benign_classification_does_not_block(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed",
                 classification={"category": "passed", "severity": "info"})
    decision = _engine(tmp_path).evaluate("InventoryModel")
    assert decision.status is PromotionStatus.ELIGIBLE
    assert decision.evidence.failure_classification_present is True


def test_unreadable_classification_is_ignored(tmp_path):
    bundle = _exec_bundle(tmp_path / "capability_runs", "InventoryModel",
                          "crun_1", "passed")
    (bundle / "failure_classification.json").write_text("{not json", encoding="utf-8")
    decision = _engine(tmp_path).evaluate("InventoryModel")
    # Conservative: unreadable classification is ignored, decision still computed.
    assert decision.status is PromotionStatus.ELIGIBLE
    assert decision.evidence.failure_classification_present is False


# --- engine: --all + determinism ------------------------------------------


def test_evaluate_all_returns_a_decision_per_capability(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    decisions = _engine(tmp_path).evaluate_all()
    by_name = {d.capability_name: d for d in decisions}
    assert "InventoryModel" in by_name
    assert "SetParameterValue" in by_name
    assert by_name["InventoryModel"].status is PromotionStatus.ELIGIBLE
    assert by_name["SetParameterValue"].status is PromotionStatus.POLICY_REFUSED
    assert all(isinstance(d, PromotionDecision) for d in decisions)


def test_decision_is_deterministic(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    engine = _engine(tmp_path)
    a = engine.evaluate("InventoryModel").to_dict()
    b = engine.evaluate("InventoryModel").to_dict()
    a.pop("evaluated_at")
    b.pop("evaluated_at")
    assert a == b


# --- output writing --------------------------------------------------------


def test_write_promotion_decisions_writes_json_and_md(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    decisions = _engine(tmp_path).evaluate_all()
    out = tmp_path / "pc"
    json_path, md_path = write_promotion_decisions(decisions, out_dir=out)
    assert json_path.name == "promotion_decision.json"
    assert md_path.name == "promotion_decision.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["count"] == len(decisions)
    assert "InventoryModel" in payload["eligible"]
    assert isinstance(payload["status_counts"], dict)
    md = md_path.read_text(encoding="utf-8")
    assert "# Promotion Eligibility Decision" in md
    assert "InventoryModel" in md


def test_json_and_md_share_one_generated_at(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    decisions = _engine(tmp_path).evaluate_all()
    json_path, md_path = write_promotion_decisions(decisions, out_dir=tmp_path / "pc")
    generated_at = json.loads(json_path.read_text(encoding="utf-8"))["generated_at"]
    assert f"**Generated at:** {generated_at}" in md_path.read_text(encoding="utf-8")


def test_evidence_summary_round_trips(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    summary = _engine(tmp_path).evaluate("InventoryModel").evidence
    assert isinstance(summary, PromotionEvidenceSummary)
    d = summary.to_dict()
    assert d["capability_name"] == "InventoryModel"
    assert d["known"] is True


def test_promotion_run_id_is_filesystem_safe():
    rid = promotion_run_id("Inventory/Model:1")
    assert "/" not in rid and ":" not in rid
    assert rid.startswith("pcheck_")


# --- no-mutation guarantees ------------------------------------------------


def test_engine_does_not_mutate_evidence_bundle(tmp_path):
    bundle = _exec_bundle(tmp_path / "capability_runs", "InventoryModel",
                          "crun_1", "passed")
    before = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
              for p in sorted(bundle.iterdir()) if p.is_file()}
    _engine(tmp_path).evaluate("InventoryModel")
    after = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
             for p in sorted(bundle.iterdir()) if p.is_file()}
    assert before == after
    # No promotion artifacts leaked into the evidence bundle.
    assert not (bundle / "promotion_decision.json").exists()


def test_engine_does_not_create_database(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    _engine(tmp_path).evaluate_all()
    assert not (tmp_path / "absent.db").exists()


# --- CLI -------------------------------------------------------------------


def test_cli_single_capability(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    res = CliRunner().invoke(cli, [
        "promotion-check", "--capability", "InventoryModel",
        "--out", str(tmp_path / "pc"),
    ] + _cli_base(tmp_path))
    assert res.exit_code == 0, res.output
    assert "eligible" in res.output
    assert (tmp_path / "pc" / "promotion_decision.json").is_file()
    assert (tmp_path / "pc" / "promotion_decision.md").is_file()


def test_cli_single_capability_json_is_valid(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    res = CliRunner().invoke(cli, [
        "promotion-check", "--capability", "InventoryModel", "--json", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["capability_name"] == "InventoryModel"
    assert payload["status"] == "eligible"


def test_cli_all_json_is_valid(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    res = CliRunner().invoke(cli, [
        "promotion-check", "--all", "--json", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    names = {d["capability_name"] for d in payload["decisions"]}
    assert {"InventoryModel", "SetParameterValue"}.issubset(names)


def test_cli_all_table(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    res = CliRunner().invoke(cli, [
        "promotion-check", "--all", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 0, res.output
    assert "InventoryModel" in res.output


def test_cli_unknown_capability_exits_nonzero(tmp_path):
    res = CliRunner().invoke(cli, [
        "promotion-check", "--capability", "NopeNotReal", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 2, res.output


def test_cli_requires_exactly_one_target(tmp_path):
    # Neither --capability nor --all.
    res = CliRunner().invoke(cli, ["promotion-check", "--no-write"]
                             + _cli_base(tmp_path))
    assert res.exit_code == 2
    # Both --capability and --all.
    res = CliRunner().invoke(cli, [
        "promotion-check", "--capability", "InventoryModel", "--all", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 2


def test_cli_does_not_mutate_state_by_default(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1", "passed")
    res = CliRunner().invoke(cli, [
        "promotion-check", "--all", "--no-write",
    ] + _cli_base(tmp_path))
    assert res.exit_code == 0, res.output
    # Read-only: no SQLite db created, no artifacts dir created.
    assert not (tmp_path / "absent.db").exists()


# --- command registry integration -----------------------------------------


def test_promotion_check_is_cataloged_read_only_safe():
    cmd = get_command("promotion-check")
    assert cmd is not None
    assert cmd.classification is CommandClass.READ_ONLY
    assert cmd.safety_level is SafetyLevel.SAFE
