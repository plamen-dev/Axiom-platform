"""Tests for Axiom Dialog Watcher and UI-Automation Risk Logging (PR #34).

Covers:
1. Dialog events file creation.
2. No-dialog run produces empty event list.
3. Simulated blocking dialog causes BLOCKED_BY_DIALOG.
4. UI automation risk defaults to false.
5. UI automation risk can be declared.
6. Existing runs still pass without dialog watcher.
7. Dialog events are included in artifact manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.dialog_watcher import (
    BLOCKED_BY_DIALOG,
    VALID_EVENT_TYPES,
    VALID_RISK_LEVELS,
    VALID_SEVERITIES,
    DialogEvent,
    DialogEventsRecord,
    DialogWatcher,
    UIAutomationRisk,
    write_default_dialog_artifacts,
)
from axiom_core.run_spine import RunContext, execute_run


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect artifact output to tmp_path for test isolation."""
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))


# ===========================================================================
# Test 1: Dialog events file creation
# ===========================================================================


class TestDialogEventsFileCreation:
    """Dialog watcher writes dialog_events.json with correct schema."""

    def test_writes_json_with_events(self, tmp_path: Path) -> None:
        folder = tmp_path / "run1"
        folder.mkdir()

        watcher = DialogWatcher(run_id="test_run_001")
        watcher.record_event(DialogEvent(
            event_type="dialog_opened",
            title="Save As",
            text="Would you like to save?",
            severity="info",
            action_taken="logged",
        ))
        watcher.write_artifacts(folder)

        events_file = folder / "dialog_events.json"
        assert events_file.exists()
        data = json.loads(events_file.read_text())
        assert data["run_id"] == "test_run_001"
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "dialog_opened"
        assert data["events"][0]["title"] == "Save As"
        assert data["events"][0]["severity"] == "info"
        assert data["events"][0]["action_taken"] == "logged"

    def test_writes_markdown_with_events(self, tmp_path: Path) -> None:
        folder = tmp_path / "run2"
        folder.mkdir()

        watcher = DialogWatcher(run_id="test_run_002")
        watcher.record_event(DialogEvent(
            event_type="modal_detected",
            title="Error",
            severity="warning",
        ))
        watcher.write_artifacts(folder)

        md_file = folder / "dialog_events.md"
        assert md_file.exists()
        content = md_file.read_text()
        assert "test_run_002" in content
        assert "Error" in content
        assert "modal_detected" in content

    def test_writes_ui_risk_file(self, tmp_path: Path) -> None:
        folder = tmp_path / "run3"
        folder.mkdir()

        watcher = DialogWatcher(run_id="test_run_003")
        watcher.write_artifacts(folder)

        risk_file = folder / "ui_automation_risk.json"
        assert risk_file.exists()
        data = json.loads(risk_file.read_text())
        assert "ui_automation_used" in data
        assert "risk_level" in data


# ===========================================================================
# Test 2: No-dialog run produces empty event list
# ===========================================================================


class TestNoDialogRun:
    """A clean run with no dialog events produces an empty list."""

    def test_empty_events_json(self, tmp_path: Path) -> None:
        folder = tmp_path / "clean_run"
        folder.mkdir()

        watcher = DialogWatcher(run_id="clean_001")
        watcher.write_artifacts(folder)

        data = json.loads((folder / "dialog_events.json").read_text())
        assert data["events"] == []
        assert data["run_id"] == "clean_001"

    def test_empty_events_markdown(self, tmp_path: Path) -> None:
        folder = tmp_path / "clean_run2"
        folder.mkdir()

        watcher = DialogWatcher(run_id="clean_002")
        watcher.write_artifacts(folder)

        content = (folder / "dialog_events.md").read_text()
        assert "No dialog events were observed" in content

    def test_no_blocking(self, tmp_path: Path) -> None:
        watcher = DialogWatcher(run_id="clean_003")
        assert watcher.has_blocking_event is False
        assert watcher.failure_classification is None

    def test_default_artifacts_helper(self, tmp_path: Path) -> None:
        folder = tmp_path / "default_run"
        folder.mkdir()

        write_default_dialog_artifacts(folder, "default_001")

        assert (folder / "dialog_events.json").exists()
        assert (folder / "dialog_events.md").exists()
        assert (folder / "ui_automation_risk.json").exists()
        data = json.loads((folder / "dialog_events.json").read_text())
        assert data["events"] == []


