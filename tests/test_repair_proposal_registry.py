"""Tests for RepairProposalRegistry and Repair Proposal Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.repair_proposal_registry import (
    RepairProposal,
    RepairProposalRegistry,
    RepairProposalSource,
    RepairProposalStatus,
    RepairProposalType,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestRepairProposalType:
    def test_values(self) -> None:
        assert RepairProposalType.CODE_CHANGE.value == "code_change"
        assert RepairProposalType.TEST_CHANGE.value == "test_change"
        assert RepairProposalType.CONFIGURATION.value == "configuration"
        assert RepairProposalType.DOCUMENTATION.value == "documentation"
        assert RepairProposalType.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(RepairProposalType) == 5


class TestRepairProposalStatus:
    def test_values(self) -> None:
        assert RepairProposalStatus.PROPOSED.value == "proposed"
        assert RepairProposalStatus.ACCEPTED.value == "accepted"
        assert RepairProposalStatus.REJECTED.value == "rejected"

    def test_count(self) -> None:
        assert len(RepairProposalStatus) == 3


class TestRepairProposalSource:
    def test_values(self) -> None:
        assert RepairProposalSource.ESCALATION.value == "escalation"
        assert RepairProposalSource.ASSERTION.value == "assertion"
        assert RepairProposalSource.REVIEW_FINDING.value == "review_finding"
        assert RepairProposalSource.VALIDATION.value == "validation"

    def test_count(self) -> None:
        assert len(RepairProposalSource) == 4


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestRepairProposalDataclass:
    def test_defaults(self) -> None:
        p = RepairProposal(title="Test")
        assert p.title == "Test"
        assert p.proposal_id
        assert p.status == "proposed"
        assert p.proposal_type == "other"
        assert p.source == "escalation"
        assert p.escalation_id == ""
        assert p.rationale == ""
        assert p.recommendations == ""
        assert p.created_at

    def test_custom_fields(self) -> None:
        p = RepairProposal(
            title="Custom",
            escalation_id="esc-123",
            description="Fix the test",
            source="assertion",
            proposal_type="code_change",
            rationale="Test keeps failing",
            recommendations="Add null check",
        )
        assert p.escalation_id == "esc-123"
        assert p.source == "assertion"
        assert p.proposal_type == "code_change"
        assert p.rationale == "Test keeps failing"
        assert p.recommendations == "Add null check"

    def test_to_dict(self) -> None:
        p = RepairProposal(title="Dict Test")
        d = p.to_dict()
        assert d["title"] == "Dict Test"
        assert d["proposal_id"] == p.proposal_id
        assert d["status"] == "proposed"
        assert "created_at" in d
        assert "escalation_id" in d
        assert "rationale" in d
        assert "recommendations" in d


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateProposal:
    def test_basic(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(title="Test")
        assert prop["title"] == "Test"
        assert prop["proposal_id"]
        assert prop["status"] == "proposed"
        assert prop["source"] == "escalation"
        assert prop["proposal_type"] == "other"

    def test_all_fields(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(
            title="Full",
            escalation_id="esc-456",
            description="Full description",
            source="review_finding",
            proposal_type="code_change",
            rationale="Repeated failure in CI",
            recommendations="Add retry logic",
        )
        assert prop["source"] == "review_finding"
        assert prop["proposal_type"] == "code_change"
        assert prop["escalation_id"] == "esc-456"
        assert prop["rationale"] == "Repeated failure in CI"
        assert prop["recommendations"] == "Add retry logic"

    def test_invalid_source(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid source"):
            reg.create_proposal(title="Bad", source="unknown")

    def test_invalid_type(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid proposal_type"):
            reg.create_proposal(title="Bad", proposal_type="nonexistent")


class TestGetProposal:
    def test_existing(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        created = reg.create_proposal(title="Get Me")
        found = reg.get_proposal(created["proposal_id"])
        assert found is not None
        assert found["title"] == "Get Me"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        assert reg.get_proposal("does-not-exist") is None


class TestListProposals:
    def test_empty(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        assert reg.list_proposals() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        reg.create_proposal(title="A", proposal_type="code_change")
        reg.create_proposal(title="B", proposal_type="test_change")
        result = reg.list_proposals()
        assert len(result) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        reg.create_proposal(title="Other", proposal_type="other")
        reg.create_proposal(title="Code", proposal_type="code_change")
        reg.create_proposal(title="Test", proposal_type="test_change")
        result = reg.list_proposals()
        types = [p["proposal_type"] for p in result]
        assert types == ["code_change", "test_change", "other"]

    def test_filter_status(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        reg.create_proposal(title="A")
        reg.create_proposal(title="B")
        proposed = reg.list_proposals(status="proposed")
        assert len(proposed) == 2

    def test_filter_type(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        reg.create_proposal(title="A", proposal_type="code_change")
        reg.create_proposal(title="B", proposal_type="documentation")
        code = reg.list_proposals(proposal_type="code_change")
        assert len(code) == 1
        assert code[0]["title"] == "A"

    def test_filter_source(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        reg.create_proposal(title="A", source="escalation")
        reg.create_proposal(title="B", source="assertion")
        esc = reg.list_proposals(source="escalation")
        assert len(esc) == 1
        assert esc[0]["title"] == "A"


class TestExportProposal:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(
            title="Export Me",
            description="Some description",
            rationale="Evidence gap found",
            recommendations="Add validation step",
            source="validation",
            proposal_type="test_change",
            escalation_id="esc-789",
        )
        md = reg.export_proposal(prop["proposal_id"])
        assert "# Repair Proposal: Export Me" in md
        assert "test_change" in md
        assert "validation" in md
        assert "Some description" in md
        assert "Evidence gap found" in md
        assert "Add validation step" in md
        assert "esc-789" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_proposal("nope")


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(title="Evidence Test")
        evidence_dir = reg.write_evidence(prop["proposal_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "repair_proposal_request.json").exists()
        assert (ev_path / "repair_proposal_result.json").exists()
        assert (ev_path / "repair_proposal_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_content_valid_json(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(title="JSON Test")
        evidence_dir = reg.write_evidence(prop["proposal_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "repair_proposal_request.json",
            "repair_proposal_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_proposed(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(title="Proposed")
        evidence_dir = reg.write_evidence(prop["proposal_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")

    def test_evidence_summary_md_content(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        prop = reg.create_proposal(
            title="MD Test", rationale="Test rationale",
        )
        evidence_dir = reg.write_evidence(prop["proposal_id"])
        md = (Path(evidence_dir) / "repair_proposal_summary.md").read_text(
            encoding="utf-8",
        )
        assert "# Repair Proposal: MD Test" in md
        assert "Test rationale" in md


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_proposal("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_proposal("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_proposal("../etc/passwd")

    def test_forward_slash(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_proposal("foo/bar")

    def test_backslash(self, tmp_path: Path) -> None:
        reg = RepairProposalRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_proposal("foo\\bar")


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_repair_proposal_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "repair-proposal-create",
            "repair-proposals",
            "repair-proposal-show",
            "repair-proposal-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_repair_proposal_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("repair-proposal-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "repair_proposal_request.json" in locations
        assert "repair_proposal_result.json" in locations
        assert "repair_proposal_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/repair_proposal_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_repair_proposal_registry.py"
