"""Tests for the Capability State Registry (PR #27).

State/governance only: these prove the registry can list/inspect capability
lifecycle state, handle unknown capabilities, refresh+persist from registries
and evidence artifacts, summarize evidence counts, preserve the latest run /
evidence pointers, derive deterministic statuses, emit JSON, and persist to
SQLite. Nothing here executes, retries, promotes, or schedules a capability.
"""

from __future__ import annotations

import json
from pathlib import Path

from axiom_cli.main import cli
from axiom_core.database import create_db_engine, init_db, make_session_factory
from axiom_core.models import CandidateCapabilityRow
from axiom_core.runner.capability_state import (
    CapabilityState,
    CapabilityStateRegistry,
    CapabilityStatus,
)
from click.testing import CliRunner

FIXED_AT = "2026-05-06T12:00:00+00:00"


# --- helpers ---------------------------------------------------------------


def _session_factory(tmp_path: Path):
    engine = create_db_engine(str(tmp_path / "state.db"))
    init_db(engine)
    return make_session_factory(engine)


def _exec_bundle(base: Path, capability: str, run_id: str, outcome: str,
                 finished_at: str, reason: str = "") -> Path:
    run_dir = base / capability / run_id
    (run_dir / "command_outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "pass_fail.json").write_text(
        json.dumps({"outcome": outcome, "capability_name": capability}),
        encoding="utf-8")
    (run_dir / "capability_result.json").write_text(
        json.dumps({
            "capability_name": capability,
            "outcome": outcome,
            "started_at": finished_at,
            "finished_at": finished_at,
            "reason": reason,
        }),
        encoding="utf-8")
    return run_dir


def _val_bundle(base: Path, validation_name: str, run_id: str, outcome: str,
                finished_at: str, capability_name: str | None = None,
                reason: str = "") -> Path:
    run_dir = base / validation_name / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "pass_fail.json").write_text(
        json.dumps({"outcome": outcome}), encoding="utf-8")
    (run_dir / "validation_result.json").write_text(
        json.dumps({
            "capability_name": capability_name,
            "validation_name": validation_name,
            "outcome": outcome,
            "started_at": finished_at,
            "finished_at": finished_at,
            "reason": reason,
        }),
        encoding="utf-8")
    return run_dir


def _registry(tmp_path: Path, **kwargs) -> CapabilityStateRegistry:
    return CapabilityStateRegistry(
        capability_runs_base=tmp_path / "capability_runs",
        validation_evidence_base=tmp_path / "validation_evidence",
        **kwargs,
    )


# --- listing & seeding -----------------------------------------------------


def test_registry_lists_capability_states(tmp_path):
    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    names = snap.names()
    # Seeded from the validation + command registries even with no artifacts.
    assert "InventoryModel" in names
    assert "SetParameterValue" in names
    assert all(isinstance(s, CapabilityState) for s in snap.states)
    # Sorted, deterministic ordering.
    assert names == sorted(names)


def test_definitional_statuses(tmp_path):
    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    # InventoryModel has a safe executor -> executable.
    assert snap.get("InventoryModel").current_status is CapabilityStatus.EXECUTABLE
    # SetParameterValue has a validation definition but no executor here.
    assert (snap.get("SetParameterValue").current_status
            is CapabilityStatus.VALIDATION_DEFINED)


# --- inspecting a single capability ---------------------------------------


def test_inspect_one_capability(tmp_path):
    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    state = snap.get("InventoryModel")
    assert state is not None
    assert state.capability_name == "InventoryModel"
    assert state.adapter == "revit"
    assert state.capability_type == "inventory"
    assert "command_registry" in state.source_registry


def test_unknown_capability_returns_none(tmp_path):
    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    assert snap.get("TotallyFakeCapability") is None


# --- evidence summarization ------------------------------------------------


def test_execution_evidence_counts_summarized(tmp_path):
    base = tmp_path / "capability_runs"
    _exec_bundle(base, "InventoryModel", "crun_1", "passed", "2026-05-01T00:00:00+00:00")
    _exec_bundle(base, "InventoryModel", "crun_2", "passed", "2026-05-02T00:00:00+00:00")
    _exec_bundle(base, "InventoryModel", "crun_3", "failed", "2026-05-03T00:00:00+00:00",
                 reason="boom")
    _exec_bundle(base, "InventoryModel", "crun_4", "refused", "2026-05-04T00:00:00+00:00")

    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("InventoryModel")
    assert state.pass_count == 2
    assert state.fail_count == 1
    assert state.refused_count == 1
    assert state.blocked_count == 0
    assert state.metadata["event_count"] == 4


