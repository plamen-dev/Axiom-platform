"""Tests for RepairDecisionRegistry and Repair Decision Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.repair_decision_registry import (
    RepairDecision,
    RepairDecisionReason,
    RepairDecisionRegistry,
    RepairDecisionSource,
    RepairDecisionStatus,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestRepairDecisionStatus:
    def test_values(self) -> None:
        assert RepairDecisionStatus.ACCEPTED.value == "accepted"
        assert RepairDecisionStatus.REJECTED.value == "rejected"
        assert RepairDecisionStatus.DEFERRED.value == "deferred"
        assert RepairDecisionStatus.SUPERSEDED.value == "superseded"

    def test_count(self) -> None:
        assert len(RepairDecisionStatus) == 4


class TestRepairDecisionSource:
    def test_values(self) -> None:
        assert RepairDecisionSource.REPAIR_PROPOSAL.value == "repair_proposal"
        assert RepairDecisionSource.ESCALATION.value == "escalation"
        assert RepairDecisionSource.REVIEW_FINDING.value == "review_finding"
        assert RepairDecisionSource.VALIDATION.value == "validation"

    def test_count(self) -> None:
        assert len(RepairDecisionSource) == 4


class TestRepairDecisionReason:
    def test_values(self) -> None:
        assert RepairDecisionReason.TECHNICAL.value == "technical"
        assert RepairDecisionReason.POLICY.value == "policy"
        assert RepairDecisionReason.RISK.value == "risk"
        assert RepairDecisionReason.DUPLICATE.value == "duplicate"
        assert RepairDecisionReason.HUMAN_JUDGMENT.value == "human_judgment"
        assert RepairDecisionReason.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(RepairDecisionReason) == 6


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestRepairDecisionDataclass:
    def test_defaults(self) -> None:
        d = RepairDecision(title="Test")
        assert d.title == "Test"
        assert d.decision_id
        assert d.status == "accepted"
        assert d.source == "repair_proposal"
        assert d.reason == "other"
        assert d.proposal_id == ""
        assert d.rationale == ""
        assert d.notes == ""
        assert d.created_at

    def test_custom_fields(self) -> None:
        d = RepairDecision(
            title="Custom",
            proposal_id="prop-123",
            description="Reject the fix",
            source="escalation",
            status="rejected",
            reason="risk",
            rationale="Too risky for production",
            notes="Revisit after v2",
        )
        assert d.proposal_id == "prop-123"
        assert d.source == "escalation"
        assert d.status == "rejected"
        assert d.reason == "risk"
        assert d.rationale == "Too risky for production"
        assert d.notes == "Revisit after v2"

    def test_to_dict(self) -> None:
        d = RepairDecision(title="Dict Test")
        data = d.to_dict()
        assert data["title"] == "Dict Test"
        assert data["decision_id"] == d.decision_id
        assert data["status"] == "accepted"
        assert "created_at" in data
        assert "proposal_id" in data
        assert "rationale" in data
        assert "notes" in data
        assert "reason" in data


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateDecision:
    def test_basic(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(title="Test")
        assert dec["title"] == "Test"
        assert dec["decision_id"]
        assert dec["status"] == "accepted"
        assert dec["source"] == "repair_proposal"
        assert dec["reason"] == "other"

    def test_all_fields(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(
            title="Full",
            proposal_id="prop-456",
            description="Full description",
            source="review_finding",
            status="rejected",
            reason="technical",
            rationale="Implementation too complex",
            notes="Consider simpler approach",
        )
        assert dec["source"] == "review_finding"
        assert dec["status"] == "rejected"
        assert dec["reason"] == "technical"
        assert dec["proposal_id"] == "prop-456"
        assert dec["rationale"] == "Implementation too complex"
        assert dec["notes"] == "Consider simpler approach"

    def test_invalid_source(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid source"):
            reg.create_decision(title="Bad", source="unknown")

    def test_invalid_status(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid status"):
            reg.create_decision(title="Bad", status="nonexistent")

    def test_invalid_reason(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid reason"):
            reg.create_decision(title="Bad", reason="nonexistent")


class TestGetDecision:
    def test_existing(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        created = reg.create_decision(title="Get Me")
        found = reg.get_decision(created["decision_id"])
        assert found is not None
        assert found["title"] == "Get Me"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        assert reg.get_decision("does-not-exist") is None


class TestListDecisions:
    def test_empty(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        assert reg.list_decisions() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        reg.create_decision(title="A", status="accepted")
        reg.create_decision(title="B", status="rejected")
        result = reg.list_decisions()
        assert len(result) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        reg.create_decision(title="Deferred", status="deferred")
        reg.create_decision(title="Accepted", status="accepted")
        reg.create_decision(title="Rejected", status="rejected")
        result = reg.list_decisions()
        statuses = [d["status"] for d in result]
        assert statuses == ["accepted", "rejected", "deferred"]

    def test_filter_status(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        reg.create_decision(title="A", status="accepted")
        reg.create_decision(title="B", status="rejected")
        accepted = reg.list_decisions(status="accepted")
        assert len(accepted) == 1
        assert accepted[0]["title"] == "A"

    def test_filter_reason(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        reg.create_decision(title="A", reason="technical")
        reg.create_decision(title="B", reason="policy")
        tech = reg.list_decisions(reason="technical")
        assert len(tech) == 1
        assert tech[0]["title"] == "A"

    def test_filter_source(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        reg.create_decision(title="A", source="escalation")
        reg.create_decision(title="B", source="validation")
        esc = reg.list_decisions(source="escalation")
        assert len(esc) == 1
        assert esc[0]["title"] == "A"


class TestExportDecision:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(
            title="Export Me",
            description="Some description",
            rationale="Risk too high",
            notes="Follow-up needed",
            source="validation",
            status="rejected",
            reason="risk",
            proposal_id="prop-789",
        )
        md = reg.export_decision(dec["decision_id"])
        assert "# Repair Decision: Export Me" in md
        assert "rejected" in md
        assert "risk" in md
        assert "validation" in md
        assert "Some description" in md
        assert "Risk too high" in md
        assert "Follow-up needed" in md
        assert "prop-789" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_decision("nope")


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(title="Evidence Test")
        evidence_dir = reg.write_evidence(dec["decision_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "repair_decision_request.json").exists()
        assert (ev_path / "repair_decision_result.json").exists()
        assert (ev_path / "repair_decision_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_content_valid_json(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(title="JSON Test")
        evidence_dir = reg.write_evidence(dec["decision_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "repair_decision_request.json",
            "repair_decision_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_accepted(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(title="Accepted", status="accepted")
        evidence_dir = reg.write_evidence(dec["decision_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is True

    def test_pass_fail_rejected(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(title="Rejected", status="rejected")
        evidence_dir = reg.write_evidence(dec["decision_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")

    def test_evidence_summary_md_content(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        dec = reg.create_decision(
            title="MD Test", rationale="Test rationale",
        )
        evidence_dir = reg.write_evidence(dec["decision_id"])
        md = (Path(evidence_dir) / "repair_decision_summary.md").read_text(
            encoding="utf-8",
        )
        assert "# Repair Decision: MD Test" in md
        assert "Test rationale" in md


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_decision("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_decision("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_decision("../etc/passwd")

    def test_forward_slash(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_decision("foo/bar")

    def test_backslash(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_decision("foo\\bar")

    def test_symlink_traversal_blocked(self, tmp_path: Path) -> None:
        reg = RepairDecisionRegistry(artifacts_root=str(tmp_path))
        decisions_dir = tmp_path / "repair_decisions"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = decisions_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            reg._safe_decision_path("evil-link")


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_repair_decision_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "repair-decision-create",
            "repair-decisions",
            "repair-decision-show",
            "repair-decision-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_repair_decision_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("repair-decision-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "repair_decision_request.json" in locations
        assert "repair_decision_result.json" in locations
        assert "repair_decision_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/repair_decision_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_repair_decision_registry.py"
