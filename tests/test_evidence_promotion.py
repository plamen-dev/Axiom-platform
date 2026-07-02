"""Tests for the Evidence to Promotion Loop (PR #147 — M2).

These prove the M2 milestone: execution evidence *changes capability state*
rather than remaining an inert artifact. The loop reuses the existing
``CapabilityConfidenceEngine`` as the durable state store and routes the
pass/fail outcome of one ``execution-chain-run`` evidence bundle onto the
capability's prior confidence/readiness.

Matrix covered: passing, failing, missing, invalid (no identity), repeated
(cumulative), and stale evidence; plus linkage and queryability.

PR #148 safety hardening adds: duplicate evidence (no second mutation, still
queryable), distinct-run accumulation, conflicting outcome signals
(quarantined, no mutation), and readiness/EVID-001 scope documentation checks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.evidence_promotion import (
    EvidenceDecision,
    EvidenceOutcome,
    EvidencePromotionLoop,
)
from axiom_core.execution_chain_orchestrator import ExecutionChainOrchestrator
from click.testing import CliRunner


@pytest.fixture
def artifacts_root(tmp_path: Any) -> str:
    return str(tmp_path / "artifacts")


@pytest.fixture
def loop(artifacts_root: str) -> EvidencePromotionLoop:
    return EvidencePromotionLoop(artifacts_root=artifacts_root)


def _write_chain_evidence(
    artifacts_root: str,
    *,
    run_id: str = "run-1",
    capability_id: str = "self-model-build",
    status: str = "PASS",
    created_at: str | None = None,
    result_id: str = "RESULT-1",
    artifact_id: str = "ARTIFACT-1",
    report_id: str = "REPORT-1",
    include_capability: bool = True,
    include_status: bool = True,
    bundle_passed: bool | None = None,
    bundle_status: str | None = None,
    evidence_id: str | None = None,
    metrics: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    include_metrics: bool = True,
) -> str:
    """Write an evidence.json + sibling trace.json like execution-chain-run does.

    ``bundle_passed`` / ``bundle_status`` write outcome signals onto the
    evidence bundle itself (the trace always carries ``status``), which lets a
    test construct agreeing or *conflicting* signal sets.
    """
    run_dir = Path(artifacts_root) / "execution_chain" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    references: dict[str, Any] = {"result_id": result_id, "artifact_id": artifact_id}
    if include_capability:
        references["capability_id"] = capability_id
    evidence: dict[str, Any] = {
        "evidence_id": evidence_id if evidence_id is not None else f"EVID-{run_id}",
        "references": references,
        "summary": "fixture evidence",
    }
    if include_metrics:
        evidence["metrics"] = (
            metrics
            if metrics is not None
            else {"module_count": 10, "import_edge_count": 20}
        )
    if quality is not None:
        evidence["quality"] = quality
    if bundle_passed is not None:
        evidence["passed"] = bundle_passed
    if bundle_status is not None:
        evidence["status"] = bundle_status
    if created_at is not None:
        evidence["created_at"] = created_at
    (run_dir / "evidence.json").write_text(json.dumps(evidence))

    trace: dict[str, Any] = {
        "run_id": run_id,
        "report_id": report_id,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
    if include_status:
        trace["status"] = status
    (run_dir / "trace.json").write_text(json.dumps(trace))
    return str(run_dir / "evidence.json")


# ---------------------------------------------------------------------------
# H1 — passing evidence raises confidence/readiness
# ---------------------------------------------------------------------------


def test_passing_evidence_raises_confidence(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, status="PASS")
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["evidence_outcome"] == EvidenceOutcome.PASS.value
    assert record["state_changed"] is True
    # From the very_low baseline, a passing run raises confidence + readiness
    # by exactly one ladder step (not straight to very_high/ready).
    assert record["prior_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["score"] > record["prior_state"]["score"]
    assert record["updated_state"]["confidence_level"] == "low"
    assert record["updated_state"]["readiness"] == "provisional"
    assert record["promotion"] == {
        "raw_level": "very_high",
        "effective_level": "low",
        "clamped": True,
    }


# ---------------------------------------------------------------------------
# H2 — failing evidence does not raise confidence; blocks readiness
# ---------------------------------------------------------------------------


def test_failing_evidence_does_not_raise_confidence(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, status="FAIL")
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["evidence_outcome"] == EvidenceOutcome.FAIL.value
    assert record["updated_state"]["score"] <= record["prior_state"]["score"]
    assert record["updated_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["readiness"] == "blocked"


# ---------------------------------------------------------------------------
# H3 — evidence is linked to capability / result / artifact / report
# ---------------------------------------------------------------------------


def test_evidence_is_linked_not_orphaned(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(
        artifacts_root,
        result_id="R-9",
        artifact_id="A-9",
        report_id="REP-9",
    )
    record = loop.apply(evidence)

    assert record["capability_id"] == "self-model-build"
    links = record["links"]
    assert links["result_id"] == "R-9"
    assert links["artifact_id"] == "A-9"
    assert links["report_id"] == "REP-9"
    assert links["evidence_id"] == "EVID-run-1"
    # The updated confidence record carries the same capability identity.
    assert record["updated_state"]["capability_id"] == "self-model-build"
    assert record["updated_state"]["confidence_report_id"]


# ---------------------------------------------------------------------------
# Invalid — evidence without capability identity is quarantined
# ---------------------------------------------------------------------------


def test_evidence_without_identity_is_quarantined(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, include_capability=False)
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["accepted"] is False
    assert record["state_changed"] is False
    assert "identity" in record["reason"]


def test_capability_id_override_rescues_missing_identity(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, include_capability=False)
    record = loop.apply(evidence, capability_id="override-cap")

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["capability_id"] == "override-cap"


# ---------------------------------------------------------------------------
# Missing — no determinable outcome / missing file prevents update
# ---------------------------------------------------------------------------


def test_missing_outcome_is_rejected(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, include_status=False)
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.REJECTED.value
    assert record["evidence_outcome"] == EvidenceOutcome.MISSING.value
    assert record["state_changed"] is False


def test_missing_evidence_file_is_rejected(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    record = loop.apply(str(Path(artifacts_root) / "does_not_exist.json"))

    assert record["decision"] == EvidenceDecision.REJECTED.value
    assert record["evidence_outcome"] == EvidenceOutcome.MISSING.value
    assert "not found" in record["reason"]


# ---------------------------------------------------------------------------
# H5 — repeated validation changes confidence cumulatively
# ---------------------------------------------------------------------------


def test_repeated_evidence_is_cumulative(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    passing = _write_chain_evidence(artifacts_root, run_id="pass", status="PASS")
    failing = _write_chain_evidence(artifacts_root, run_id="fail", status="FAIL")

    first = loop.apply(passing)
    assert first["updated_state"]["execution_count"] == 1
    assert first["updated_state"]["success_count"] == 1
    assert first["updated_state"]["score"] == 1.0

    second = loop.apply(failing)
    # Cumulative: a later failure lowers the accumulated confidence.
    assert second["prior_state"]["execution_count"] == 1
    assert second["updated_state"]["execution_count"] == 2
    assert second["updated_state"]["failure_count"] == 1
    assert second["updated_state"]["score"] == 0.5
    assert second["updated_state"]["score"] < first["updated_state"]["score"]


# ---------------------------------------------------------------------------
# Stale — old evidence is quarantined when max_age_seconds is set
# ---------------------------------------------------------------------------


def test_stale_evidence_is_quarantined(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    evidence = _write_chain_evidence(artifacts_root, status="PASS", created_at=old)
    record = loop.apply(evidence, max_age_seconds=3600)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["state_changed"] is False
    assert "stale" in record["reason"]


def test_fresh_evidence_passes_staleness_gate(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    fresh = datetime.now(timezone.utc).isoformat()
    evidence = _write_chain_evidence(artifacts_root, status="PASS", created_at=fresh)
    record = loop.apply(evidence, max_age_seconds=3600)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value


# ---------------------------------------------------------------------------
# Determinism — same prior state + same evidence -> same score/level/decision
# ---------------------------------------------------------------------------


def test_deterministic_state_effect(tmp_path: Any) -> None:
    root_a = str(tmp_path / "a")
    root_b = str(tmp_path / "b")
    ev_a = _write_chain_evidence(root_a, status="PASS")
    ev_b = _write_chain_evidence(root_b, status="PASS")

    rec_a = EvidencePromotionLoop(artifacts_root=root_a).apply(ev_a)
    rec_b = EvidencePromotionLoop(artifacts_root=root_b).apply(ev_b)

    for key in ("decision", "evidence_outcome"):
        assert rec_a[key] == rec_b[key]
    for key in ("score", "confidence_level", "readiness", "execution_count"):
        assert rec_a["updated_state"][key] == rec_b["updated_state"][key]


# ---------------------------------------------------------------------------
# Queryable — intake records can be listed / fetched, current state queried
# ---------------------------------------------------------------------------


def test_intake_records_are_queryable(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, status="PASS")
    record = loop.apply(evidence)
    intake_id = record["intake_id"]

    fetched = loop.get_intake(intake_id)
    assert fetched is not None
    assert fetched["intake_id"] == intake_id

    history = loop.list_intakes(capability_id="self-model-build")
    assert any(r["intake_id"] == intake_id for r in history)

    state = loop.current_state("self-model-build")
    assert state["confidence_report_id"] == record["updated_state"]["confidence_report_id"]
    assert state["readiness"] == "provisional"


def test_m3_hook_recorded(loop: EvidencePromotionLoop, artifacts_root: str) -> None:
    evidence = _write_chain_evidence(artifacts_root, status="PASS")
    record = loop.apply(evidence)
    assert "semantic_info_useful" in record["m3_hook"]
    assert any("purpose" in s for s in record["m3_hook"]["semantic_info_useful"])


# ---------------------------------------------------------------------------
# Integration — evidence produced by the real execution chain changes state
# ---------------------------------------------------------------------------


def test_execution_chain_evidence_changes_state(artifacts_root: str) -> None:
    orchestrator = ExecutionChainOrchestrator(
        repo_root=".", artifacts_root=artifacts_root
    )
    trace = orchestrator.run("self-model-build")
    assert trace.status == "PASS"

    evidence_path = trace.evidence_reference["evidence_path"]
    loop = EvidencePromotionLoop(artifacts_root=artifacts_root)
    record = loop.apply(evidence_path)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["evidence_outcome"] == EvidenceOutcome.PASS.value
    # Evidence links resolve to the real chain ids.
    assert record["capability_id"] == trace.capability_id
    assert record["links"]["result_id"] == trace.result_id
    assert record["links"]["artifact_id"] == trace.artifact_id
    assert record["links"]["report_id"] == trace.report_id
    # State changed purely because evidence was ingested; the single-step
    # ladder limits the first run to one level above the very_low baseline.
    assert record["prior_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["confidence_level"] == "low"
    assert record["updated_state"]["readiness"] == "provisional"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_capability_evidence_apply_json(tmp_path: Any) -> None:
    root = str(tmp_path / "artifacts")
    evidence = _write_chain_evidence(root, status="PASS")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "capability-evidence-apply",
            "--evidence",
            evidence,
            "--artifacts-root",
            root,
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["decision"] == "accepted"
    assert payload["updated_state"]["readiness"] == "provisional"


def test_cli_capability_evidence_apply_console(tmp_path: Any) -> None:
    root = str(tmp_path / "artifacts")
    evidence = _write_chain_evidence(root, status="FAIL")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["capability-evidence-apply", "--evidence", evidence, "--artifacts-root", root],
    )
    assert result.exit_code == 0, result.output
    assert "Capability Evidence Intake" in result.output
    assert "accepted" in result.output


def test_cli_history_and_show(tmp_path: Any) -> None:
    root = str(tmp_path / "artifacts")
    evidence = _write_chain_evidence(root, status="PASS")
    runner = CliRunner()
    apply_result = runner.invoke(
        cli,
        [
            "capability-evidence-apply",
            "--evidence",
            evidence,
            "--artifacts-root",
            root,
            "--json-output",
        ],
    )
    intake_id = json.loads(apply_result.output)["intake_id"]

    history = runner.invoke(
        cli,
        [
            "capability-evidence-history",
            "--capability-id",
            "self-model-build",
            "--artifacts-root",
            root,
            "--json-output",
        ],
    )
    assert history.exit_code == 0, history.output
    assert any(r["intake_id"] == intake_id for r in json.loads(history.output))

    show = runner.invoke(
        cli,
        [
            "capability-evidence-show",
            intake_id,
            "--artifacts-root",
            root,
            "--json-output",
        ],
    )
    assert show.exit_code == 0, show.output
    assert json.loads(show.output)["intake_id"] == intake_id


# ---------------------------------------------------------------------------
# PR #148 — duplicate evidence handling
# ---------------------------------------------------------------------------


def test_duplicate_evidence_does_not_inflate_confidence(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """The same evidence file applied twice must not mutate state again."""
    evidence = _write_chain_evidence(artifacts_root, run_id="dup", status="PASS")

    first = loop.apply(evidence)
    assert first["decision"] == EvidenceDecision.ACCEPTED.value
    assert first["updated_state"]["execution_count"] == 1
    assert first["updated_state"]["success_count"] == 1

    second = loop.apply(evidence)
    assert second["decision"] == EvidenceDecision.DUPLICATE.value
    assert second["state_changed"] is False
    assert second["duplicate_of"] == first["intake_id"]
    # Confidence factors are unchanged — no second accumulation.
    assert second["updated_state"]["execution_count"] == 1
    assert second["updated_state"]["success_count"] == 1
    assert second["updated_state"]["score"] == first["updated_state"]["score"]

    # The durable confidence store agrees: still a single execution.
    assert loop.current_state("self-model-build")["execution_count"] == 1


def test_duplicate_evidence_attempt_is_visible_in_history(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(artifacts_root, run_id="dup2", status="PASS")
    loop.apply(evidence)
    dup = loop.apply(evidence)

    history = loop.list_intakes(capability_id="self-model-build")
    decisions = [r["decision"] for r in history]
    assert EvidenceDecision.DUPLICATE.value in decisions
    fetched = loop.get_intake(dup["intake_id"])
    assert fetched["decision"] == EvidenceDecision.DUPLICATE.value
    assert fetched["evidence_fingerprint"] == "evidence_id:EVID-dup2"


def test_distinct_runs_still_accumulate(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Distinct evidence from distinct runs is not treated as a duplicate."""
    first_ev = _write_chain_evidence(artifacts_root, run_id="r1", status="PASS")
    second_ev = _write_chain_evidence(artifacts_root, run_id="r2", status="PASS")

    first = loop.apply(first_ev)
    second = loop.apply(second_ev)

    assert first["decision"] == EvidenceDecision.ACCEPTED.value
    assert second["decision"] == EvidenceDecision.ACCEPTED.value
    assert second["updated_state"]["execution_count"] == 2
    assert second["updated_state"]["success_count"] == 2


