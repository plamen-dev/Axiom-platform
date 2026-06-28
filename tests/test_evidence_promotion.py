"""Tests for the Evidence to Promotion Loop (PR #147 — M2).

These prove the M2 milestone: execution evidence *changes capability state*
rather than remaining an inert artifact. The loop reuses the existing
``CapabilityConfidenceEngine`` as the durable state store and routes the
pass/fail outcome of one ``execution-chain-run`` evidence bundle onto the
capability's prior confidence/readiness.

Matrix covered: passing, failing, missing, invalid (no identity), repeated
(cumulative), and stale evidence; plus linkage and queryability.
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
) -> str:
    """Write an evidence.json + sibling trace.json like execution-chain-run does."""
    run_dir = Path(artifacts_root) / "execution_chain" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    references: dict[str, Any] = {"result_id": result_id, "artifact_id": artifact_id}
    if include_capability:
        references["capability_id"] = capability_id
    evidence = {
        "evidence_id": f"EVID-{run_id}",
        "references": references,
        "metrics": {"module_count": 10, "import_edge_count": 20},
        "summary": "fixture evidence",
    }
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
    # From the very_low baseline, a passing run raises confidence + readiness.
    assert record["prior_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["score"] > record["prior_state"]["score"]
    assert record["updated_state"]["confidence_level"] == "very_high"
    assert record["updated_state"]["readiness"] == "ready"


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
    assert state["readiness"] == "ready"


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
    # State changed purely because evidence was ingested.
    assert record["prior_state"]["confidence_level"] == "very_low"
    assert record["updated_state"]["confidence_level"] == "very_high"
    assert record["updated_state"]["readiness"] == "ready"


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
    assert payload["updated_state"]["readiness"] == "ready"


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
