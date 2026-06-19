"""Tests for axiom_core.patch_application — Safe Patch Application Runner v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db_path)
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    return db_path


@pytest.fixture()
def approved_proposal_id(tmp_db, tmp_path):
    """Create an approved patch proposal and return its ID."""
    from axiom_core.patch_proposal import (
        FileEditType,
        PatchProposal,
        PatchProposalRegistry,
        PatchStatus,
        ProposedFileChange,
    )

    registry = PatchProposalRegistry(db_path=tmp_db)
    greeting_path = str(tmp_path / "workspace" / "greeting.py")
    utils_path = str(tmp_path / "workspace" / "utils.py")
    proposal = PatchProposal(
        plan_id="plan-001",
        title="Patch: Add greeting",
        summary="Add a greeting module",
        file_changes=[
            ProposedFileChange(
                file_path=greeting_path,
                edit_type=FileEditType.ADD,
                description="Add greeting module",
                after_hint="def greet():\n    return 'hello'\n",
            ),
            ProposedFileChange(
                file_path=utils_path,
                edit_type=FileEditType.MODIFY,
                description="Update utils",
                after_hint="# updated utils\n",
            ),
        ],
    )
    registry._persist(proposal)
    registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)
    return proposal.proposal_id


@pytest.fixture()
def rejected_proposal_id(tmp_db):
    """Create a rejected patch proposal."""
    from axiom_core.patch_proposal import (
        PatchProposal,
        PatchProposalRegistry,
        PatchStatus,
        ProposedFileChange,
    )

    registry = PatchProposalRegistry(db_path=tmp_db)
    proposal = PatchProposal(
        plan_id="plan-002",
        title="Rejected patch",
        summary="Should be refused",
        file_changes=[ProposedFileChange(file_path="src/bad.py")],
    )
    registry._persist(proposal)
    registry.update_status(proposal.proposal_id, PatchStatus.REJECTED)
    return proposal.proposal_id


@pytest.fixture()
def proposed_proposal_id(tmp_db):
    """Create a proposal that was never reviewed (still proposed)."""
    from axiom_core.patch_proposal import (
        PatchProposal,
        PatchProposalRegistry,
        ProposedFileChange,
    )

    registry = PatchProposalRegistry(db_path=tmp_db)
    proposal = PatchProposal(
        plan_id="plan-003",
        title="Unapproved patch",
        summary="Never reviewed",
        file_changes=[ProposedFileChange(file_path="src/pending.py")],
    )
    registry._persist(proposal)
    return proposal.proposal_id


@pytest.fixture()
def superseded_proposal_id(tmp_db):
    """Create a superseded patch proposal."""
    from axiom_core.patch_proposal import (
        PatchProposal,
        PatchProposalRegistry,
        PatchStatus,
        ProposedFileChange,
    )

    registry = PatchProposalRegistry(db_path=tmp_db)
    proposal = PatchProposal(
        plan_id="plan-004",
        title="Superseded patch",
        summary="Old version",
        file_changes=[ProposedFileChange(file_path="src/old.py")],
    )
    registry._persist(proposal)
    registry.update_status(proposal.proposal_id, PatchStatus.SUPERSEDED)
    return proposal.proposal_id


@pytest.fixture()
def runner(tmp_db, tmp_path):
    from axiom_core.patch_application import PatchApplicationRunner

    return PatchApplicationRunner(
        db_path=tmp_db, workspace_root=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_application_status_values(self):
        from axiom_core.patch_application import ApplicationStatus

        assert ApplicationStatus.PENDING.value == "pending"
        assert ApplicationStatus.RUNNING.value == "running"
        assert ApplicationStatus.COMPLETED.value == "completed"
        assert ApplicationStatus.FAILED.value == "failed"
        assert ApplicationStatus.SIMULATED.value == "simulated"

    def test_step_status_values(self):
        from axiom_core.patch_application import StepStatus

        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.APPLIED.value == "applied"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SIMULATED.value == "simulated"


# ---------------------------------------------------------------------------
# TestDataModels
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_rollback_info_to_dict(self):
        from axiom_core.patch_application import PatchRollbackInfo

        info = PatchRollbackInfo(
            file_path="src/foo.py",
            original_content="old",
            original_exists=True,
            backup_path="/tmp/backup",
        )
        d = info.to_dict()
        assert d["file_path"] == "src/foo.py"
        assert d["original_exists"] is True
        assert d["has_original_content"] is True

    def test_evidence_to_dict(self):
        from axiom_core.patch_application import PatchApplicationEvidence

        ev = PatchApplicationEvidence(
            artifact_type="patch_request",
            artifact_path="/tmp/req.json",
            description="Request",
        )
        d = ev.to_dict()
        assert d["artifact_type"] == "patch_request"

    def test_step_to_dict(self):
        from axiom_core.patch_application import PatchApplicationStep, StepStatus

        step = PatchApplicationStep(
            file_path="src/foo.py",
            edit_type="add",
            description="Add file",
            status=StepStatus.APPLIED,
        )
        d = step.to_dict()
        assert d["status"] == "applied"
        assert d["file_path"] == "src/foo.py"

    def test_result_to_dict(self):
        from axiom_core.patch_application import PatchApplicationResult

        result = PatchApplicationResult(
            success=True,
            steps_applied=3,
            steps_failed=0,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["steps_applied"] == 3

    def test_run_to_dict(self):
        from axiom_core.patch_application import (
            ApplicationStatus,
            PatchApplicationRun,
        )

        run = PatchApplicationRun(
            proposal_id="prop-001",
            plan_id="plan-001",
            simulate=False,
            status=ApplicationStatus.COMPLETED,
        )
        d = run.to_dict()
        assert d["proposal_id"] == "prop-001"
        assert d["status"] == "completed"
        parsed = json.loads(json.dumps(d, default=str))
        assert parsed["plan_id"] == "plan-001"


# ---------------------------------------------------------------------------
# TestSafetyGates
# ---------------------------------------------------------------------------


class TestSafetyGates:
    def test_unknown_proposal_refused(self, runner):
        with pytest.raises(ValueError, match="not found"):
            runner.apply("nonexistent-id")

    def test_rejected_proposal_refused(self, runner, rejected_proposal_id):
        with pytest.raises(ValueError, match="rejected"):
            runner.apply(rejected_proposal_id)

    def test_unapproved_proposal_refused(self, runner, proposed_proposal_id):
        with pytest.raises(ValueError, match="not been reviewed"):
            runner.apply(proposed_proposal_id)

    def test_superseded_proposal_refused(self, runner, superseded_proposal_id):
        with pytest.raises(ValueError, match="superseded"):
            runner.apply(superseded_proposal_id)


# ---------------------------------------------------------------------------
# TestSimulateMode
# ---------------------------------------------------------------------------


class TestSimulateMode:
    def test_simulate_succeeds(self, runner, approved_proposal_id):
        from axiom_core.patch_application import ApplicationStatus

        run = runner.apply(approved_proposal_id, simulate=True)
        assert run.status == ApplicationStatus.SIMULATED
        assert run.result is not None
        assert run.result.success is True
        assert run.result.steps_simulated == 2
        assert run.result.steps_applied == 0

    def test_simulate_does_not_write_files(
        self, runner, approved_proposal_id, tmp_path,
    ):
        runner.apply(approved_proposal_id, simulate=True)
        assert not (tmp_path / "workspace" / "greeting.py").exists()

    def test_simulate_does_not_change_proposal_status(
        self, runner, approved_proposal_id, tmp_db,
    ):
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus

        runner.apply(approved_proposal_id, simulate=True)
        reg = PatchProposalRegistry(db_path=tmp_db)
        proposal = reg.get_proposal(approved_proposal_id)
        assert proposal is not None
        assert proposal.status == PatchStatus.APPROVED


# ---------------------------------------------------------------------------
# TestApplyMode
# ---------------------------------------------------------------------------


class TestApplyMode:
    def test_apply_succeeds(self, runner, approved_proposal_id, tmp_path):
        from axiom_core.patch_application import ApplicationStatus

        run = runner.apply(approved_proposal_id, simulate=False)
        assert run.status == ApplicationStatus.COMPLETED
        assert run.result is not None
        assert run.result.success is True
        assert run.result.steps_applied == 2

    def test_apply_marks_proposal_applied(
        self, runner, approved_proposal_id, tmp_db,
    ):
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus

        runner.apply(approved_proposal_id, simulate=False)
        reg = PatchProposalRegistry(db_path=tmp_db)
        proposal = reg.get_proposal(approved_proposal_id)
        assert proposal is not None
        assert proposal.status == PatchStatus.APPLIED

    def test_already_applied_refused(
        self, runner, approved_proposal_id,
    ):
        runner.apply(approved_proposal_id, simulate=False)
        with pytest.raises(ValueError, match="already applied"):
            runner.apply(approved_proposal_id, simulate=False)


# ---------------------------------------------------------------------------
# TestEvidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_written_on_simulate(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        assert len(run.evidence) >= 4
        types = [e.artifact_type for e in run.evidence]
        assert "patch_request" in types
        assert "patch_result" in types
        assert "patch_summary" in types
        assert "pass_fail" in types

    def test_evidence_written_on_apply(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=False)
        types = [e.artifact_type for e in run.evidence]
        assert "patch_request" in types
        assert "patch_result" in types
        assert "patch_summary" in types
        assert "pass_fail" in types

    def test_evidence_files_exist(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        for ev in run.evidence:
            assert Path(ev.artifact_path).exists(), (
                f"Missing: {ev.artifact_path}"
            )

    def test_patch_request_json_valid(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        req_ev = next(
            e for e in run.evidence if e.artifact_type == "patch_request"
        )
        data = json.loads(Path(req_ev.artifact_path).read_text())
        assert data["proposal_id"] == approved_proposal_id
        assert data["simulate"] is True

    def test_pass_fail_json_valid(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        pf_ev = next(
            e for e in run.evidence if e.artifact_type == "pass_fail"
        )
        data = json.loads(Path(pf_ev.artifact_path).read_text())
        assert data["passed"] is True
        assert data["status"] == "simulated"

    def test_summary_markdown_exists(
        self, runner, approved_proposal_id, tmp_path,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        summary_ev = next(
            e for e in run.evidence if e.artifact_type == "patch_summary"
        )
        content = Path(summary_ev.artifact_path).read_text()
        assert "# Patch Application Run" in content
        assert "SIMULATED" in content


# ---------------------------------------------------------------------------
# TestRollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_info_captured_for_new_files(
        self, runner, approved_proposal_id,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        for step in run.steps:
            assert step.rollback_info is not None

    def test_rollback_info_marks_nonexistent(self, tmp_db, tmp_path):
        from axiom_core.patch_application import PatchApplicationRunner
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-nonexist",
            title="New file only",
            summary="Add a file that does not exist",
            file_changes=[
                ProposedFileChange(
                    file_path=str(tmp_path / "does_not_exist.py"),
                    edit_type=FileEditType.ADD,
                    description="Brand new file",
                    after_hint="# new\n",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=True)
        step = run.steps[0]
        assert step.rollback_info is not None
        assert step.rollback_info.original_exists is False


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_steps_follow_proposal_order(
        self, runner, approved_proposal_id,
    ):
        run = runner.apply(approved_proposal_id, simulate=True)
        assert len(run.steps) == 2
        assert run.steps[0].file_path.endswith("greeting.py")
        assert run.steps[1].file_path.endswith("utils.py")

    def test_json_output_valid(self, runner, approved_proposal_id):
        run = runner.apply(approved_proposal_id, simulate=True)
        output = json.dumps(run.to_dict(), indent=2, default=str)
        parsed = json.loads(output)
        assert parsed["status"] == "simulated"


# ---------------------------------------------------------------------------
# TestPartialFailure
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_partial_failure_reports_success_false(self, tmp_db, tmp_path):
        from axiom_core.patch_application import (
            ApplicationStatus,
            PatchApplicationRunner,
        )
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        good_path = str(tmp_path / "workspace" / "good.py")
        bad_path = "/dev/null/../../../etc/shadow"

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-fail",
            title="Partial failure",
            summary="One step should fail",
            file_changes=[
                ProposedFileChange(
                    file_path=good_path,
                    edit_type=FileEditType.ADD,
                    description="Good file",
                    after_hint="# good\n",
                ),
                ProposedFileChange(
                    file_path=bad_path,
                    edit_type=FileEditType.MODIFY,
                    description="Bad path outside workspace",
                    after_hint="# bad\n",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=True)

        assert run.status == ApplicationStatus.FAILED
        assert run.result is not None
        assert run.result.success is False
        assert run.result.steps_failed >= 1

    def test_partial_failure_does_not_mark_applied(self, tmp_db, tmp_path):
        from axiom_core.patch_application import PatchApplicationRunner
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-noapply",
            title="Should not mark applied",
            summary="Step fails",
            file_changes=[
                ProposedFileChange(
                    file_path="/etc/passwd",
                    edit_type=FileEditType.MODIFY,
                    description="Escape",
                    after_hint="bad\n",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=False)

        assert run.result is not None
        assert run.result.success is False

        refreshed = registry.get_proposal(proposal.proposal_id)
        assert refreshed is not None
        assert refreshed.status == PatchStatus.APPROVED


# ---------------------------------------------------------------------------
# TestWorkspaceSecurity
# ---------------------------------------------------------------------------


class TestWorkspaceSecurity:
    def test_absolute_path_outside_workspace_rejected(
        self, tmp_db, tmp_path,
    ):
        from axiom_core.patch_application import PatchApplicationRunner, StepStatus
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-escape",
            title="Escape attempt",
            summary="Tries /etc/passwd",
            file_changes=[
                ProposedFileChange(
                    file_path="/etc/passwd",
                    edit_type=FileEditType.MODIFY,
                    description="Escape",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=True)

        assert run.steps[0].status == StepStatus.FAILED
        assert "escapes workspace" in run.steps[0].error.lower()

    def test_traversal_path_rejected(self, tmp_db, tmp_path):
        from axiom_core.patch_application import PatchApplicationRunner, StepStatus
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-traversal",
            title="Traversal attempt",
            summary="Uses ../../../etc/passwd",
            file_changes=[
                ProposedFileChange(
                    file_path=str(tmp_path / "workspace" / ".." / ".." / "etc" / "passwd"),
                    edit_type=FileEditType.MODIFY,
                    description="Traversal",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=True)

        assert run.steps[0].status == StepStatus.FAILED
        assert "escapes workspace" in run.steps[0].error.lower()

    def test_simulate_does_not_read_outside_workspace(
        self, tmp_db, tmp_path,
    ):
        from axiom_core.patch_application import PatchApplicationRunner
        from axiom_core.patch_proposal import (
            FileEditType,
            PatchProposal,
            PatchProposalRegistry,
            PatchStatus,
            ProposedFileChange,
        )

        registry = PatchProposalRegistry(db_path=tmp_db)
        proposal = PatchProposal(
            plan_id="plan-exfil",
            title="Exfiltration attempt",
            summary="Read /etc/passwd via rollback",
            file_changes=[
                ProposedFileChange(
                    file_path="/etc/passwd",
                    edit_type=FileEditType.ADD,
                    description="Exfiltrate",
                ),
            ],
        )
        registry._persist(proposal)
        registry.update_status(proposal.proposal_id, PatchStatus.APPROVED)

        runner = PatchApplicationRunner(
            db_path=tmp_db, workspace_root=str(tmp_path),
        )
        run = runner.apply(proposal.proposal_id, simulate=True)

        assert run.steps[0].status.value == "failed"
        assert run.steps[0].rollback_info is None