def test_previously_quarantined_evidence_can_still_apply(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Only *accepted* applications block re-application; a quarantine doesn't."""
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    evidence = _write_chain_evidence(
        artifacts_root, run_id="requeue", status="PASS", created_at=old
    )
    quarantined = loop.apply(evidence, max_age_seconds=3600)
    assert quarantined["decision"] == EvidenceDecision.QUARANTINED.value

    accepted = loop.apply(evidence)  # no staleness gate this time
    assert accepted["decision"] == EvidenceDecision.ACCEPTED.value
    assert accepted["updated_state"]["execution_count"] == 1


# ---------------------------------------------------------------------------
# PR #148 — conflicting outcome signal handling
# ---------------------------------------------------------------------------


def test_conflicting_signals_are_quarantined(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """bundle.passed=true but trace.status=FAIL must not be silently resolved."""
    evidence = _write_chain_evidence(
        artifacts_root, run_id="conflict", status="FAIL", bundle_passed=True
    )
    record = loop.apply(evidence)

    assert record["evidence_outcome"] == EvidenceOutcome.CONFLICT.value
    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["state_changed"] is False
    assert "conflict" in record["reason"].lower()
    # All detected signals are preserved for the audit record.
    sources = {s["source"] for s in record["outcome_signals"]}
    assert {"bundle.passed", "trace.status"} <= sources
    assert {s["outcome"] for s in record["outcome_signals"]} == {"pass", "fail"}


def test_conflicted_evidence_does_not_mutate_confidence(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    evidence = _write_chain_evidence(
        artifacts_root, run_id="conflict2", bundle_status="PASS", status="FAIL"
    )
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["prior_state"] == record["updated_state"]
    # Nothing was written to the confidence store.
    assert loop.current_state("self-model-build")["execution_count"] == 0


def test_agreeing_signals_are_accepted(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Multiple signals that agree are not a conflict."""
    evidence = _write_chain_evidence(
        artifacts_root, run_id="agree", bundle_passed=True, bundle_status="PASS",
        status="PASS",
    )
    record = loop.apply(evidence)
    assert record["evidence_outcome"] == EvidenceOutcome.PASS.value
    assert record["decision"] == EvidenceDecision.ACCEPTED.value


def test_cli_duplicate_and_conflict(tmp_path: Any) -> None:
    root = str(tmp_path / "artifacts")
    runner = CliRunner()

    evidence = _write_chain_evidence(root, run_id="cli-dup", status="PASS")
    first = runner.invoke(
        cli,
        ["capability-evidence-apply", "--evidence", evidence,
         "--artifacts-root", root, "--json-output"],
    )
    assert json.loads(first.output)["decision"] == "accepted"
    second = runner.invoke(
        cli,
        ["capability-evidence-apply", "--evidence", evidence,
         "--artifacts-root", root, "--json-output"],
    )
    dup_payload = json.loads(second.output)
    assert dup_payload["decision"] == "duplicate"
    assert dup_payload["state_changed"] is False

    conflict = _write_chain_evidence(
        root, run_id="cli-conflict", status="FAIL", bundle_passed=True
    )
    conflict_result = runner.invoke(
        cli,
        ["capability-evidence-apply", "--evidence", conflict,
         "--artifacts-root", root, "--json-output"],
    )
    conflict_payload = json.loads(conflict_result.output)
    assert conflict_payload["decision"] == "quarantined"
    assert conflict_payload["evidence_outcome"] == "conflict"
    assert conflict_payload["state_changed"] is False


# ---------------------------------------------------------------------------
# PR #148 — readiness classification + EVID-001 scope language
# ---------------------------------------------------------------------------


def test_readiness_label_is_deterministic_and_local() -> None:
    """Readiness is a pure deterministic projection of the score, documented
    as implementation-local (not promotion doctrine)."""
    from axiom_core import evidence_promotion

    assert evidence_promotion._readiness_from_score(0.95) == "ready"
    assert evidence_promotion._readiness_from_score(0.7) == "ready"
    assert evidence_promotion._readiness_from_score(0.5) == "provisional"
    assert evidence_promotion._readiness_from_score(0.3) == "provisional"
    assert evidence_promotion._readiness_from_score(0.1) == "blocked"
    # Deterministic: same input -> same label.
    assert evidence_promotion._readiness_from_score(0.5) == (
        evidence_promotion._readiness_from_score(0.5)
    )

    doc = evidence_promotion._readiness_from_score.__doc__ or ""
    assert "implementation-local" in doc.lower()
    assert "not promotion" in doc.lower()
    assert "program 6" in doc.lower()


def test_evid001_language_is_scoped_to_m2_slice() -> None:
    """The module must not overclaim full EVID-001 closure."""
    from axiom_core import evidence_promotion

    module_doc = (evidence_promotion.__doc__ or "").lower()
    assert "narrow m2 slice" in module_doc
    assert "model_health" in module_doc
    assert "remains" in module_doc and "open" in module_doc


# ---------------------------------------------------------------------------
# Finding 2 — semantically empty evidence is quarantined, not promoted
# ---------------------------------------------------------------------------


def test_empty_evidence_is_quarantined_not_promoted(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """A PASS bundle with module_count=0 must be quarantined with no state change."""
    evidence = _write_chain_evidence(
        artifacts_root,
        status="PASS",
        metrics={"module_count": 0, "import_edge_count": 0, "isolated_module_count": 0},
    )
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["accepted"] is False
    assert record["state_changed"] is False
    assert record["evidence_quality"]["verdict"] == "EMPTY"
    assert "module_count" in record["evidence_quality"]["zero_metrics"]


def test_empty_evidence_does_not_move_confidence_or_readiness(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Empty evidence must not move very_low -> very_high / blocked -> ready."""
    evidence = _write_chain_evidence(
        artifacts_root, status="PASS", metrics={"module_count": 0}
    )
    record = loop.apply(evidence)

    assert record["prior_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["confidence_level"] == "very_low"
    assert record["prior_state"]["readiness"] == "blocked"
    assert record["updated_state"]["readiness"] == "blocked"
    # And the durable capability state is untouched.
    assert loop.current_state("self-model-build")["confidence_level"] == "very_low"
    assert loop.current_state("self-model-build")["readiness"] == "blocked"


def test_substantive_evidence_still_promotes(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Non-zero module_count still accepts + promotes exactly as before."""
    evidence = _write_chain_evidence(
        artifacts_root, status="PASS", metrics={"module_count": 5, "import_edge_count": 0}
    )
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["updated_state"]["confidence_level"] == "low"
    assert record["updated_state"]["readiness"] == "provisional"


def test_unknown_capability_not_evaluated_preserves_behavior(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """A capability with no configured rule is NOT_EVALUATED and still accepts."""
    evidence = _write_chain_evidence(
        artifacts_root,
        capability_id="some-other-capability",
        status="PASS",
        metrics={"module_count": 0},
    )
    record = loop.apply(evidence, capability_id="some-other-capability")

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert record["evidence_quality"]["verdict"] == "NOT_EVALUATED"


def test_older_bundle_without_quality_is_defensively_recomputed(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """A bundle lacking the quality field is recomputed and quarantined if empty."""
    evidence = _write_chain_evidence(
        artifacts_root, status="PASS", metrics={"module_count": 0}
    )
    # No `quality` field was written (older-format bundle).
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["evidence_quality"]["verdict"] == "EMPTY"
    assert "recomputed from metrics" in record["reason"]


def test_malformed_quality_field_is_defensively_recomputed(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """A malformed quality field cannot smuggle empty evidence past the gate."""
    evidence = _write_chain_evidence(
        artifacts_root,
        status="PASS",
        metrics={"module_count": 0},
        quality={"verdict": "TOTALLY_FINE_TRUST_ME"},
    )
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["evidence_quality"]["verdict"] == "EMPTY"


def test_stamped_substantive_quality_is_honored(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """A well-formed stamped SUBSTANTIVE verdict is used as-is (not recomputed)."""
    evidence = _write_chain_evidence(
        artifacts_root,
        status="PASS",
        metrics={"module_count": 3},
        quality={
            "verdict": "SUBSTANTIVE",
            "required_metrics": ["module_count"],
            "zero_metrics": [],
            "reason": "stamped by producer",
        },
    )
    record = loop.apply(evidence)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    assert "recomputed" not in record["reason"]


def test_chain_stamps_quality_empty_while_status_pass(tmp_path: Any) -> None:
    """Producer: a valid id-flow PASS run still stamps quality.verdict=EMPTY
    when the self-model has zero modules (empty repo)."""
    empty_repo = tmp_path / "empty_repo"
    (empty_repo / "src").mkdir(parents=True)
    orch = ExecutionChainOrchestrator(
        repo_root=str(empty_repo), artifacts_root=str(tmp_path / "artifacts")
    )
    trace = orch.run("self-model-build")

    assert trace.status == "PASS"  # id-flow plumbing verdict unchanged
    evidence_path = Path(trace.evidence_reference["evidence_path"])
    bundle = json.loads(evidence_path.read_text())
    assert bundle["metrics"]["module_count"] == 0
    assert bundle["quality"]["verdict"] == "EMPTY"
    assert "module_count" in bundle["quality"]["zero_metrics"]


def test_chain_quality_empty_is_quarantined_end_to_end(tmp_path: Any) -> None:
    """Producer + consumer: an empty repo's chain evidence is quarantined."""
    empty_repo = tmp_path / "empty_repo"
    (empty_repo / "src").mkdir(parents=True)
    artifacts = str(tmp_path / "artifacts")
    orch = ExecutionChainOrchestrator(
        repo_root=str(empty_repo), artifacts_root=artifacts
    )
    trace = orch.run("self-model-build")
    loop = EvidencePromotionLoop(artifacts_root=artifacts)
    record = loop.apply(trace.evidence_reference["evidence_path"])

    assert record["decision"] == EvidenceDecision.QUARANTINED.value
    assert record["state_changed"] is False
    assert record["evidence_quality"]["verdict"] == "EMPTY"


# ---------------------------------------------------------------------------
# Single-step promotion ladder — trust accumulates, it is not granted at once
# ---------------------------------------------------------------------------


def _apply_pass(loop: EvidencePromotionLoop, root: str, run_id: str) -> dict[str, Any]:
    evidence = _write_chain_evidence(root, run_id=run_id, status="PASS")
    return loop.apply(evidence)


def test_ladder_climbs_one_level_per_accepted_pass(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Four distinct accepted PASSes climb exactly one level each."""
    expectations = [
        ("low", "provisional", True),
        ("medium", "provisional", True),
        ("high", "ready", True),
        ("very_high", "ready", False),  # high -> very_high is one step: no clamp
    ]
    for i, (level, readiness, clamped) in enumerate(expectations):
        record = _apply_pass(loop, artifacts_root, run_id=f"ladder-{i}")
        assert record["decision"] == EvidenceDecision.ACCEPTED.value
        assert record["updated_state"]["confidence_level"] == level
        assert record["updated_state"]["readiness"] == readiness
        assert record["promotion"]["raw_level"] == "very_high"
        assert record["promotion"]["effective_level"] == level
        assert record["promotion"]["clamped"] is clamped


def test_failure_drop_is_never_clamped(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Once at very_high, a failure lowers the published level immediately."""
    for i in range(4):
        _apply_pass(loop, artifacts_root, run_id=f"drop-up-{i}")
    assert loop.current_state("self-model-build")["confidence_level"] == "very_high"

    failing = _write_chain_evidence(artifacts_root, run_id="drop-fail", status="FAIL")
    record = loop.apply(failing)

    assert record["decision"] == EvidenceDecision.ACCEPTED.value
    # 4/5 = 0.8 -> raw high; the drop is applied as-is, not rate-limited.
    assert record["updated_state"]["confidence_level"] == "high"
    assert record["promotion"] == {
        "raw_level": "high",
        "effective_level": "high",
        "clamped": False,
    }


def test_quarantined_and_duplicate_do_not_advance_ladder(
    loop: EvidencePromotionLoop, artifacts_root: str
) -> None:
    """Only accepted applications climb the ladder."""
    first = _apply_pass(loop, artifacts_root, run_id="rung-1")
    assert first["updated_state"]["confidence_level"] == "low"

    empty = _write_chain_evidence(
        artifacts_root, run_id="rung-empty", status="PASS",
        metrics={"module_count": 0},
    )
    quarantined = loop.apply(empty)
    assert quarantined["decision"] == EvidenceDecision.QUARANTINED.value

    duplicate = loop.apply(
        _write_chain_evidence(artifacts_root, run_id="rung-1", status="PASS")
    )
    assert duplicate["decision"] == EvidenceDecision.DUPLICATE.value

    state = loop.current_state("self-model-build")
    assert state["confidence_level"] == "low"
    assert state["readiness"] == "provisional"


def test_ladder_state_round_trips_durable_store(
    artifacts_root: str,
) -> None:
    """The clamped level survives a fresh loop over the same artifacts root."""
    loop = EvidencePromotionLoop(artifacts_root=artifacts_root)
    _apply_pass(loop, artifacts_root, run_id="rt-1")
    _apply_pass(loop, artifacts_root, run_id="rt-2")

    fresh = EvidencePromotionLoop(artifacts_root=artifacts_root)
    state = fresh.current_state("self-model-build")
    assert state["confidence_level"] == "medium"
    assert state["readiness"] == "provisional"
    # The raw score is untouched doctrine: still the pure success ratio.
    assert state["score"] == 1.0


def test_clamp_level_is_pure_and_conservative() -> None:
    from axiom_core.evidence_promotion import _clamp_level

    assert _clamp_level("very_low", "very_high") == ("low", True)
    assert _clamp_level("low", "very_high") == ("medium", True)
    assert _clamp_level("high", "very_high") == ("very_high", False)
    assert _clamp_level("very_high", "low") == ("low", False)  # drops uncapped
    assert _clamp_level("medium", "medium") == ("medium", False)
    # Unknown labels are treated as very_low.
    assert _clamp_level("weird", "very_high") == ("low", True)