# ===========================================================================
# Test 3: Simulated blocking dialog causes BLOCKED_BY_DIALOG
# ===========================================================================


class TestBlockingDialog:
    """A blocking dialog event triggers BLOCKED_BY_DIALOG classification."""

    def test_blocking_event_classification(self) -> None:
        watcher = DialogWatcher(run_id="blocked_001")
        watcher.record_event(DialogEvent(
            event_type="modal_detected",
            title="File Not Found",
            text="The linked model could not be located.",
            severity="blocking",
            action_taken="failed_run",
        ))

        assert watcher.has_blocking_event is True
        assert watcher.failure_classification == BLOCKED_BY_DIALOG

    def test_blocking_in_record(self) -> None:
        record = DialogEventsRecord(
            run_id="blocked_002",
            events=[
                DialogEvent(severity="info"),
                DialogEvent(severity="blocking", event_type="unknown_ui_blocker"),
            ],
        )
        assert record.has_blocking_event is True
        assert record.failure_classification == BLOCKED_BY_DIALOG

    def test_non_blocking_events_do_not_trigger(self) -> None:
        watcher = DialogWatcher(run_id="info_001")
        watcher.record_event(DialogEvent(severity="info"))
        watcher.record_event(DialogEvent(severity="warning"))

        assert watcher.has_blocking_event is False
        assert watcher.failure_classification is None

    def test_blocking_dialog_fails_run_via_spine(self) -> None:
        """A blocking dialog watcher causes execute_run to fail."""
        watcher = DialogWatcher(run_id="will_be_overwritten")
        watcher.record_event(DialogEvent(
            event_type="modal_detected",
            title="Desktop Connector Error",
            severity="blocking",
            action_taken="failed_run",
        ))

        ctx = RunContext(
            capability="GridCreation",
            dialog_watcher=watcher,
        )
        result = execute_run(ctx)

        assert result.status == "failed"
        assert result.error_data is not None
        assert result.error_data["error_type"] == "BLOCKED_BY_DIALOG"

    def test_blocking_markdown_mentions_classification(self, tmp_path: Path) -> None:
        folder = tmp_path / "blocked_md"
        folder.mkdir()

        watcher = DialogWatcher(run_id="blocked_md_001")
        watcher.record_event(DialogEvent(
            event_type="dialog_opened",
            title="Worksharing conflict",
            severity="blocking",
        ))
        watcher.write_artifacts(folder)

        content = (folder / "dialog_events.md").read_text()
        assert "BLOCKED_BY_DIALOG" in content
        assert "Blocking events:" in content


# ===========================================================================
# Test 4: UI automation risk defaults to false
# ===========================================================================


class TestUIAutomationRiskDefaults:
    """UI automation risk defaults to no automation used."""

    def test_default_values(self) -> None:
        risk = UIAutomationRisk()
        d = risk.to_dict()
        assert d["ui_automation_used"] is False
        assert d["ui_automation_reason"] == ""
        assert d["official_api_available"] is None
        assert d["risk_level"] == "none"
        assert d["notes"] == ""

    def test_default_in_watcher(self, tmp_path: Path) -> None:
        folder = tmp_path / "default_risk"
        folder.mkdir()

        watcher = DialogWatcher(run_id="risk_default_001")
        watcher.write_artifacts(folder)

        data = json.loads((folder / "ui_automation_risk.json").read_text())
        assert data["ui_automation_used"] is False
        assert data["risk_level"] == "none"

    def test_spine_produces_default_risk(self) -> None:
        """execute_run without dialog_watcher produces default risk file."""
        ctx = RunContext(capability="GridCreation")
        result = execute_run(ctx)

        risk_file = Path(result.artifact_path) / "ui_automation_risk.json"
        assert risk_file.exists()
        data = json.loads(risk_file.read_text())
        assert data["ui_automation_used"] is False
        assert data["risk_level"] == "none"


