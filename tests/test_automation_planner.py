"""Tests for axiom_core.automation_planner — PR #35."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.automation_planner import (
    LANE_DESKTOP_REVIT,
    LANE_NON_REVIT_DATA,
    LANE_UNKNOWN,
    VALID_EVENT_TYPES,
    VALID_LANES,
    AutomationEvent,
    RecommendedAction,
    apply_policy_gate,
    classify_execution_lane,
    execute_plan_run,
    plan_for_event,
)


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect artifact output to tmp_path for test isolation."""
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path / "Artifacts"))


# ===========================================================================
# Test 1: Event schema validation
# ===========================================================================


class TestEventSchemaValidation:
    """Event schema validation catches invalid events."""

    def test_valid_event_no_errors(self) -> None:
        event = AutomationEvent(
            event_id="evt_001",
            event_type="model_updated",
            source="test",
            model_path=r"C:\Projects\Model.rvt",
        )
        assert event.validate() == []

    def test_missing_event_id(self) -> None:
        event = AutomationEvent(event_id="", event_type="model_updated")
        errors = event.validate()
        assert any("event_id" in e for e in errors)

    def test_missing_event_type(self) -> None:
        event = AutomationEvent(event_id="evt_002", event_type="")
        errors = event.validate()
        assert any("event_type" in e for e in errors)

    def test_invalid_event_type(self) -> None:
        event = AutomationEvent(event_id="evt_003", event_type="invalid_type")
        errors = event.validate()
        assert any("not in" in e for e in errors)

    def test_invalid_source(self) -> None:
        event = AutomationEvent(event_id="evt_004", event_type="model_updated", source="bad_source")
        errors = event.validate()
        assert any("source" in e for e in errors)

    def test_all_valid_event_types_pass(self) -> None:
        for etype in VALID_EVENT_TYPES:
            event = AutomationEvent(event_id="evt_x", event_type=etype, source="test")
            assert event.validate() == [], f"{etype} failed validation"

    def test_timestamp_auto_populated(self) -> None:
        event = AutomationEvent(event_id="evt_005", event_type="model_updated")
        assert event.timestamp_utc != ""

    def test_to_dict_roundtrip(self) -> None:
        event = AutomationEvent(
            event_id="evt_006",
            event_type="ruleset_updated",
            project_id="proj_abc",
            model_path=r"C:\Revit\test.rvt",
            changed_fields=["grids", "levels"],
            source="test",
        )
        d = event.to_dict()
        assert d["event_id"] == "evt_006"
        assert d["event_type"] == "ruleset_updated"
        assert d["changed_fields"] == ["grids", "levels"]


# ===========================================================================
# Test 2: Model-updated event creates recommended health check
# ===========================================================================


class TestModelUpdatedPlanning:
    """model_updated events recommend health/readiness checks."""

    def test_model_updated_recommends_health(self) -> None:
        event = AutomationEvent(event_id="evt_mu_01", event_type="model_updated", source="test")
        plan = plan_for_event(event)

        assert len(plan.recommended_actions) >= 1
        health_actions = [a for a in plan.recommended_actions if a.capability_id == "model_health"]
        assert len(health_actions) == 1
        assert health_actions[0].recommended_mode == "health_check"

    def test_model_updated_low_risk(self) -> None:
        event = AutomationEvent(event_id="evt_mu_02", event_type="model_updated", source="test")
        plan = plan_for_event(event)

        for action in plan.recommended_actions:
            assert action.risk_level == "low"

    def test_model_updated_next_step_not_empty(self) -> None:
        event = AutomationEvent(event_id="evt_mu_03", event_type="model_updated", source="test")
        plan = plan_for_event(event)

        for action in plan.recommended_actions:
            assert action.next_step != ""


# ===========================================================================
# Test 3: Ruleset-updated event recommends readiness re-evaluation
# ===========================================================================


class TestRulesetUpdatedPlanning:
    """ruleset_updated events recommend both health check and GridCreation dry-run."""

    def test_ruleset_updated_multiple_actions(self) -> None:
        event = AutomationEvent(event_id="evt_ru_01", event_type="ruleset_updated", source="test")
        plan = plan_for_event(event)

        assert len(plan.recommended_actions) >= 2
        cap_ids = [a.capability_id for a in plan.recommended_actions]
        assert "model_health" in cap_ids
        assert "grid_creation" in cap_ids

    def test_ruleset_updated_grid_creation_dry_run(self) -> None:
        event = AutomationEvent(event_id="evt_ru_02", event_type="ruleset_updated", source="test")
        plan = plan_for_event(event)

        grid_action = next(a for a in plan.recommended_actions if a.capability_id == "grid_creation")
        assert grid_action.recommended_mode == "dry_run"
        assert grid_action.risk_level == "medium"