def test_latest_run_and_evidence_path_preserved(tmp_path):
    base = tmp_path / "capability_runs"
    _exec_bundle(base, "InventoryModel", "crun_1", "passed", "2026-05-01T00:00:00+00:00")
    last = _exec_bundle(base, "InventoryModel", "crun_2", "failed",
                        "2026-05-09T00:00:00+00:00", reason="latest-failure")

    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("InventoryModel")
    # Latest by timestamp wins.
    assert state.last_execution_run_id == "crun_2"
    assert state.last_evidence_path == str(last)
    assert state.last_error_summary == "latest-failure"
    # Latest execution failed -> status reflects the most recent run.
    assert state.current_status is CapabilityStatus.EXECUTION_FAILED


def test_validation_evidence_mapped_by_capability_name(tmp_path):
    vbase = tmp_path / "validation_evidence"
    _val_bundle(vbase, "DiscoveryHarness", "evr_1", "passed",
                "2026-05-01T00:00:00+00:00", capability_name="DiscoveryHarness")
    # Infra validation with no capability_name is ignored.
    _val_bundle(vbase, "CommandRegistry", "evr_2", "passed",
                "2026-05-02T00:00:00+00:00", capability_name=None)

    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    dh = snap.get("DiscoveryHarness")
    assert dh.current_status is CapabilityStatus.VALIDATION_PASSED
    assert dh.last_validation_run_id == "evr_1"
    assert snap.get("CommandRegistry") is None


def test_execution_takes_precedence_over_validation(tmp_path):
    _val_bundle(tmp_path / "validation_evidence", "InventoryModel", "evr_1",
                "passed", "2026-05-01T00:00:00+00:00", capability_name="InventoryModel")
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "failed", "2026-05-02T00:00:00+00:00")
    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("InventoryModel")
    assert state.current_status is CapabilityStatus.EXECUTION_FAILED
    assert state.last_validation_run_id == "evr_1"
    assert state.last_execution_run_id == "crun_1"


# --- promotion candidate flag (non-binding) --------------------------------