# ===========================================================================
# Test 5: UI automation risk can be declared
# ===========================================================================


class TestUIAutomationRiskDeclaration:
    """UI automation risk can be explicitly set."""

    def test_declared_risk(self, tmp_path: Path) -> None:
        folder = tmp_path / "declared_risk"
        folder.mkdir()

        risk = UIAutomationRisk(
            ui_automation_used=True,
            ui_automation_reason="Desktop Connector has no API for sync status.",
            official_api_available=False,
            risk_level="high",
            notes="Used SendKeys to dismiss Desktop Connector sync dialog.",
        )
        watcher = DialogWatcher(run_id="risk_declared_001")
        watcher.write_artifacts(folder, ui_risk=risk)

        data = json.loads((folder / "ui_automation_risk.json").read_text())
        assert data["ui_automation_used"] is True
        assert data["risk_level"] == "high"
        assert "Desktop Connector" in data["ui_automation_reason"]
        assert data["official_api_available"] is False

    def test_low_risk_api_alternative(self, tmp_path: Path) -> None:
        folder = tmp_path / "low_risk"
        folder.mkdir()

        risk = UIAutomationRisk(
            ui_automation_used=True,
            ui_automation_reason="Auto-dismissed known save prompt.",
            official_api_available=True,
            risk_level="low",
            notes="Official API exists but requires Revit restart.",
        )
        watcher = DialogWatcher(run_id="risk_low_001")
        watcher.write_artifacts(folder, ui_risk=risk)

        data = json.loads((folder / "ui_automation_risk.json").read_text())
        assert data["ui_automation_used"] is True
        assert data["risk_level"] == "low"
        assert data["official_api_available"] is True


# ===========================================================================
# Test 6: Existing runs still pass without dialog watcher
# ===========================================================================


class TestExistingRunsUnaffected:
    """Runs without a dialog watcher still succeed and produce artifacts."""

    def test_basic_dry_run_no_watcher(self) -> None:
        ctx = RunContext(capability="GridCreation", mode="dry_run")
        result = execute_run(ctx)

        assert result.status == "completed"
        folder = Path(result.artifact_path)
        assert (folder / "run_metadata.json").exists()
        assert (folder / "execution_result.json").exists()
        assert (folder / "external_calls.json").exists()

    def test_failed_run_no_watcher(self) -> None:
        def failing_executor(ctx: RunContext) -> dict:
            raise RuntimeError("Test failure")

        ctx = RunContext(capability="GridCreation")
        result = execute_run(ctx, executor=failing_executor)

        assert result.status == "failed"
        assert result.error_data is not None
        assert result.error_data["error_type"] == "RuntimeError"

    def test_dialog_files_produced_even_without_watcher(self) -> None:
        """Default dialog artifacts are written even when no watcher is passed."""
        ctx = RunContext(capability="GridCreation")
        result = execute_run(ctx)

        folder = Path(result.artifact_path)
        assert (folder / "dialog_events.json").exists()
        assert (folder / "dialog_events.md").exists()
        assert (folder / "ui_automation_risk.json").exists()


# ===========================================================================
# Test 7: Dialog events are included in artifact manifest
# ===========================================================================


class TestManifestInclusion:
    """Dialog and UI-risk files appear in artifact_manifest.json."""

    def test_manifest_includes_dialog_files(self) -> None:
        ctx = RunContext(capability="GridCreation")
        result = execute_run(ctx)

        manifest_file = Path(result.artifact_path) / "artifact_manifest.json"
        manifest = json.loads(manifest_file.read_text())

        assert "dialog_events.json" in manifest["files"]
        assert "dialog_events.md" in manifest["files"]
        assert "ui_automation_risk.json" in manifest["files"]

    def test_manifest_includes_dialog_files_with_watcher(self) -> None:
        watcher = DialogWatcher(run_id="manifest_test")
        watcher.record_event(DialogEvent(
            event_type="dialog_opened",
            title="Sync",
            severity="info",
        ))

        ctx = RunContext(capability="GridCreation", dialog_watcher=watcher)
        result = execute_run(ctx)

        manifest_file = Path(result.artifact_path) / "artifact_manifest.json"
        manifest = json.loads(manifest_file.read_text())

        assert "dialog_events.json" in manifest["files"]
        assert "dialog_events.md" in manifest["files"]
        assert "ui_automation_risk.json" in manifest["files"]


