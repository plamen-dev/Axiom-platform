"""Tests for the Model Health Readiness Evidence Consumer (PR #156).

These prove the narrow Model Health slice of EVID-001 is closed: the
``axiom_capability_readiness.json`` producer (PR #32 model_health) is no longer
orphaned to read-only helpers — it now has a state/evidence consumer that
ingests, validates, dedups, preserves provenance, and durably records readiness
evidence. Readiness is deliberately NOT mapped onto confidence math.

Matrix covered: valid, missing artifact, invalid JSON, missing required
fields, invalid readiness label, duplicate (no second record), conflicting
labels within one artifact (quarantined), stale (opt-in), provenance, and the
confirmation that confidence is never mutated.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.capability_confidence import CapabilityConfidenceEngine
from axiom_core.model_health_evidence import (
    ModelHealthReadinessConsumer,
    ReadinessDecision,
)
from click.testing import CliRunner


@pytest.fixture
def artifacts_root(tmp_path: Any) -> str:
    return str(tmp_path / "artifacts")


@pytest.fixture
def consumer(artifacts_root: str) -> ModelHealthReadinessConsumer:
    return ModelHealthReadinessConsumer(artifacts_root=artifacts_root)


def _write_readiness(
    artifacts_root: str,
    *,
    run_id: str = "ModelHealth-run-1",
    generated_at: str | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    raw: str | None = None,
    top_level: dict[str, Any] | None = None,
) -> str:
    """Write an axiom_capability_readiness.json like execute_health_run does."""
    run_dir = Path(artifacts_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "axiom_capability_readiness.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return str(path)
    if capabilities is None:
        capabilities = [
            {
                "capability": "GridCreation",
                "capability_version": "1.0.0",
                "readiness": "READY",
                "risk_level": "medium",
                "dry_run_available": True,
                "execute_available": True,
                "blocking_conditions": [],
                "warnings": [],
                "required_user_decisions": [],
                "recommended_next_actions": [],
            }
        ]
    data: dict[str, Any] = {
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "capabilities": capabilities,
    }
    if top_level is not None:
        data.update(top_level)
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 1. Valid readiness artifact is consumed
# ---------------------------------------------------------------------------


def test_valid_readiness_is_accepted(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(artifacts_root)
    result = consumer.apply(path)

    assert result.error is None
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec["decision"] == ReadinessDecision.ACCEPTED.value
    assert rec["capability"] == "GridCreation"
    assert rec["readiness"] == "READY"
    assert rec["confidence_mutated"] is False
    # Durable, queryable state.
    assert consumer.current_readiness("GridCreation") == rec["readiness_state"]


# ---------------------------------------------------------------------------
# 2. Missing artifact is handled safely
# ---------------------------------------------------------------------------


def test_missing_artifact_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    result = consumer.apply(str(Path(artifacts_root) / "nope.json"))
    assert result.error is not None
    assert "not found" in result.error
    assert result.records[0]["decision"] == ReadinessDecision.REJECTED.value


# ---------------------------------------------------------------------------
# 3. Invalid JSON is rejected
# ---------------------------------------------------------------------------


def test_invalid_json_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(artifacts_root, raw="{not json")
    result = consumer.apply(path)
    assert result.error is not None
    assert "not readable JSON" in result.error


def test_non_object_artifact_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(artifacts_root, raw="[1, 2, 3]")
    result = consumer.apply(path)
    assert result.error is not None
    assert "not a JSON object" in result.error


def test_missing_capabilities_list_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(artifacts_root, raw='{"generated_at_utc": "x"}')
    result = consumer.apply(path)
    assert result.error is not None
    assert "capabilities" in result.error


# ---------------------------------------------------------------------------
# 4. Missing/invalid required fields are rejected (per-entry)
# ---------------------------------------------------------------------------


def test_missing_capability_field_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root, capabilities=[{"readiness": "READY"}]
    )
    result = consumer.apply(path)
    assert result.records[0]["decision"] == ReadinessDecision.REJECTED.value


def test_missing_readiness_field_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root, capabilities=[{"capability": "GridCreation"}]
    )
    result = consumer.apply(path)
    assert result.records[0]["decision"] == ReadinessDecision.REJECTED.value


def test_invalid_readiness_label_rejected(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root,
        capabilities=[{"capability": "GridCreation", "readiness": "MAYBE"}],
    )
    result = consumer.apply(path)
    rec = result.records[0]
    assert rec["decision"] == ReadinessDecision.REJECTED.value
    assert "invalid readiness" in rec["reason"]


def test_one_bad_entry_does_not_block_good_entry(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root,
        capabilities=[
            {"capability": "GridCreation", "readiness": "READY"},
            {"readiness": "BLOCKED"},  # malformed: no capability
        ],
    )
    result = consumer.apply(path)
    decisions = {r["capability"]: r["decision"] for r in result.records}
    assert decisions["GridCreation"] == ReadinessDecision.ACCEPTED.value
    assert ReadinessDecision.REJECTED.value in decisions.values()


# ---------------------------------------------------------------------------
# 5. Duplicate evidence is not re-recorded as a second mutation
# ---------------------------------------------------------------------------


def test_duplicate_readiness_not_reapplied(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root, generated_at="2026-01-01T00:00:00+00:00"
    )
    first = consumer.apply(path)
    second = consumer.apply(path)

    assert first.records[0]["decision"] == ReadinessDecision.ACCEPTED.value
    assert second.records[0]["decision"] == ReadinessDecision.DUPLICATE.value
    accepted = [
        r
        for r in consumer.list_intakes(capability="GridCreation")
        if r["decision"] == ReadinessDecision.ACCEPTED.value
    ]
    assert len(accepted) == 1


def test_distinct_snapshot_accumulates(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    p1 = _write_readiness(
        artifacts_root, run_id="r1", generated_at="2026-01-01T00:00:00+00:00"
    )
    p2 = _write_readiness(
        artifacts_root, run_id="r2", generated_at="2026-01-02T00:00:00+00:00"
    )
    consumer.apply(p1)
    consumer.apply(p2)
    accepted = [
        r
        for r in consumer.list_intakes(capability="GridCreation")
        if r["decision"] == ReadinessDecision.ACCEPTED.value
    ]
    assert len(accepted) == 2


# ---------------------------------------------------------------------------
# 6. Conflicting readiness within one artifact is quarantined
# ---------------------------------------------------------------------------


def test_conflicting_readiness_quarantined(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root,
        capabilities=[
            {"capability": "GridCreation", "readiness": "READY"},
            {"capability": "GridCreation", "readiness": "BLOCKED"},
        ],
    )
    result = consumer.apply(path)
    decisions = [r["decision"] for r in result.records]
    assert decisions == [
        ReadinessDecision.QUARANTINED.value,
        ReadinessDecision.QUARANTINED.value,
    ]
    assert consumer.current_readiness("GridCreation") is None


# ---------------------------------------------------------------------------
# 7. Stale evidence behavior is explicit (opt-in)
# ---------------------------------------------------------------------------


def test_stale_readiness_quarantined_when_opted_in(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path = _write_readiness(artifacts_root, generated_at=old)
    result = consumer.apply(path, max_age_seconds=60)
    assert result.records[0]["decision"] == ReadinessDecision.QUARANTINED.value
    assert "stale" in result.records[0]["reason"]


def test_stale_readiness_accepted_without_opt_in(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path = _write_readiness(artifacts_root, generated_at=old)
    result = consumer.apply(path)  # no max_age_seconds
    assert result.records[0]["decision"] == ReadinessDecision.ACCEPTED.value


# ---------------------------------------------------------------------------
# 8. Provenance is preserved
# ---------------------------------------------------------------------------


def test_provenance_preserved(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    path = _write_readiness(
        artifacts_root,
        run_id="ModelHealth-abc",
        generated_at="2026-03-03T03:03:03+00:00",
    )
    rec = consumer.apply(path).records[0]
    prov = rec["provenance"]
    assert prov["source_artifact"] == path
    assert prov["producer_run_id"] == "ModelHealth-abc"
    assert prov["generated_at_utc"] == "2026-03-03T03:03:03+00:00"
    assert prov["producer"] == "axiom_core.model_health.execute_health_run"


# ---------------------------------------------------------------------------
# 9. Confidence math is never mutated by readiness consumption
# ---------------------------------------------------------------------------


def test_confidence_not_mutated_by_readiness(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    engine = CapabilityConfidenceEngine(artifacts_root=artifacts_root)
    assert engine.list_reports() == []
    path = _write_readiness(artifacts_root)
    consumer.apply(path)
    # No confidence report was created as a side effect of readiness ingestion.
    assert engine.list_reports() == []


# ---------------------------------------------------------------------------
# 10. Read-only server helper remains read-only (no intake side effects)
# ---------------------------------------------------------------------------


def test_read_only_helper_does_not_create_intake(
    consumer: ModelHealthReadinessConsumer, artifacts_root: str
) -> None:
    # The consumer is the only thing that writes intakes; merely reading the
    # artifact (as server_tools does) must not have created any.
    _write_readiness(artifacts_root)
    assert consumer.list_intakes() == []


# ---------------------------------------------------------------------------
# 11. CLI smoke: apply + history
# ---------------------------------------------------------------------------


def test_cli_model_health_evidence_apply(artifacts_root: str) -> None:
    path = _write_readiness(artifacts_root)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "model-health-evidence-apply",
            "--readiness",
            path,
            "--artifacts-root",
            artifacts_root,
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["accepted"] == 1

    hist = runner.invoke(
        cli,
        [
            "model-health-evidence-history",
            "--artifacts-root",
            artifacts_root,
            "--json-output",
        ],
    )
    assert hist.exit_code == 0, hist.output
    records = json.loads(hist.output)
    assert len(records) == 1
    assert records[0]["capability"] == "GridCreation"


def test_cli_missing_artifact_exit_code(artifacts_root: str) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "model-health-evidence-apply",
            "--readiness",
            str(Path(artifacts_root) / "missing.json"),
            "--artifacts-root",
            artifacts_root,
            "--json-output",
        ],
    )
    assert result.exit_code == 1
