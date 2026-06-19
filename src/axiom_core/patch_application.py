"""Safe Patch Application Runner v1.

Controlled mechanism for applying approved patch proposals. Executes only
explicitly approved proposals, writes evidence artifacts, supports simulate
mode, and captures rollback metadata.

Chain: Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
      -> Patch Application (this module)

Non-goals: no git operations, no PR creation, no autonomous approval.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ApplicationStatus(str, Enum):
    """Status of a patch application run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SIMULATED = "simulated"


class StepStatus(str, Enum):
    """Status of a single application step."""

    PENDING = "pending"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    SIMULATED = "simulated"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PatchRollbackInfo:
    """Rollback metadata for a single file change."""

    def __init__(
        self,
        file_path: str = "",
        original_content: str | None = None,
        original_exists: bool = True,
        backup_path: str = "",
    ) -> None:
        self.file_path = file_path
        self.original_content = original_content
        self.original_exists = original_exists
        self.backup_path = backup_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "original_exists": self.original_exists,
            "backup_path": self.backup_path,
            "has_original_content": self.original_content is not None,
        }


class PatchApplicationEvidence:
    """Evidence artifact produced during application."""

    def __init__(
        self,
        artifact_type: str = "",
        artifact_path: str = "",
        description: str = "",
    ) -> None:
        self.artifact_type = artifact_type
        self.artifact_path = artifact_path
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "artifact_path": self.artifact_path,
            "description": self.description,
        }


class PatchApplicationStep:
    """A single step in the application process."""

    def __init__(
        self,
        step_id: str = "",
        file_path: str = "",
        edit_type: str = "",
        description: str = "",
        status: StepStatus = StepStatus.PENDING,
        rollback_info: PatchRollbackInfo | None = None,
        error: str = "",
    ) -> None:
        self.step_id = step_id or str(uuid4())
        self.file_path = file_path
        self.edit_type = edit_type
        self.description = description
        self.status = status
        self.rollback_info = rollback_info
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "file_path": self.file_path,
            "edit_type": self.edit_type,
            "description": self.description,
            "status": self.status.value,
            "rollback_info": (
                self.rollback_info.to_dict() if self.rollback_info else None
            ),
            "error": self.error,
        }


class PatchApplicationResult:
    """Result summary of a patch application run."""

    def __init__(
        self,
        success: bool = False,
        steps_applied: int = 0,
        steps_failed: int = 0,
        steps_skipped: int = 0,
        steps_simulated: int = 0,
        error: str = "",
    ) -> None:
        self.success = success
        self.steps_applied = steps_applied
        self.steps_failed = steps_failed
        self.steps_skipped = steps_skipped
        self.steps_simulated = steps_simulated
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "steps_applied": self.steps_applied,
            "steps_failed": self.steps_failed,
            "steps_skipped": self.steps_skipped,
            "steps_simulated": self.steps_simulated,
            "error": self.error,
        }


class PatchApplicationRun:
    """A complete patch application run with steps, evidence, and result."""

    def __init__(
        self,
        run_id: str = "",
        proposal_id: str = "",
        plan_id: str = "",
        simulate: bool = False,
        status: ApplicationStatus = ApplicationStatus.PENDING,
        steps: list[PatchApplicationStep] | None = None,
        evidence: list[PatchApplicationEvidence] | None = None,
        result: PatchApplicationResult | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid4())
        self.proposal_id = proposal_id
        self.plan_id = plan_id
        self.simulate = simulate
        self.status = status
        self.steps = steps or []
        self.evidence = evidence or []
        self.result = result
        self.started_at = started_at or datetime.now(timezone.utc).isoformat()
        self.completed_at = completed_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "proposal_id": self.proposal_id,
            "plan_id": self.plan_id,
            "simulate": self.simulate,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "evidence": [e.to_dict() for e in self.evidence],
            "result": self.result.to_dict() if self.result else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# PatchApplicationRunner — the controlled application engine
# ---------------------------------------------------------------------------

_ALLOWED_STATUSES = {"approved"}
_REFUSED_REASONS = {
    "proposed": "Proposal has not been reviewed yet",
    "rejected": "Proposal was rejected",
    "superseded": "Proposal was superseded by a newer version",
    "applied": "Proposal was already applied",
}