# ===========================================================================
# Test 8: DialogWatcher run_id synced to actual run ID (bug fix)
# ===========================================================================


class TestRunIdSync:
    """Watcher run_id is updated to match the spine-generated run_id."""

    def test_run_id_matches_in_artifacts(self) -> None:
        """dialog_events.json run_id must match run_metadata.json run_id."""
        watcher = DialogWatcher(run_id="placeholder_will_be_overwritten")
        watcher.record_event(DialogEvent(
            event_type="dialog_opened",
            title="Test",
            severity="info",
        ))

        ctx = RunContext(capability="GridCreation", dialog_watcher=watcher)
        result = execute_run(ctx)

        folder = Path(result.artifact_path)
        events = json.loads((folder / "dialog_events.json").read_text())
        metadata = json.loads((folder / "run_metadata.json").read_text())

        assert events["run_id"] == metadata["run_id"]
        assert events["run_id"] == result.run_id
        assert events["run_id"] != "placeholder_will_be_overwritten"

    def test_watcher_run_id_updated_after_execute(self) -> None:
        watcher = DialogWatcher(run_id="old_id")
        ctx = RunContext(capability="GridCreation", dialog_watcher=watcher)
        result = execute_run(ctx)

        assert watcher.run_id == result.run_id


# ===========================================================================
# Test 9: UI automation risk passed through RunContext
# ===========================================================================


class TestUIRiskPassthrough:
    """UIAutomationRisk from RunContext is written to artifacts."""

    def test_risk_from_context(self) -> None:
        watcher = DialogWatcher(run_id="x")
        risk = UIAutomationRisk(
            ui_automation_used=True,
            ui_automation_reason="Desktop Connector sync",
            risk_level="high",
        )

        ctx = RunContext(
            capability="GridCreation",
            dialog_watcher=watcher,
            ui_automation_risk=risk,
        )
        result = execute_run(ctx)

        data = json.loads(
            (Path(result.artifact_path) / "ui_automation_risk.json").read_text()
        )
        assert data["ui_automation_used"] is True
        assert data["risk_level"] == "high"
        assert "Desktop Connector" in data["ui_automation_reason"]

    def test_default_risk_when_no_context_risk(self) -> None:
        """Without ui_automation_risk in context, default (no risk) is written."""
        watcher = DialogWatcher(run_id="y")
        ctx = RunContext(capability="GridCreation", dialog_watcher=watcher)
        result = execute_run(ctx)

        data = json.loads(
            (Path(result.artifact_path) / "ui_automation_risk.json").read_text()
        )
        assert data["ui_automation_used"] is False
        assert data["risk_level"] == "none"


# ===========================================================================
# Test 10: Valid enum constants
# ===========================================================================


class TestEnumConstants:
    """Validate that enum constant sets are correct."""

    def test_valid_event_types(self) -> None:
        assert "dialog_opened" in VALID_EVENT_TYPES
        assert "modal_detected" in VALID_EVENT_TYPES
        assert "unknown_ui_blocker" in VALID_EVENT_TYPES

    def test_valid_severities(self) -> None:
        assert "info" in VALID_SEVERITIES
        assert "warning" in VALID_SEVERITIES
        assert "blocking" in VALID_SEVERITIES

    def test_valid_risk_levels(self) -> None:
        assert "none" in VALID_RISK_LEVELS
        assert "low" in VALID_RISK_LEVELS
        assert "medium" in VALID_RISK_LEVELS
        assert "high" in VALID_RISK_LEVELS