# ===========================================================================
# Test 4: GridCreation impact classification
# ===========================================================================


class TestGridCreationImpact:
    """GridCreation actions are classified correctly."""

    def test_grid_creation_execute_desktop_revit(self) -> None:
        lane = classify_execution_lane("grid_creation", "execute")
        assert lane == LANE_DESKTOP_REVIT

    def test_grid_creation_dry_run_desktop_revit(self) -> None:
        lane = classify_execution_lane("grid_creation", "dry_run")
        assert lane == LANE_DESKTOP_REVIT

    def test_grid_creation_health_check_desktop_revit(self) -> None:
        lane = classify_execution_lane("grid_creation", "health_check")
        assert lane == LANE_DESKTOP_REVIT


# ===========================================================================
# Test 5: Execution lane classification
# ===========================================================================


class TestExecutionLaneClassification:
    """Execution lane classifier returns correct lanes."""

    def test_model_health_report_non_revit(self) -> None:
        lane = classify_execution_lane("model_health_report", "health_check")
        assert lane == LANE_NON_REVIT_DATA

    def test_report_generation_non_revit(self) -> None:
        lane = classify_execution_lane("report_generation", "dry_run")
        assert lane == LANE_NON_REVIT_DATA

    def test_artifact_query_non_revit(self) -> None:
        lane = classify_execution_lane("artifact_query", "dry_run")
        assert lane == LANE_NON_REVIT_DATA

    def test_model_health_desktop_revit(self) -> None:
        lane = classify_execution_lane("model_health", "health_check")
        assert lane == LANE_DESKTOP_REVIT

    def test_project_setup_desktop_revit(self) -> None:
        lane = classify_execution_lane("project_setup", "execute")
        assert lane == LANE_DESKTOP_REVIT

    def test_unknown_capability_unknown_lane(self) -> None:
        lane = classify_execution_lane("some_future_capability", "execute")
        assert lane == LANE_UNKNOWN

    def test_all_lanes_valid(self) -> None:
        for lane in VALID_LANES:
            assert lane in {"desktop_revit", "aps", "non_revit_data", "unknown"}


# ===========================================================================
# Test 6: High-risk action requires approval
# ===========================================================================


class TestPolicyGate:
    """Policy gate enforces approval requirements."""

    def test_high_risk_never_auto_executes(self) -> None:
        action = RecommendedAction(
            capability_id="grid_creation",
            reason="test",
            recommended_mode="execute",
            risk_level="high",
        )
        decision = apply_policy_gate(action)
        assert decision.auto_execute_allowed is False
        assert decision.approval_required is True
        assert "High-risk" in decision.reason

    def test_execute_mode_requires_approval(self) -> None:
        action = RecommendedAction(
            capability_id="grid_creation",
            reason="test",
            recommended_mode="execute",
            risk_level="low",
        )
        decision = apply_policy_gate(action)
        assert decision.auto_execute_allowed is False
        assert decision.approval_required is True

    def test_medium_risk_requires_approval(self) -> None:
        action = RecommendedAction(
            capability_id="grid_creation",
            reason="test",
            recommended_mode="dry_run",
            risk_level="medium",
        )
        decision = apply_policy_gate(action)
        assert decision.auto_execute_allowed is False
        assert decision.approval_required is True

    def test_low_risk_health_check_still_requires_approval(self) -> None:
        action = RecommendedAction(
            capability_id="model_health",
            reason="test",
            recommended_mode="health_check",
            risk_level="low",
        )
        decision = apply_policy_gate(action)
        assert decision.auto_execute_allowed is False
        assert decision.approval_required is True
        assert decision.dry_run_recommended is True

    def test_no_action_auto_executes(self) -> None:
        """No combination of risk/mode should auto-execute in default policy."""
        for risk in ("low", "medium", "high"):
            for mode in ("health_check", "dry_run", "execute"):
                action = RecommendedAction(
                    capability_id="x", reason="t", recommended_mode=mode, risk_level=risk
                )
                decision = apply_policy_gate(action)
                assert decision.auto_execute_allowed is False