class PatchApplicationRunner:
    """Applies approved patch proposals with safety gates and evidence.

    Safety gates:
    - Must refuse rejected, unknown, deprecated, superseded, unapproved proposals
    - Simulate mode performs all steps without writing files
    - Evidence always written to artifacts/patch_runs/<run_id>/

    Non-goals: no git operations, no PR creation, no autonomous approval.
    """

    def __init__(
        self,
        db_path: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        self._artifacts_root = Path(
            os.environ.get("AXIOM_ARTIFACTS_ROOT", "artifacts"),
        )
        self._workspace_root = Path(
            workspace_root or os.environ.get("AXIOM_WORKSPACE_ROOT", "."),
        ).resolve()

    def apply(
        self,
        proposal_id: str,
        simulate: bool = False,
    ) -> PatchApplicationRun:
        """Apply an approved patch proposal.

        Raises ValueError if the proposal is not found or not approved.
        """
        proposal = self._get_proposal(proposal_id)
        run = PatchApplicationRun(
            proposal_id=proposal_id,
            plan_id=proposal.plan_id,
            simulate=simulate,
            status=ApplicationStatus.RUNNING,
        )

        run_dir = self._create_run_dir(run.run_id)
        self._write_request(run_dir, run, proposal)

        try:
            self._execute_steps(run, proposal, run_dir, simulate)
            has_failures = any(
                s.status == StepStatus.FAILED for s in run.steps
            )
            if has_failures:
                run.status = ApplicationStatus.FAILED
                run.result = self._build_result(
                    run, success=False,
                    error="One or more steps failed",
                )
            else:
                run.status = (
                    ApplicationStatus.SIMULATED
                    if simulate
                    else ApplicationStatus.COMPLETED
                )
                run.result = self._build_result(run, success=True)
                if not simulate:
                    self._mark_proposal_applied(proposal_id)
        except Exception as exc:
            run.status = ApplicationStatus.FAILED
            run.result = self._build_result(
                run, success=False, error=str(exc),
            )

        run.completed_at = datetime.now(timezone.utc).isoformat()
        self._write_result(run_dir, run)
        self._write_summary(run_dir, run)
        self._write_pass_fail(run_dir, run)

        return run

    # -- safety gate --------------------------------------------------------

    def _get_proposal(self, proposal_id: str) -> Any:
        from axiom_core.patch_proposal import PatchProposalRegistry

        registry = PatchProposalRegistry(db_path=self._db_path)
        proposal = registry.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Patch proposal not found: {proposal_id}")

        status = proposal.status.value
        if status in _REFUSED_REASONS:
            raise ValueError(
                f"Cannot apply proposal: {_REFUSED_REASONS[status]} "
                f"(status={status})",
            )
        if status not in _ALLOWED_STATUSES:
            raise ValueError(
                f"Cannot apply proposal: status '{status}' is not approved",
            )

        return proposal

    # -- step execution -----------------------------------------------------

    def _validate_path(self, file_path: str) -> Path:
        """Validate that a file path is within the workspace root."""
        resolved = Path(file_path).resolve()
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            raise ValueError(
                f"Path escapes workspace root: {file_path} "
                f"(workspace: {self._workspace_root})",
            )
        return resolved

    def _execute_steps(
        self,
        run: PatchApplicationRun,
        proposal: Any,
        run_dir: Path,
        simulate: bool,
    ) -> None:
        for i, fc in enumerate(proposal.file_changes):
            step = PatchApplicationStep(
                file_path=fc.file_path,
                edit_type=fc.edit_type.value if hasattr(fc.edit_type, "value") else str(fc.edit_type),
                description=fc.description,
            )

            try:
                self._validate_path(fc.file_path)
                rollback = self._capture_rollback(fc.file_path, run_dir)
                step.rollback_info = rollback

                if simulate:
                    step.status = StepStatus.SIMULATED
                else:
                    self._apply_file_change(fc, run_dir)
                    step.status = StepStatus.APPLIED
            except Exception as exc:
                step.status = StepStatus.FAILED
                step.error = str(exc)

            run.steps.append(step)

    def _capture_rollback(
        self,
        file_path: str,
        run_dir: Path,
    ) -> PatchRollbackInfo:
        rollback_dir = run_dir / "rollback_info"
        rollback_dir.mkdir(exist_ok=True)

        target = Path(file_path)
        original_content = None
        original_exists = target.exists()

        if original_exists:
            try:
                original_content = target.read_text(encoding="utf-8")
                safe_name = file_path.replace("/", "__").replace("\\", "__")
                backup_path = str(rollback_dir / safe_name)
                shutil.copy2(str(target), backup_path)
            except Exception:
                backup_path = ""
        else:
            backup_path = ""

        return PatchRollbackInfo(
            file_path=file_path,
            original_content=original_content,
            original_exists=original_exists,
            backup_path=backup_path,
        )

    def _apply_file_change(self, fc: Any, run_dir: Path) -> None:
        """Apply a single file change.

        Handles add, modify, delete, rename edit types. The actual content
        for add/modify comes from the proposal's after_hint field.
        """
        edit_type = fc.edit_type.value if hasattr(fc.edit_type, "value") else str(fc.edit_type)
        target = Path(fc.file_path)

        if edit_type == "delete":
            if target.exists():
                target.unlink()
            return

        if edit_type == "rename":
            if hasattr(fc, "after_hint") and fc.after_hint and target.exists():
                new_path = Path(fc.after_hint)
                new_path.parent.mkdir(parents=True, exist_ok=True)
                target.rename(new_path)
            return

        content = ""
        if hasattr(fc, "after_hint") and fc.after_hint:
            content = fc.after_hint
        elif hasattr(fc, "description") and fc.description:
            content = f"# Placeholder: {fc.description}\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        applied_dir = run_dir / "applied_changes"
        applied_dir.mkdir(exist_ok=True)
        safe_name = fc.file_path.replace("/", "__").replace("\\", "__")
        shutil.copy2(str(target), str(applied_dir / safe_name))

    # -- proposal status sync -----------------------------------------------

    def _mark_proposal_applied(self, proposal_id: str) -> None:
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus

        registry = PatchProposalRegistry(db_path=self._db_path)
        registry.update_status(proposal_id, PatchStatus.APPLIED)

    # -- evidence writing ---------------------------------------------------

    def _create_run_dir(self, run_id: str) -> Path:
        run_dir = self._artifacts_root / "patch_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _write_request(
        self,
        run_dir: Path,
        run: PatchApplicationRun,
        proposal: Any,
    ) -> None:
        request = {
            "run_id": run.run_id,
            "proposal_id": run.proposal_id,
            "plan_id": run.plan_id,
            "simulate": run.simulate,
            "started_at": run.started_at,
            "proposal_summary": proposal.summary,
            "proposal_title": proposal.title,
            "overall_risk_level": proposal.overall_risk_level.value,
            "file_count": len(proposal.file_changes),
        }
        path = run_dir / "patch_request.json"
        path.write_text(json.dumps(request, indent=2), encoding="utf-8")
        run.evidence.append(
            PatchApplicationEvidence(
                artifact_type="patch_request",
                artifact_path=str(path),
                description="Patch application request",
            ),
        )

    def _write_result(self, run_dir: Path, run: PatchApplicationRun) -> None:
        path = run_dir / "patch_result.json"
        path.write_text(
            json.dumps(run.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        run.evidence.append(
            PatchApplicationEvidence(
                artifact_type="patch_result",
                artifact_path=str(path),
                description="Patch application result",
            ),
        )

    def _write_summary(self, run_dir: Path, run: PatchApplicationRun) -> None:
        lines = [
            f"# Patch Application Run: {run.run_id}",
            "",
            f"**Proposal:** {run.proposal_id}",
            f"**Plan:** {run.plan_id}",
            f"**Mode:** {'simulate' if run.simulate else 'apply'}",
            f"**Status:** {run.status.value}",
            f"**Started:** {run.started_at}",
            f"**Completed:** {run.completed_at}",
            "",
            "## Steps",
            "",
        ]

        for step in run.steps:
            marker = {
                "applied": "APPLIED",
                "simulated": "SIMULATED",
                "failed": "FAILED",
                "skipped": "SKIPPED",
                "pending": "PENDING",
            }.get(step.status.value, step.status.value)
            lines.append(f"- [{marker}] {step.edit_type} {step.file_path}")
            if step.error:
                lines.append(f"  Error: {step.error}")

        if run.result:
            lines.extend([
                "",
                "## Result",
                "",
                f"- Success: {run.result.success}",
                f"- Applied: {run.result.steps_applied}",
                f"- Failed: {run.result.steps_failed}",
                f"- Skipped: {run.result.steps_skipped}",
                f"- Simulated: {run.result.steps_simulated}",
            ])
            if run.result.error:
                lines.append(f"- Error: {run.result.error}")

        lines.append("")
        path = run_dir / "patch_summary.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        run.evidence.append(
            PatchApplicationEvidence(
                artifact_type="patch_summary",
                artifact_path=str(path),
                description="Human-readable summary",
            ),
        )

    def _write_pass_fail(
        self,
        run_dir: Path,
        run: PatchApplicationRun,
    ) -> None:
        result = {
            "run_id": run.run_id,
            "passed": run.result.success if run.result else False,
            "status": run.status.value,
            "completed_at": run.completed_at,
        }
        path = run_dir / "pass_fail.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        run.evidence.append(
            PatchApplicationEvidence(
                artifact_type="pass_fail",
                artifact_path=str(path),
                description="Pass/fail verdict",
            ),
        )

    def _build_result(
        self,
        run: PatchApplicationRun,
        success: bool,
        error: str = "",
    ) -> PatchApplicationResult:
        applied = sum(
            1 for s in run.steps if s.status == StepStatus.APPLIED
        )
        failed = sum(
            1 for s in run.steps if s.status == StepStatus.FAILED
        )
        skipped = sum(
            1 for s in run.steps if s.status == StepStatus.SKIPPED
        )
        simulated = sum(
            1 for s in run.steps if s.status == StepStatus.SIMULATED
        )
        return PatchApplicationResult(
            success=success,
            steps_applied=applied,
            steps_failed=failed,
            steps_skipped=skipped,
            steps_simulated=simulated,
            error=error,
        )
