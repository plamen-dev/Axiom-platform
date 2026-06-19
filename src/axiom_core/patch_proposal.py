"""Patch Proposal Record v1.

Durable record format for proposed code changes before they are applied.
Describes patches, evidence, tests, and risks without editing files.
Read-only: never modifies source files, never runs git operations.
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PatchStatus(str, Enum):
    """Lifecycle status of a patch proposal."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


class PatchRiskLevel(str, Enum):
    """Risk severity for a patch."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FileEditType(str, Enum):
    """Kind of intended file edit."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


# ---------------------------------------------------------------------------
# ORM Row
# ---------------------------------------------------------------------------


class PatchProposalRow(Base):
    """SQLAlchemy row for a patch proposal."""

    __tablename__ = "patch_proposals"

    proposal_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="proposed",
    )
    file_changes_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
    )
    test_commands_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
    )
    validation_commands_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
    )
    risks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_requirements_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
    )
    rollback_notes: Mapped[str] = mapped_column(Text, nullable=True)
    overall_risk_level: Mapped[str] = mapped_column(
        String(30), nullable=False, default="low",
    )
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ProposedFileChange:
    """A proposed edit to a single file."""

    def __init__(
        self,
        file_path: str = "",
        edit_type: FileEditType = FileEditType.MODIFY,
        description: str = "",
        before_hint: str = "",
        after_hint: str = "",
        related_symbols: list[str] | None = None,
    ) -> None:
        self.file_path = file_path
        self.edit_type = edit_type
        self.description = description
        self.before_hint = before_hint
        self.after_hint = after_hint
        self.related_symbols = related_symbols or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "edit_type": self.edit_type.value,
            "description": self.description,
            "before_hint": self.before_hint,
            "after_hint": self.after_hint,
            "related_symbols": self.related_symbols,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposedFileChange:
        return cls(
            file_path=data.get("file_path", ""),
            edit_type=FileEditType(data.get("edit_type", "modify")),
            description=data.get("description", ""),
            before_hint=data.get("before_hint", ""),
            after_hint=data.get("after_hint", ""),
            related_symbols=data.get("related_symbols", []),
        )


class ProposedTestCommand:
    """A test or validation command to run after applying the patch."""

    __test__ = False

    def __init__(
        self,
        command: str = "",
        description: str = "",
        expected_exit_code: int = 0,
        is_validation: bool = False,
    ) -> None:
        self.command = command
        self.description = description
        self.expected_exit_code = expected_exit_code
        self.is_validation = is_validation

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "expected_exit_code": self.expected_exit_code,
            "is_validation": self.is_validation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposedTestCommand:
        return cls(
            command=data.get("command", ""),
            description=data.get("description", ""),
            expected_exit_code=data.get("expected_exit_code", 0),
            is_validation=data.get("is_validation", False),
        )


class PatchRisk:
    """A risk associated with a patch proposal."""

    def __init__(
        self,
        description: str = "",
        level: PatchRiskLevel = PatchRiskLevel.LOW,
        mitigation: str = "",
        affected_area: str = "",
    ) -> None:
        self.description = description
        self.level = level
        self.mitigation = mitigation
        self.affected_area = affected_area

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "level": self.level.value,
            "mitigation": self.mitigation,
            "affected_area": self.affected_area,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchRisk:
        return cls(
            description=data.get("description", ""),
            level=PatchRiskLevel(data.get("level", "low")),
            mitigation=data.get("mitigation", ""),
            affected_area=data.get("affected_area", ""),
        )


class PatchEvidenceRequirement:
    """Evidence that must be produced when applying this patch."""

    def __init__(
        self,
        description: str = "",
        evidence_type: str = "test_output",
        required: bool = True,
    ) -> None:
        self.description = description
        self.evidence_type = evidence_type
        self.required = required

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "evidence_type": self.evidence_type,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchEvidenceRequirement:
        return cls(
            description=data.get("description", ""),
            evidence_type=data.get("evidence_type", "test_output"),
            required=data.get("required", True),
        )