# ===========================================================================
# Test 7: Planner writes artifacts and audit entry
# ===========================================================================


class TestPlannerArtifacts:
    """execute_plan_run produces spine artifacts and audit entries."""

    def test_plan_run_creates_artifacts(self, tmp_path: Path) -> None:
        event = AutomationEvent(
            event_id="evt_art_01",
            event_type="model_updated",
            model_path=r"C:\Dev\Projects\Test.rvt",
            source="test",
        )
        result = execute_plan_run(event)

        assert result["error"] is False
        folder = Path(result["artifact_path"])
        assert (folder / "automation_plan.json").exists()
        assert (folder / "automation_plan.md").exists()
        assert (folder / "policy_gate.json").exists()
        assert (folder / "run_metadata.json").exists()
        assert (folder / "command_input.json").exists()
        assert (folder / "execution_result.json").exists()
        assert (folder / "external_calls.json").exists()
        assert (folder / "artifact_manifest.json").exists()
        assert (folder / "dialog_events.json").exists()
        assert (folder / "ui_automation_risk.json").exists()

    def test_plan_run_audit_entries(self, tmp_path: Path) -> None:
        event = AutomationEvent(event_id="evt_art_02", event_type="model_updated", source="test")
        execute_plan_run(event)

        audit_path = tmp_path / "Artifacts" / "audit" / "axiom_command_log.jsonl"
        assert audit_path.exists()
        lines = [json.loads(line) for line in audit_path.read_text().strip().split("\n")]
        planner_entries = [e for e in lines if e["capability"] == "AutomationPlanner"]
        assert len(planner_entries) >= 2
        statuses = [e["status"] for e in planner_entries]
        assert "started" in statuses
        assert "completed" in statuses

    def test_plan_run_plan_content(self, tmp_path: Path) -> None:
        event = AutomationEvent(event_id="evt_art_03", event_type="ruleset_updated", source="test")
        result = execute_plan_run(event)

        plan_data = json.loads(
            (Path(result["artifact_path"]) / "automation_plan.json").read_text()
        )
        assert plan_data["event_id"] == "evt_art_03"
        assert len(plan_data["recommended_actions"]) >= 2

    def test_plan_run_policy_gate_content(self, tmp_path: Path) -> None:
        event = AutomationEvent(event_id="evt_art_04", event_type="model_updated", source="test")
        result = execute_plan_run(event)

        gate_data = json.loads(
            (Path(result["artifact_path"]) / "policy_gate.json").read_text()
        )
        assert gate_data["event_id"] == "evt_art_04"
        assert len(gate_data["decisions"]) >= 1
        for decision in gate_data["decisions"]:
            assert decision["auto_execute_allowed"] is False

    def test_invalid_event_returns_error(self) -> None:
        event = AutomationEvent(event_id="", event_type="bad_type")
        result = execute_plan_run(event)

        assert result["error"] is True
        assert result["error_type"] == "EventValidationError"
        assert len(result["errors"]) >= 2

    def test_plan_run_manifest_includes_plan_files(self, tmp_path: Path) -> None:
        event = AutomationEvent(event_id="evt_art_05", event_type="model_updated", source="test")
        result = execute_plan_run(event)

        manifest = json.loads(
            (Path(result["artifact_path"]) / "artifact_manifest.json").read_text()
        )
        assert "automation_plan.json" in manifest["files"]
        assert "automation_plan.md" in manifest["files"]
        assert "policy_gate.json" in manifest["files"]

    def test_plan_run_model_path_redacted_in_input(self, tmp_path: Path) -> None:
        event = AutomationEvent(
            event_id="evt_art_06",
            event_type="model_updated",
            model_path=r"C:\Users\JohnDoe\Projects\Secret.rvt",
            source="test",
        )
        result = execute_plan_run(event)

        input_data = json.loads(
            (Path(result["artifact_path"]) / "command_input.json").read_text()
        )
        # Top-level model_path must be redacted
        assert "JohnDoe" not in input_data["model_path"]
        assert "***" in input_data["model_path"]
        # Nested event.model_path must also be redacted
        assert "JohnDoe" not in input_data["event"]["model_path"]
        assert "***" in input_data["event"]["model_path"]
