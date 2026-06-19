"""Tests for axiom_core.patch_proposal — Patch Proposal Record v1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

import pytest

# ---------------------------------------------------------------------------
# Lightweight fakes for ImplementationPlan so tests stay isolated.
# ---------------------------------------------------------------------------


class _FakeChangeType(str, Enum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


class _FakeRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class _FakeFileChange:
    file_path: str = ""
    change_type: _FakeChangeType = _FakeChangeType.MODIFY
    description: str = ""
    related_symbols: list[str] | None = None

    def __post_init__(self):
        if self.related_symbols is None:
            self.related_symbols = []


@dataclass
class _FakeTestPlan:
    test_files: list[str] | None = None
    new_tests_needed: list[str] | None = None
    regression_commands: list[str] | None = None

    __test__ = False

    def __post_init__(self):
        self.test_files = self.test_files or []
        self.new_tests_needed = self.new_tests_needed or []
        self.regression_commands = self.regression_commands or []


@dataclass
class _FakeRiskNote:
    description: str = ""
    level: _FakeRiskLevel = _FakeRiskLevel.LOW
    mitigation: str = ""


@dataclass
class _FakePlan:
    plan_id: str = "plan-001"
    title: str = "Implementation Plan: Fix widget crash"
    summary: str = "Bug fix affecting 3 files"
    file_changes: list[_FakeFileChange] | None = None
    test_plan: _FakeTestPlan | None = None
    risks: list[_FakeRiskNote] | None = None
    evidence_requirements: list[str] | None = None

    def __post_init__(self):
        if self.file_changes is None:
            self.file_changes = [
                _FakeFileChange(
                    file_path="src/axiom_core/widget.py",
                    change_type=_FakeChangeType.MODIFY,
                    description="Fix crash in widget",
                    related_symbols=["axiom_core.widget.Widget"],
                ),
                _FakeFileChange(
                    file_path="src/axiom_core/dashboard.py",
                    change_type=_FakeChangeType.MODIFY,
                    description="Update dashboard",
                ),
                _FakeFileChange(
                    file_path="tests/test_widget.py",
                    change_type=_FakeChangeType.MODIFY,
                    description="Add regression test",
                ),
            ]
        if self.test_plan is None:
            self.test_plan = _FakeTestPlan(
                test_files=["tests/test_widget.py"],
                regression_commands=["poetry run pytest tests/ -x -q"],
            )
        if self.risks is None:
            self.risks = [
                _FakeRiskNote(
                    description="Widget API change",
                    level=_FakeRiskLevel.MEDIUM,
                    mitigation="Run full test suite",
                ),
            ]
        if self.evidence_requirements is None:
            self.evidence_requirements = ["Regression test proves fix"]


class _FakePlanner:
    def __init__(self, plans: dict[str, _FakePlan] | None = None) -> None:
        self._plans = plans or {}

    def get_plan(self, plan_id: str) -> _FakePlan | None:
        return self._plans.get(plan_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db_path)
    return db_path


@pytest.fixture()
def registry(tmp_db):
    from axiom_core.patch_proposal import PatchProposalRegistry

    return PatchProposalRegistry(db_path=tmp_db)


@pytest.fixture()
def fake_plan():
    return _FakePlan()


@pytest.fixture()
def planner(fake_plan):
    return _FakePlanner({"plan-001": fake_plan})


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_patch_status_values(self):
        from axiom_core.patch_proposal import PatchStatus

        assert PatchStatus.PROPOSED.value == "proposed"
        assert PatchStatus.APPROVED.value == "approved"
        assert PatchStatus.REJECTED.value == "rejected"
        assert PatchStatus.APPLIED.value == "applied"
        assert PatchStatus.SUPERSEDED.value == "superseded"

    def test_patch_risk_level_values(self):
        from axiom_core.patch_proposal import PatchRiskLevel

        assert PatchRiskLevel.LOW.value == "low"
        assert PatchRiskLevel.MEDIUM.value == "medium"
        assert PatchRiskLevel.HIGH.value == "high"
        assert PatchRiskLevel.CRITICAL.value == "critical"

    def test_file_edit_type_values(self):
        from axiom_core.patch_proposal import FileEditType

        assert FileEditType.ADD.value == "add"
        assert FileEditType.MODIFY.value == "modify"
        assert FileEditType.DELETE.value == "delete"
        assert FileEditType.RENAME.value == "rename"


# ---------------------------------------------------------------------------
# TestDataModels
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_proposed_file_change_roundtrip(self):
        from axiom_core.patch_proposal import FileEditType, ProposedFileChange

        fc = ProposedFileChange(
            file_path="src/foo.py",
            edit_type=FileEditType.MODIFY,
            description="Fix bug",
            before_hint="old code",
            after_hint="new code",
            related_symbols=["Foo.bar"],
        )
        d = fc.to_dict()
        assert d["file_path"] == "src/foo.py"
        assert d["edit_type"] == "modify"
        assert d["before_hint"] == "old code"
        fc2 = ProposedFileChange.from_dict(d)
        assert fc2.file_path == fc.file_path
        assert fc2.before_hint == fc.before_hint

    def test_proposed_test_command_roundtrip(self):
        from axiom_core.patch_proposal import ProposedTestCommand

        tc = ProposedTestCommand(
            command="poetry run pytest tests/ -x",
            description="Run all tests",
            expected_exit_code=0,
            is_validation=False,
        )
        d = tc.to_dict()
        assert d["command"] == "poetry run pytest tests/ -x"
        tc2 = ProposedTestCommand.from_dict(d)
        assert tc2.command == tc.command
        assert tc2.expected_exit_code == 0

    def test_patch_risk_roundtrip(self):
        from axiom_core.patch_proposal import PatchRisk, PatchRiskLevel

        r = PatchRisk(
            description="Breaks API",
            level=PatchRiskLevel.HIGH,
            mitigation="Add migration",
            affected_area="api",
        )
        d = r.to_dict()
        assert d["level"] == "high"
        assert d["affected_area"] == "api"
        r2 = PatchRisk.from_dict(d)
        assert r2.level == PatchRiskLevel.HIGH

    def test_patch_evidence_requirement_roundtrip(self):
        from axiom_core.patch_proposal import PatchEvidenceRequirement

        er = PatchEvidenceRequirement(
            description="Tests pass",
            evidence_type="test_output",
            required=True,
        )
        d = er.to_dict()
        assert d["required"] is True
        er2 = PatchEvidenceRequirement.from_dict(d)
        assert er2.description == er.description

    def test_patch_proposal_to_dict(self):
        from axiom_core.patch_proposal import (
            PatchProposal,
            ProposedFileChange,
            ProposedTestCommand,
        )

        proposal = PatchProposal(
            plan_id="plan-001",
            title="Patch: Fix widget",
            summary="A patch",
            file_changes=[ProposedFileChange(file_path="src/a.py")],
            test_commands=[ProposedTestCommand(command="pytest")],
        )
        d = proposal.to_dict()
        assert d["plan_id"] == "plan-001"
        assert d["status"] == "proposed"
        assert len(d["file_changes"]) == 1
        parsed = json.loads(json.dumps(d, default=str))
        assert parsed["title"] == "Patch: Fix widget"


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_create_from_plan(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        assert proposal.plan_id == "plan-001"
        assert proposal.status.value == "proposed"
        assert "Patch Proposal" in proposal.title
        assert len(proposal.file_changes) == 3
        assert len(proposal.test_commands) >= 1
        assert len(proposal.evidence_requirements) >= 2

    def test_create_from_unknown_plan_raises(self, registry):
        empty_planner = _FakePlanner({})
        with pytest.raises(ValueError, match="not found"):
            registry.create_from_plan("nonexistent", empty_planner)

    def test_file_changes_derived(self, registry, planner):
        from axiom_core.patch_proposal import FileEditType

        proposal = registry.create_from_plan("plan-001", planner)
        fc_paths = [fc.file_path for fc in proposal.file_changes]
        assert "src/axiom_core/widget.py" in fc_paths
        widget_fc = next(
            fc for fc in proposal.file_changes
            if fc.file_path == "src/axiom_core/widget.py"
        )
        assert widget_fc.edit_type == FileEditType.MODIFY
        assert len(widget_fc.related_symbols) >= 1

    def test_test_commands_derived(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        commands = [tc.command for tc in proposal.test_commands]
        assert any("test_widget" in c for c in commands)

    def test_validation_commands_derived(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        val_cmds = [vc.command for vc in proposal.validation_commands]
        assert any("ruff" in c for c in val_cmds)
        for vc in proposal.validation_commands:
            assert vc.is_validation is True

    def test_risks_inherited(self, registry, planner):
        from axiom_core.patch_proposal import PatchRiskLevel

        proposal = registry.create_from_plan("plan-001", planner)
        assert len(proposal.risks) >= 1
        levels = [r.level for r in proposal.risks]
        assert PatchRiskLevel.MEDIUM in levels

    def test_overall_risk_computed(self, registry, planner):
        from axiom_core.patch_proposal import PatchRiskLevel

        proposal = registry.create_from_plan("plan-001", planner)
        assert proposal.overall_risk_level == PatchRiskLevel.MEDIUM

    def test_evidence_requirements_include_plan_reqs(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        descs = [er.description for er in proposal.evidence_requirements]
        assert "Regression test proves fix" in descs
        assert "All targeted tests pass" in descs

    def test_rollback_notes_generated(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        assert "3 file(s)" in proposal.rollback_notes

    def test_json_output_valid(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        output = json.dumps(proposal.to_dict(), indent=2, default=str)
        parsed = json.loads(output)
        assert parsed["plan_id"] == "plan-001"


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_proposal_persists_and_retrieves(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        retrieved = registry.get_proposal(proposal.proposal_id)
        assert retrieved is not None
        assert retrieved.proposal_id == proposal.proposal_id
        assert retrieved.plan_id == "plan-001"

    def test_get_proposal_for_plan(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        retrieved = registry.get_proposal_for_plan("plan-001")
        assert retrieved is not None
        assert retrieved.proposal_id == proposal.proposal_id

    def test_get_proposal_unknown_returns_none(self, registry):
        assert registry.get_proposal("nonexistent-id") is None

    def test_get_proposal_for_unknown_plan_returns_none(self, registry):
        assert registry.get_proposal_for_plan("nonexistent-plan") is None

    def test_list_proposals(self, registry, planner):
        registry.create_from_plan("plan-001", planner)
        proposals = registry.list_proposals()
        assert len(proposals) >= 1

    def test_list_proposals_filter_by_status(self, registry, planner):
        from axiom_core.patch_proposal import PatchStatus

        registry.create_from_plan("plan-001", planner)
        proposed = registry.list_proposals(status=PatchStatus.PROPOSED)
        assert len(proposed) >= 1
        for p in proposed:
            assert p.status == PatchStatus.PROPOSED

    def test_regenerate_supersedes_old_proposal(self, registry, planner):
        from axiom_core.patch_proposal import PatchStatus

        proposal1 = registry.create_from_plan("plan-001", planner)
        old_updated_at = registry.get_proposal(proposal1.proposal_id).updated_at
        proposal2 = registry.create_from_plan("plan-001", planner)
        old = registry.get_proposal(proposal1.proposal_id)
        assert old is not None
        assert old.status == PatchStatus.SUPERSEDED
        assert old.updated_at >= old_updated_at
        new = registry.get_proposal(proposal2.proposal_id)
        assert new is not None
        assert new.status == PatchStatus.PROPOSED

    def test_get_proposal_for_plan_skips_superseded(self, registry, planner):
        from axiom_core.patch_proposal import PatchStatus

        registry.create_from_plan("plan-001", planner)
        proposal2 = registry.create_from_plan("plan-001", planner)
        result = registry.get_proposal_for_plan("plan-001")
        assert result is not None
        assert result.proposal_id == proposal2.proposal_id
        assert result.status != PatchStatus.SUPERSEDED

    def test_update_status(self, registry, planner):
        from axiom_core.patch_proposal import PatchStatus

        proposal = registry.create_from_plan("plan-001", planner)
        updated = registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)
        assert updated.status == PatchStatus.APPROVED
        retrieved = registry.get_proposal(proposal.proposal_id)
        assert retrieved is not None
        assert retrieved.status == PatchStatus.APPROVED

    def test_update_status_unknown_raises(self, registry):
        from axiom_core.patch_proposal import PatchStatus

        with pytest.raises(ValueError, match="not found"):
            registry.update_status("nonexistent-id", PatchStatus.APPROVED)

    def test_from_row_roundtrip(self, registry, planner):
        proposal = registry.create_from_plan("plan-001", planner)
        retrieved = registry.get_proposal(proposal.proposal_id)
        assert retrieved is not None
        d_orig = proposal.to_dict()
        d_retr = retrieved.to_dict()
        for key in ("plan_id", "title", "summary", "status", "file_changes",
                     "test_commands", "rollback_notes"):
            assert d_orig[key] == d_retr[key], f"Roundtrip mismatch: {key}"


# ---------------------------------------------------------------------------
# TestRiskComputation
# ---------------------------------------------------------------------------


class TestRiskComputation:
    def test_no_risks_returns_low(self, registry):
        from axiom_core.patch_proposal import PatchRiskLevel

        result = registry._compute_overall_risk([])
        assert result == PatchRiskLevel.LOW

    def test_critical_dominates(self, registry):
        from axiom_core.patch_proposal import PatchRisk, PatchRiskLevel

        risks = [
            PatchRisk(level=PatchRiskLevel.LOW),
            PatchRisk(level=PatchRiskLevel.CRITICAL),
            PatchRisk(level=PatchRiskLevel.MEDIUM),
        ]
        assert registry._compute_overall_risk(risks) == PatchRiskLevel.CRITICAL

    def test_high_without_critical(self, registry):
        from axiom_core.patch_proposal import PatchRisk, PatchRiskLevel

        risks = [
            PatchRisk(level=PatchRiskLevel.LOW),
            PatchRisk(level=PatchRiskLevel.HIGH),
        ]
        assert registry._compute_overall_risk(risks) == PatchRiskLevel.HIGH

    def test_large_patch_adds_high_risk(self, registry):
        from axiom_core.patch_proposal import PatchRiskLevel

        plan = _FakePlan(
            file_changes=[
                _FakeFileChange(file_path=f"src/file{i}.py")
                for i in range(12)
            ],
            risks=[],
        )
        planner = _FakePlanner({"plan-001": plan})
        proposal = registry.create_from_plan("plan-001", planner)
        levels = [r.level for r in proposal.risks]
        assert PatchRiskLevel.HIGH in levels
        assert proposal.overall_risk_level == PatchRiskLevel.HIGH
