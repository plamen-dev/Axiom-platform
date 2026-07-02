"""Tests for ConflictRegistry and Conflict Resolution Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.conflict_registry import (
    Conflict,
    ConflictRegistry,
    ConflictSeverity,
    ConflictSource,
    ConflictStatus,
    ConflictType,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestConflictType:
    def test_values(self) -> None:
        assert ConflictType.PROPOSAL_CONFLICT.value == "proposal_conflict"
        assert ConflictType.DECISION_CONFLICT.value == "decision_conflict"
        assert ConflictType.ASSERTION_CONFLICT.value == "assertion_conflict"
        assert ConflictType.VALIDATION_CONFLICT.value == "validation_conflict"
        assert ConflictType.REVIEW_FINDING_CONFLICT.value == "review_finding_conflict"
        assert ConflictType.ESCALATION_CONFLICT.value == "escalation_conflict"
        assert ConflictType.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(ConflictType) == 7


class TestConflictSeverity:
    def test_values(self) -> None:
        assert ConflictSeverity.NONE.value == "none"
        assert ConflictSeverity.INFO.value == "info"
        assert ConflictSeverity.WARNING.value == "warning"
        assert ConflictSeverity.BLOCKER.value == "blocker"
        assert ConflictSeverity.HUMAN_REQUIRED.value == "human_required"

    def test_count(self) -> None:
        assert len(ConflictSeverity) == 5


class TestConflictStatus:
    def test_values(self) -> None:
        assert ConflictStatus.OPEN.value == "open"
        assert ConflictStatus.ACKNOWLEDGED.value == "acknowledged"
        assert ConflictStatus.RESOLVED.value == "resolved"
        assert ConflictStatus.CLOSED.value == "closed"

    def test_count(self) -> None:
        assert len(ConflictStatus) == 4


class TestConflictSource:
    def test_values(self) -> None:
        assert ConflictSource.REPAIR_DECISION.value == "repair_decision"
        assert ConflictSource.REPAIR_PROPOSAL.value == "repair_proposal"
        assert ConflictSource.ESCALATION.value == "escalation"
        assert ConflictSource.ASSERTION.value == "assertion"
        assert ConflictSource.REVIEW_FINDING.value == "review_finding"
        assert ConflictSource.VALIDATION.value == "validation"
        assert ConflictSource.OTHER.value == "other"

    def test_count(self) -> None:
        assert len(ConflictSource) == 7


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestConflictDataclass:
    def test_defaults(self) -> None:
        c = Conflict(title="Test")
        assert c.title == "Test"
        assert c.conflict_id
        assert c.status == "open"
        assert c.severity == "info"
        assert c.conflict_type == "other"
        assert c.source == "other"
        assert c.left_ref == ""
        assert c.right_ref == ""
        assert c.rationale == ""
        assert c.recommendation == ""
        assert c.resolution_notes == ""
        assert c.created_at

    def test_custom_fields(self) -> None:
        c = Conflict(
            title="Custom",
            description="Two proposals conflict",
            conflict_type="proposal_conflict",
            severity="blocker",
            source="repair_proposal",
            left_ref="prop-1",
            right_ref="prop-2",
            rationale="Mutually exclusive approaches",
            recommendation="Pick one",
        )
        assert c.conflict_type == "proposal_conflict"
        assert c.severity == "blocker"
        assert c.left_ref == "prop-1"
        assert c.right_ref == "prop-2"

    def test_to_dict(self) -> None:
        c = Conflict(title="Dict Test")
        d = c.to_dict()
        assert d["title"] == "Dict Test"
        assert d["conflict_id"] == c.conflict_id
        assert d["status"] == "open"
        assert "created_at" in d
        assert "left_ref" in d
        assert "right_ref" in d
        assert "resolution_notes" in d


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCreateConflict:
    def test_basic(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(title="Test")
        assert conf["title"] == "Test"
        assert conf["conflict_id"]
        assert conf["status"] == "open"
        assert conf["severity"] == "info"
        assert conf["conflict_type"] == "other"
        assert conf["source"] == "other"

    def test_all_fields(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(
            title="Full",
            description="Full description",
            conflict_type="decision_conflict",
            severity="blocker",
            source="repair_decision",
            left_ref="dec-1",
            right_ref="dec-2",
            rationale="Contradictory decisions",
            recommendation="Escalate to human",
        )
        assert conf["conflict_type"] == "decision_conflict"
        assert conf["severity"] == "blocker"
        assert conf["source"] == "repair_decision"
        assert conf["left_ref"] == "dec-1"
        assert conf["right_ref"] == "dec-2"

    def test_invalid_type(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid conflict_type"):
            reg.create_conflict(title="Bad", conflict_type="nonexistent")

    def test_invalid_severity(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid severity"):
            reg.create_conflict(title="Bad", severity="nonexistent")

    def test_invalid_source(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="Invalid source"):
            reg.create_conflict(title="Bad", source="nonexistent")


class TestGetConflict:
    def test_existing(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        created = reg.create_conflict(title="Get Me")
        found = reg.get_conflict(created["conflict_id"])
        assert found is not None
        assert found["title"] == "Get Me"

    def test_nonexistent(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        assert reg.get_conflict("does-not-exist") is None


class TestListConflicts:
    def test_empty(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        assert reg.list_conflicts() == []

    def test_multiple(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="A", severity="info")
        reg.create_conflict(title="B", severity="blocker")
        result = reg.list_conflicts()
        assert len(result) == 2

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="Info", severity="info")
        reg.create_conflict(title="Blocker", severity="blocker")
        reg.create_conflict(title="Human", severity="human_required")
        result = reg.list_conflicts()
        sevs = [c["severity"] for c in result]
        assert sevs == ["human_required", "blocker", "info"]

    def test_filter_status(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="A")
        reg.create_conflict(title="B")
        opened = reg.list_conflicts(status="open")
        assert len(opened) == 2

    def test_filter_severity(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="A", severity="blocker")
        reg.create_conflict(title="B", severity="info")
        blockers = reg.list_conflicts(severity="blocker")
        assert len(blockers) == 1
        assert blockers[0]["title"] == "A"

    def test_filter_type(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="A", conflict_type="proposal_conflict")
        reg.create_conflict(title="B", conflict_type="decision_conflict")
        proposals = reg.list_conflicts(conflict_type="proposal_conflict")
        assert len(proposals) == 1
        assert proposals[0]["title"] == "A"

    def test_filter_source(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="A", source="escalation")
        reg.create_conflict(title="B", source="validation")
        esc = reg.list_conflicts(source="escalation")
        assert len(esc) == 1
        assert esc[0]["title"] == "A"


class TestExportConflict:
    def test_export_markdown(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(
            title="Export Me",
            description="Some description",
            rationale="Two proposals conflict",
            recommendation="Pick the simpler one",
            source="repair_proposal",
            severity="warning",
            conflict_type="proposal_conflict",
            left_ref="prop-1",
            right_ref="prop-2",
        )
        md = reg.export_conflict(conf["conflict_id"])
        assert "# Conflict: Export Me" in md
        assert "warning" in md
        assert "proposal_conflict" in md
        assert "Some description" in md
        assert "Two proposals conflict" in md
        assert "Pick the simpler one" in md
        assert "prop-1" in md
        assert "prop-2" in md

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.export_conflict("nope")


class TestWriteEvidence:
    def test_evidence_files(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(title="Evidence Test")
        evidence_dir = reg.write_evidence(conf["conflict_id"])
        ev_path = Path(evidence_dir)
        assert (ev_path / "conflict_request.json").exists()
        assert (ev_path / "conflict_result.json").exists()
        assert (ev_path / "conflict_summary.md").exists()
        assert (ev_path / "pass_fail.json").exists()

    def test_evidence_content_valid_json(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(title="JSON Test")
        evidence_dir = reg.write_evidence(conf["conflict_id"])
        ev_path = Path(evidence_dir)
        for fname in [
            "conflict_request.json",
            "conflict_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((ev_path / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_open(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(title="Open")
        evidence_dir = reg.write_evidence(conf["conflict_id"])
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is False

    def test_evidence_nonexistent(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.write_evidence("nope")

    def test_evidence_summary_md_content(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conf = reg.create_conflict(
            title="MD Test", rationale="Test rationale",
        )
        evidence_dir = reg.write_evidence(conf["conflict_id"])
        md = (Path(evidence_dir) / "conflict_summary.md").read_text(
            encoding="utf-8",
        )
        assert "# Conflict: MD Test" in md
        assert "Test rationale" in md


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIdValidation:
    def test_empty_id(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_conflict("")

    def test_whitespace_id(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            reg.get_conflict("   ")

    def test_path_traversal(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_conflict("../etc/passwd")

    def test_forward_slash(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_conflict("foo/bar")

    def test_backslash(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            reg.get_conflict("foo\\bar")

    def test_symlink_traversal_blocked(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        conflicts_dir = tmp_path / "conflicts"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = conflicts_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            reg._safe_conflict_path("evil-link")

    def test_symlink_skipped_in_list(self, tmp_path: Path) -> None:
        reg = ConflictRegistry(artifacts_root=str(tmp_path))
        reg.create_conflict(title="Real")
        outside = tmp_path / "outside"
        outside.mkdir()
        fake_json = outside / "conflict.json"
        fake_json.write_text('{"title":"Evil","status":"open","severity":"info"}')
        conflicts_dir = tmp_path / "conflicts"
        symlink = conflicts_dir / "evil-link"
        make_symlink_or_skip(symlink, outside)
        results = reg.list_conflicts()
        titles = [c["title"] for c in results]
        assert "Real" in titles
        assert "Evil" not in titles


# ---------------------------------------------------------------------------
# CommandRegistry integration tests
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_conflict_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        expected = [
            "conflict-create",
            "conflicts",
            "conflict-show",
            "conflict-export",
        ]
        for name in expected:
            cmd = get_command(name)
            assert cmd is not None, f"{name} not registered"
            assert cmd.classification.value == "read_only"
            assert cmd.safety_level.value == "safe"

    def test_conflict_create_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("conflict-create")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "conflict_request.json" in locations
        assert "conflict_result.json" in locations
        assert "conflict_summary.md" in locations
        assert "pass_fail.json" in locations


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/conflict_registry.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_conflict_registry.py"