class PatchProposal:
    """A structured proposal for code changes derived from an implementation plan."""

    def __init__(
        self,
        proposal_id: str = "",
        plan_id: str = "",
        title: str = "",
        summary: str = "",
        status: PatchStatus = PatchStatus.PROPOSED,
        file_changes: list[ProposedFileChange] | None = None,
        test_commands: list[ProposedTestCommand] | None = None,
        validation_commands: list[ProposedTestCommand] | None = None,
        risks: list[PatchRisk] | None = None,
        evidence_requirements: list[PatchEvidenceRequirement] | None = None,
        rollback_notes: str = "",
        overall_risk_level: PatchRiskLevel = PatchRiskLevel.LOW,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.proposal_id = proposal_id or str(uuid4())
        self.plan_id = plan_id
        self.title = title
        self.summary = summary
        self.status = status
        self.file_changes = file_changes or []
        self.test_commands = test_commands or []
        self.validation_commands = validation_commands or []
        self.risks = risks or []
        self.evidence_requirements = evidence_requirements or []
        self.rollback_notes = rollback_notes
        self.overall_risk_level = overall_risk_level
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "plan_id": self.plan_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status.value,
            "file_changes": [fc.to_dict() for fc in self.file_changes],
            "test_commands": [tc.to_dict() for tc in self.test_commands],
            "validation_commands": [vc.to_dict() for vc in self.validation_commands],
            "risks": [r.to_dict() for r in self.risks],
            "evidence_requirements": [
                er.to_dict() for er in self.evidence_requirements
            ],
            "rollback_notes": self.rollback_notes,
            "overall_risk_level": self.overall_risk_level.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: PatchProposalRow) -> PatchProposal:
        fc_data = json.loads(row.file_changes_json) if row.file_changes_json else []
        tc_data = json.loads(row.test_commands_json) if row.test_commands_json else []
        vc_data = (
            json.loads(row.validation_commands_json)
            if row.validation_commands_json
            else []
        )
        risks_data = json.loads(row.risks_json) if row.risks_json else []
        ev_data = (
            json.loads(row.evidence_requirements_json)
            if row.evidence_requirements_json
            else []
        )

        return cls(
            proposal_id=row.proposal_id,
            plan_id=row.plan_id,
            title=row.title,
            summary=row.summary or "",
            status=PatchStatus(row.status),
            file_changes=[ProposedFileChange.from_dict(fc) for fc in fc_data],
            test_commands=[ProposedTestCommand.from_dict(tc) for tc in tc_data],
            validation_commands=[ProposedTestCommand.from_dict(vc) for vc in vc_data],
            risks=[PatchRisk.from_dict(r) for r in risks_data],
            evidence_requirements=[
                PatchEvidenceRequirement.from_dict(er) for er in ev_data
            ],
            rollback_notes=row.rollback_notes or "",
            overall_risk_level=PatchRiskLevel(row.overall_risk_level),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# PatchProposalRegistry — the registry engine
# ---------------------------------------------------------------------------


class PatchProposalRegistry:
    """Creates and manages patch proposals from implementation plans.

    Read-only with respect to source files: never edits code, never runs
    git operations, never applies patches.
    """

    def __init__(self, db_path: str | None = None) -> None:
        effective_path = db_path or os.environ.get("AXIOM_DB_PATH")
        engine = create_db_engine(effective_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    def create_from_plan(
        self,
        plan_id: str,
        planner: Any,
    ) -> PatchProposal:
        """Create a patch proposal from an implementation plan.

        Raises ValueError if the plan is not found.
        """
        plan = planner.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Implementation plan not found: {plan_id}")

        file_changes = self._derive_file_changes(plan)
        test_commands = self._derive_test_commands(plan)
        validation_commands = self._derive_validation_commands(plan)
        risks = self._derive_risks(plan)
        evidence_reqs = self._derive_evidence_requirements(plan)
        rollback = self._derive_rollback_notes(plan)
        overall_risk = self._compute_overall_risk(risks)

        proposal = PatchProposal(
            plan_id=plan_id,
            title=f"Patch Proposal: {plan.title.removeprefix('Implementation Plan: ')}",
            summary=self._build_summary(plan, file_changes),
            file_changes=file_changes,
            test_commands=test_commands,
            validation_commands=validation_commands,
            risks=risks,
            evidence_requirements=evidence_reqs,
            rollback_notes=rollback,
            overall_risk_level=overall_risk,
        )

        self._persist(proposal)
        return proposal

    def get_proposal(self, proposal_id: str) -> PatchProposal | None:
        with get_session(self._session_factory) as session:
            row = session.get(PatchProposalRow, proposal_id)
            if row is None:
                return None
            return PatchProposal.from_row(row)

    def get_proposal_for_plan(self, plan_id: str) -> PatchProposal | None:
        with get_session(self._session_factory) as session:
            row = (
                session.query(PatchProposalRow)
                .filter(
                    PatchProposalRow.plan_id == plan_id,
                    PatchProposalRow.status != PatchStatus.SUPERSEDED.value,
                )
                .order_by(PatchProposalRow.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return PatchProposal.from_row(row)

    def list_proposals(
        self,
        status: PatchStatus | None = None,
    ) -> list[PatchProposal]:
        with get_session(self._session_factory) as session:
            query = session.query(PatchProposalRow)
            if status is not None:
                query = query.filter(PatchProposalRow.status == status.value)
            query = query.order_by(PatchProposalRow.created_at.desc())
            return [PatchProposal.from_row(row) for row in query.all()]

    def update_status(
        self,
        proposal_id: str,
        new_status: PatchStatus,
    ) -> PatchProposal:
        """Update the status of a proposal.

        Raises ValueError if the proposal is not found.
        """
        with get_session(self._session_factory) as session:
            row = session.get(PatchProposalRow, proposal_id)
            if row is None:
                raise ValueError(f"Patch proposal not found: {proposal_id}")
            row.status = new_status.value
            row.updated_at = datetime.now(timezone.utc).isoformat()
            return PatchProposal.from_row(row)

    # -- persistence --------------------------------------------------------

    def _persist(self, proposal: PatchProposal) -> None:
        with get_session(self._session_factory) as session:
            previous = (
                session.query(PatchProposalRow)
                .filter(
                    PatchProposalRow.plan_id == proposal.plan_id,
                    PatchProposalRow.proposal_id != proposal.proposal_id,
                    PatchProposalRow.status != PatchStatus.SUPERSEDED.value,
                )
                .all()
            )
            for prev in previous:
                prev.status = PatchStatus.SUPERSEDED.value
                prev.updated_at = datetime.now(timezone.utc).isoformat()
            row = PatchProposalRow(
                proposal_id=proposal.proposal_id,
                plan_id=proposal.plan_id,
                title=proposal.title,
                summary=proposal.summary,
                status=proposal.status.value,
                file_changes_json=json.dumps(
                    [fc.to_dict() for fc in proposal.file_changes],
                ),
                test_commands_json=json.dumps(
                    [tc.to_dict() for tc in proposal.test_commands],
                ),
                validation_commands_json=json.dumps(
                    [vc.to_dict() for vc in proposal.validation_commands],
                ),
                risks_json=json.dumps([r.to_dict() for r in proposal.risks]),
                evidence_requirements_json=json.dumps(
                    [er.to_dict() for er in proposal.evidence_requirements],
                ),
                rollback_notes=proposal.rollback_notes,
                overall_risk_level=proposal.overall_risk_level.value,
                created_at=proposal.created_at,
                updated_at=proposal.updated_at,
            )
            session.add(row)

    # -- derivation helpers -------------------------------------------------

    def _derive_file_changes(self, plan: Any) -> list[ProposedFileChange]:
        changes: list[ProposedFileChange] = []
        for fc in plan.file_changes:
            edit_type = FileEditType(fc.change_type.value)
            changes.append(
                ProposedFileChange(
                    file_path=fc.file_path,
                    edit_type=edit_type,
                    description=fc.description,
                    related_symbols=list(fc.related_symbols),
                )
            )
        return changes

    def _derive_test_commands(self, plan: Any) -> list[ProposedTestCommand]:
        commands: list[ProposedTestCommand] = []
        if plan.test_plan and plan.test_plan.test_files:
            for tf in plan.test_plan.test_files:
                safe_path = shlex.quote(tf)
                commands.append(
                    ProposedTestCommand(
                        command=f"poetry run pytest {safe_path} -x -q",
                        description=f"Run tests in {tf}",
                    )
                )
        if plan.test_plan and plan.test_plan.regression_commands:
            for rc in plan.test_plan.regression_commands:
                commands.append(
                    ProposedTestCommand(
                        command=rc,
                        description="Regression command from plan",
                    )
                )
        return commands

    def _derive_validation_commands(self, plan: Any) -> list[ProposedTestCommand]:
        commands: list[ProposedTestCommand] = []
        affected_files = [fc.file_path for fc in plan.file_changes]
        py_files = [f for f in affected_files if f.endswith(".py")]
        if py_files:
            file_list = " ".join(shlex.quote(f) for f in py_files)
            commands.append(
                ProposedTestCommand(
                    command=f"poetry run ruff check {file_list}",
                    description="Lint check on affected Python files",
                    is_validation=True,
                )
            )
        return commands

    def _derive_risks(self, plan: Any) -> list[PatchRisk]:
        risks: list[PatchRisk] = []
        for r in plan.risks:
            risks.append(
                PatchRisk(
                    description=r.description,
                    level=PatchRiskLevel(r.level.value),
                    mitigation=r.mitigation,
                )
            )
        file_count = len(plan.file_changes)
        if file_count > 10:
            risks.append(
                PatchRisk(
                    description=f"Large patch: {file_count} files affected",
                    level=PatchRiskLevel.HIGH,
                    mitigation="Consider splitting into smaller patches",
                    affected_area="scope",
                )
            )
        return risks

    def _derive_evidence_requirements(
        self,
        plan: Any,
    ) -> list[PatchEvidenceRequirement]:
        reqs: list[PatchEvidenceRequirement] = []
        reqs.append(
            PatchEvidenceRequirement(
                description="All targeted tests pass",
                evidence_type="test_output",
                required=True,
            )
        )
        reqs.append(
            PatchEvidenceRequirement(
                description="ruff check clean on affected files",
                evidence_type="lint_output",
                required=True,
            )
        )
        for er in plan.evidence_requirements:
            reqs.append(
                PatchEvidenceRequirement(
                    description=er,
                    evidence_type="plan_requirement",
                    required=True,
                )
            )
        return reqs

    def _derive_rollback_notes(self, plan: Any) -> str:
        file_count = len(plan.file_changes)
        if file_count == 0:
            return "No files affected — no rollback needed."
        return (
            f"Revert the commit touching {file_count} file(s). "
            "Run targeted tests to confirm rollback is clean."
        )

    def _compute_overall_risk(self, risks: list[PatchRisk]) -> PatchRiskLevel:
        if not risks:
            return PatchRiskLevel.LOW
        levels = [r.level for r in risks]
        if PatchRiskLevel.CRITICAL in levels:
            return PatchRiskLevel.CRITICAL
        if PatchRiskLevel.HIGH in levels:
            return PatchRiskLevel.HIGH
        if PatchRiskLevel.MEDIUM in levels:
            return PatchRiskLevel.MEDIUM
        return PatchRiskLevel.LOW

    def _build_summary(
        self,
        plan: Any,
        file_changes: list[ProposedFileChange],
    ) -> str:
        title = plan.title.removeprefix("Implementation Plan: ")
        return (
            f"Patch proposal for '{title}'. "
            f"Affects {len(file_changes)} file(s)."
        )