def test_promotion_candidate_flag(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("InventoryModel")
    assert state.promotion_candidate is True


def test_promotion_candidate_false_with_failure(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_2",
                 "failed", "2026-05-02T00:00:00+00:00")
    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("InventoryModel")
    assert state.promotion_candidate is False


def test_promotion_candidate_for_validation_only_pass(tmp_path):
    # A validation-defined capability with a passing validation but no execution
    # evidence is still a (non-binding) promotion candidate — the VALIDATION_PASSED
    # branch must be reachable, not dead.
    _val_bundle(tmp_path / "validation_evidence", "SetParameterValue", "evr_1",
                "passed", "2026-05-01T00:00:00+00:00",
                capability_name="SetParameterValue")
    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("SetParameterValue")
    assert state.current_status is CapabilityStatus.VALIDATION_PASSED
    assert state.promotion_candidate is True


def test_promotion_candidate_false_with_validation_failure(tmp_path):
    _val_bundle(tmp_path / "validation_evidence", "SetParameterValue", "evr_1",
                "passed", "2026-05-01T00:00:00+00:00",
                capability_name="SetParameterValue")
    _val_bundle(tmp_path / "validation_evidence", "SetParameterValue", "evr_2",
                "failed", "2026-05-02T00:00:00+00:00",
                capability_name="SetParameterValue")
    state = _registry(tmp_path).build_snapshot(at=FIXED_AT).get("SetParameterValue")
    assert state.promotion_candidate is False


# --- determinism -----------------------------------------------------------


def test_statuses_are_deterministic(tmp_path):
    base = tmp_path / "capability_runs"
    _exec_bundle(base, "InventoryModel", "crun_1", "passed", "2026-05-01T00:00:00+00:00")
    _exec_bundle(base, "InventoryModel", "crun_2", "refused", "2026-05-02T00:00:00+00:00")

    reg = _registry(tmp_path)
    first = reg.build_snapshot(at=FIXED_AT).to_dict()
    second = reg.build_snapshot(at=FIXED_AT).to_dict()
    assert first == second


# --- JSON output -----------------------------------------------------------


def test_json_snapshot_round_trips(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    snap = _registry(tmp_path).build_snapshot(at=FIXED_AT)
    payload = json.loads(json.dumps(snap.to_dict()))
    assert payload["count"] == len(snap.states)
    assert "InventoryModel" in payload["status_counts"] or payload["status_counts"]
    inv = next(c for c in payload["capabilities"] if c["capability_name"] == "InventoryModel")
    assert inv["current_status"] == "execution_passed"
    assert inv["pass_count"] == 1


# --- discovery candidates source ------------------------------------------


def test_discovery_candidates_source(tmp_path):
    sf = _session_factory(tmp_path)
    from axiom_core.database import get_session
    with get_session(sf) as session:
        session.add(CandidateCapabilityRow(
            candidate_id="cand_1", capability="SetParameterValue", adapter="revit"))
        session.add(CandidateCapabilityRow(
            candidate_id="cand_2", capability="SetParameterValue", adapter="revit"))
    snap = _registry(tmp_path, session_factory=sf).build_snapshot(at=FIXED_AT)
    spv = snap.get("SetParameterValue")
    assert "discovery" in spv.source_registry
    assert spv.metadata["candidate_count"] == 2


# --- SQLite persistence ----------------------------------------------------


def test_refresh_persists_and_reloads(tmp_path):
    base = tmp_path / "capability_runs"
    last = _exec_bundle(base, "InventoryModel", "crun_1", "passed",
                        "2026-05-01T00:00:00+00:00")
    sf = _session_factory(tmp_path)

    reg = _registry(tmp_path, session_factory=sf)
    refreshed = reg.refresh(at=FIXED_AT)
    assert refreshed.get("InventoryModel").pass_count == 1

    # A brand new registry over the same db must load the persisted state.
    reloaded = _registry(tmp_path, session_factory=sf).load_snapshot()
    assert reloaded is not None
    inv = reloaded.get("InventoryModel")
    assert inv.current_status is CapabilityStatus.EXECUTION_PASSED
    assert inv.pass_count == 1
    assert inv.last_evidence_path == str(last)

    # History rows persisted too.
    history = _registry(tmp_path, session_factory=sf).load_history("InventoryModel")
    assert [e.run_id for e in history.sorted_events()] == ["crun_1"]


def test_refresh_is_idempotent(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    sf = _session_factory(tmp_path)
    reg = _registry(tmp_path, session_factory=sf)
    reg.refresh(at=FIXED_AT)
    reg.refresh(at="2026-06-06T12:00:00+00:00")

    from axiom_core.database import get_session
    from axiom_core.models import CapabilityStateEventRow, CapabilityStateRow
    with get_session(sf) as session:
        assert session.query(CapabilityStateRow).filter_by(
            capability_name="InventoryModel").count() == 1
        # Event history rebuilt, not duplicated.
        assert session.query(CapabilityStateEventRow).filter_by(
            capability_name="InventoryModel").count() == 1


def test_refresh_scans_artifacts_once(tmp_path, monkeypatch):
    # refresh() must derive the persisted state summary and the persisted event
    # history from a single artifact scan (no double-scan race).
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    sf = _session_factory(tmp_path)
    reg = _registry(tmp_path, session_factory=sf)

    calls = {"n": 0}
    real_histories = reg.histories

    def _counting_histories():
        calls["n"] += 1
        return real_histories()

    monkeypatch.setattr(reg, "histories", _counting_histories)
    reg.refresh(at=FIXED_AT)
    assert calls["n"] == 1


def test_state_and_event_rows_share_dataset(tmp_path):
    # The persisted state summary and the persisted event history must describe
    # the same underlying dataset (counts/latest-run derived from the same scan).
    base = tmp_path / "capability_runs"
    _exec_bundle(base, "InventoryModel", "crun_1", "passed",
                 "2026-05-01T00:00:00+00:00")
    _exec_bundle(base, "InventoryModel", "crun_2", "failed",
                 "2026-05-02T00:00:00+00:00", reason="boom")
    sf = _session_factory(tmp_path)
    _registry(tmp_path, session_factory=sf).refresh(at=FIXED_AT)

    from axiom_core.database import get_session
    from axiom_core.models import CapabilityStateEventRow, CapabilityStateRow
    with get_session(sf) as session:
        state = session.query(CapabilityStateRow).filter_by(
            capability_name="InventoryModel").one()
        events = session.query(CapabilityStateEventRow).filter_by(
            capability_name="InventoryModel").all()

    exec_events = [e for e in events if e.kind == "execution"]
    assert {e.run_id for e in exec_events} == {"crun_1", "crun_2"}
    assert state.pass_count == sum(1 for e in exec_events if e.outcome == "passed")
    assert state.fail_count == sum(1 for e in exec_events if e.outcome == "failed")
    # Latest execution pointer agrees with the newest event by (at, run_id).
    assert state.last_execution_run_id == "crun_2"


def test_refresh_consistent_when_artifacts_change_between_scans(tmp_path, monkeypatch):
    # If the filesystem changes mid-refresh, state rows and event rows must NOT
    # split across two scans. We force a concurrent bundle write as a side effect
    # of the (single) histories() call: with a double-scan the second scan would
    # observe crun_2 and the event rows would diverge from the state summary.
    base = tmp_path / "capability_runs"
    _exec_bundle(base, "InventoryModel", "crun_1", "passed",
                 "2026-05-01T00:00:00+00:00")
    sf = _session_factory(tmp_path)
    reg = _registry(tmp_path, session_factory=sf)

    real_histories = reg.histories

    def _mutating_histories():
        result = real_histories()
        # Simulate a concurrent capability run writing a new bundle AFTER the
        # scan that produced ``result``.
        _exec_bundle(base, "InventoryModel", "crun_2", "failed",
                     "2026-05-02T00:00:00+00:00")
        return result

    monkeypatch.setattr(reg, "histories", _mutating_histories)
    reg.refresh(at=FIXED_AT)

    from axiom_core.database import get_session
    from axiom_core.models import CapabilityStateEventRow, CapabilityStateRow
    with get_session(sf) as session:
        state = session.query(CapabilityStateRow).filter_by(
            capability_name="InventoryModel").one()
        events = session.query(CapabilityStateEventRow).filter_by(
            capability_name="InventoryModel").all()

    # Only the pre-change event is persisted, and the summary agrees with it.
    assert {e.run_id for e in events} == {"crun_1"}
    assert state.pass_count == 1
    assert state.fail_count == 0
    assert state.last_execution_run_id == "crun_1"


def test_first_seen_preserved_across_refresh(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    sf = _session_factory(tmp_path)
    reg = _registry(tmp_path, session_factory=sf)
    first = reg.refresh(at=FIXED_AT).get("InventoryModel").first_seen_at
    reg.refresh(at="2026-09-09T12:00:00+00:00")
    reloaded = reg.load_snapshot().get("InventoryModel")
    # first_seen anchored to the earliest evidence, last_seen advances.
    assert reloaded.first_seen_at <= first
    assert reloaded.last_seen_at > reloaded.first_seen_at


# --- CLI -------------------------------------------------------------------


def test_cli_list(tmp_path):
    res = CliRunner().invoke(cli, [
        "capability-state", "--db-path", str(tmp_path / "absent.db"),
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ], env={"COLUMNS": "200"})
    assert res.exit_code == 0, res.output
    assert "Capability State Registry" in res.output
    assert "InventoryModel" in res.output


def test_cli_inspect_json(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    res = CliRunner().invoke(cli, [
        "capability-state", "--name", "InventoryModel", "--json",
        "--db-path", str(tmp_path / "absent.db"),
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["capability_name"] == "InventoryModel"
    assert payload["current_status"] == "execution_passed"


def test_cli_unknown_capability_exits_nonzero(tmp_path):
    res = CliRunner().invoke(cli, [
        "capability-state", "--name", "NopeNotReal",
        "--db-path", str(tmp_path / "absent.db"),
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ])
    assert res.exit_code == 2, res.output


def test_cli_refresh_persists(tmp_path):
    _exec_bundle(tmp_path / "capability_runs", "InventoryModel", "crun_1",
                 "passed", "2026-05-01T00:00:00+00:00")
    db_path = str(tmp_path / "cli.db")
    args = [
        "capability-state", "--refresh", "--db-path", db_path,
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ]
    res = CliRunner().invoke(cli, args)
    assert res.exit_code == 0, res.output
    assert Path(db_path).is_file()

    # Read-only reload from the persisted db.
    res2 = CliRunner().invoke(cli, [
        "capability-state", "--json", "--db-path", db_path,
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ])
    assert res2.exit_code == 0, res2.output
    payload = json.loads(res2.output)
    inv = next(c for c in payload["capabilities"]
               if c["capability_name"] == "InventoryModel")
    assert inv["pass_count"] == 1


def test_cli_readonly_does_not_create_db(tmp_path):
    db_path = tmp_path / "absent.db"
    res = CliRunner().invoke(cli, [
        "capability-state", "--db-path", str(db_path),
        "--capability-runs-dir", str(tmp_path / "capability_runs"),
        "--validation-evidence-dir", str(tmp_path / "validation_evidence"),
    ])
    assert res.exit_code == 0, res.output
    # Read-only must not create a database file.
    assert not db_path.is_file()
