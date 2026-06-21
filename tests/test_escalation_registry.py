"""Tests for EscalationRegistry and Escalation Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.escalation_registry import (
    Escalation,
    EscalationCategory,
    EscalationRegistry,
    EscalationSeverity,
    EscalationStatus,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEscalationStatus:
    def test_values(self) -> None:
        assert EscalationStatus.OPEN.value == "open"
        assert EscalationStatus.ACKNOWLEDGED.value == "acknowledged"
        assert EscalationStatus.IN_PROGRESS.value == "in_progress"
        assert EscalationStatus.RESOLVED.value == "resolved"
        assert EscalationStatus.CLOSED.value == "closed"

    def test_count(self) -> None:
        assert len(EscalationStatus) == 5


class TestEscalationSeverity:
    def test_values(self) -> None:
        assert EscalationSeverity.NONE.value == "none"
        assert EscalationSeverity.INFO.value == "info"
        assert EscalationSeverity.WARNING.value == "warning"
        assert EscalationSeverity.BLOCKER.value == "blocker"
        assert EscalationSeverity.HUMAN_REQUIRED.value == "human_required"

    def test_count(self) -> None:
        assert len(EscalationSeverity) == 5


class TestEscalationCategory:
    def test_values(self) -> None:
        assert EscalationCategory.EVIDENCE_GAP.value == "evidence_gap"
        assert EscalationCategory.ARCHITECTURE.value == "architecture"
        assert EscalationCategory.VALIDATION.value == "validation"
        assert EscalationCategory.REPEATED_FAILURE.value == "repeated_failure"
        assert EscalationCategory.DEPENDENCY.value == "dependency"
        assert EscalationCategory.CONFLICT.value == "conflict"
        assert EscalationCategory.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(EscalationCategory) == 7


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestEscalationDataclass:
    def test_defaults(self) -> None:
        e = Escalation(title="Test")
        assert e.title == "Test"
        assert e.escalation_id
        assert e.status == "open"
        assert e.severity == "info"
        assert e.category == "other"
        assert e.reason == ""
        assert e.created_at
        assert e.updated_at == e.created_at

    def test_custom_fields(self) -> None:
        e = Escalation(
            title="Custom",
            description="Desc",
            reason="Missing evidence for assertion",
            severity="blocker",
            category="architecture",
            source="devin",
        )
        assert e.severity == "blocker"
        assert e.category == "architecture"
        assert e.source == "devin"
        assert e.reason == "Missing evidence for assertion"

    def test_to_dict(self) -> None:
        e = Escalation(title="Dict Test")
        d = e.to_dict()
        assert d["title"] == "Dict Test"
        assert d["escalation_id"] == e.escalation_id
        assert d["status"] == "open"
        assert d["reason"] == ""
        assert "created_at" in d
        assert "updated_at" in d
        assert "resolved_at" in d

    def test_to_dict_with_reason(self) -> None:
        e = Escalation(title="R", reason="Some rationale")
        d = e.to_dict()
        assert d["reason"] == "Some rationale"


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateEscalation:
    def test_basic(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        assert esc["title"] == "Test"
        assert esc["escalation_id"]
        assert esc["status"] == "open"
        assert esc["severity"] == "info"
        assert esc["category"] == "other"

    def test_all_fields(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(
            title="Full",
            description="Full desc",
            reason="Repeated CI failure on validation",
            severity="human_required",
            category="evidence_gap",
            source="ci",
        )
        assert esc["severity"] == "human_required"
        assert esc["category"] == "evidence_gap"
        assert esc["source"] == "ci"
        assert esc["reason"] == "Repeated CI failure on validation"
        assert esc["description"] == "Full desc"

    def test_invalid_severity(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid severity"):
            reg.create_escalation(title="Bad", severity="extreme")

    def test_invalid_category(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid category"):
            reg.create_escalation(title="Bad", category="nonexistent")


class TestGetEscalation:
    def test_existing(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        created = reg.create_escalation(title="Get Me")
        found = reg.get_escalation(created["escalation_id"])
        assert found is not None
        assert found["title"] == "Get Me"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        assert reg.get_escalation("does-not-exist") is None


class TestListEscalations:
    def test_empty(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        assert reg.list_escalations() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        reg.create_escalation(title="A", severity="info")
        reg.create_escalation(title="B", severity="blocker")
        result = reg.list_escalations()
        assert len(result) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        reg.create_escalation(title="Info", severity="info")
        reg.create_escalation(title="Human Required", severity="human_required")
        reg.create_escalation(title="Blocker", severity="blocker")
        result = reg.list_escalations()
        severities = [e["severity"] for e in result]
        assert severities == ["human_required", "blocker", "info"]

    def test_filter_status(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Resolve Me")
        reg.update_status(esc["escalation_id"], "resolved")
        reg.create_escalation(title="Still Open")
        open_list = reg.list_escalations(status="open")
        assert len(open_list) == 1
        assert open_list[0]["title"] == "Still Open"

    def test_filter_severity(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        reg.create_escalation(title="A", severity="info")
        reg.create_escalation(title="B", severity="blocker")
        blockers = reg.list_escalations(severity="blocker")
        assert len(blockers) == 1
        assert blockers[0]["title"] == "B"

    def test_filter_category(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        reg.create_escalation(title="A", category="architecture")
        reg.create_escalation(title="B", category="validation")
        arch = reg.list_escalations(category="architecture")
        assert len(arch) == 1
        assert arch[0]["title"] == "A"


class TestUpdateStatus:
    def test_update_to_acknowledged(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        updated = reg.update_status(esc["escalation_id"], "acknowledged")
        assert updated["status"] == "acknowledged"

    def test_update_to_resolved(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        updated = reg.update_status(
            esc["escalation_id"], "resolved", resolution_notes="Fixed it",
        )
        assert updated["status"] == "resolved"
        assert updated["resolution_notes"] == "Fixed it"
        assert updated["resolved_at"]

    def test_update_to_closed(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        updated = reg.update_status(esc["escalation_id"], "closed")
        assert updated["status"] == "closed"
        assert updated["resolved_at"]

    def test_update_nonexistent(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.update_status("nope", "acknowledged")

    def test_update_invalid_status(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        with pytest.raises(ValueError, match="Invalid status"):
            reg.update_status(esc["escalation_id"], "bogus")

    def test_update_timestamps(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        updated = reg.update_status(esc["escalation_id"], "in_progress")
        assert updated["updated_at"] >= esc["created_at"]

    def test_resolved_at_not_overwritten(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Test")
        resolved = reg.update_status(esc["escalation_id"], "resolved")
        closed = reg.update_status(esc["escalation_id"], "closed")
        assert closed["resolved_at"] == resolved["resolved_at"]


class TestExportEscalation:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(
            title="Export Me",
            description="Some description",
            reason="Evidence gap in validation",
            severity="blocker",
            category="architecture",
            source="review",
        )
        md = reg.export_escalation(esc["escalation_id"])
        assert "# Escalation: Export Me" in md
        assert "blocker" in md
        assert "architecture" in md
        assert "Some description" in md
        assert "Evidence gap in validation" in md
        assert "review" in md

    def test_export_with_resolution(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Resolved")
        reg.update_status(esc["escalation_id"], "resolved", resolution_notes="All fixed")
        md = reg.export_escalation(esc["escalation_id"])
        assert "## Resolution" in md
        assert "All fixed" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_escalation("nope")


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Evidence Test")
        evidence_dir = reg.write_evidence(esc["escalation_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "escalation_request.json").exists()
        assert (ev_path / "escalation_result.json").exists()
        assert (ev_path / "escalation_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_content_valid_json(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="JSON Test")
        evidence_dir = reg.write_evidence(esc["escalation_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "escalation_request.json",
            "escalation_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_open(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Open")
        evidence_dir = reg.write_evidence(esc["escalation_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False

    def test_pass_fail_resolved(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="Resolved")
        reg.update_status(esc["escalation_id"], "resolved")
        evidence_dir = reg.write_evidence(esc["escalation_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is True

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")

    def test_evidence_summary_md_content(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        esc = reg.create_escalation(title="MD Test", reason="Test reason")
        evidence_dir = reg.write_evidence(esc["escalation_id"])
        md = (Path(evidence_dir) / "escalation_summary.md").read_text(encoding="utf-8")
        assert "# Escalation: MD Test" in md
        assert "Test reason" in md


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_escalation("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_escalation("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_escalation("../etc/passwd")

    def test_forward_slash(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_escalation("foo/bar")

    def test_backslash(self, tmp_path: Path) -> None:
        reg = EscalationRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_escalation("foo\\bar")


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_escalation_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "escalation-create",
            "escalations",
            "escalation-show",
            "escalation-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_escalation_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("escalation-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "escalation_request.json" in locations
        assert "escalation_result.json" in locations
        assert "escalation_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/escalation_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_escalation_registry.py"
