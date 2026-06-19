"""PR Draft Generator v1.

Converts code validation evidence and work item context into merge-ready
release artifacts (commit title, extended description, validation section,
strategic significance).

Chain: Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
      -> Patch Application -> Code Validation -> PR Draft (this module)

Non-goals: no GitHub API, no PR creation, no merge behavior, no review
finding ingestion, no automatic fixes, no learning, no network dependency.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PRDraftStatus(str, Enum):
    """Lifecycle status of a PR draft."""

    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"
    REFUSED = "refused"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PRValidationSection:
    """Structured validation evidence for the PR description."""

    def __init__(
        self,
        validation_run_id: str = "",
        status: str = "",
        overall_passed: bool = False,
        stages_passed: int = 0,
        stages_failed: int = 0,
        stages_skipped: int = 0,
        evidence_paths: list[str] | None = None,
    ) -> None:
        self.validation_run_id = validation_run_id
        self.status = status
        self.overall_passed = overall_passed
        self.stages_passed = stages_passed
        self.stages_failed = stages_failed
        self.stages_skipped = stages_skipped
        self.evidence_paths = evidence_paths or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_run_id": self.validation_run_id,
            "status": self.status,
            "overall_passed": self.overall_passed,
            "stages_passed": self.stages_passed,
            "stages_failed": self.stages_failed,
            "stages_skipped": self.stages_skipped,
            "evidence_paths": self.evidence_paths,
        }


class PRStrategicSection:
    """Strategic context for the PR description."""

    def __init__(
        self,
        significance: str = "",
        next_recommended_step: str = "",
        non_goals: list[str] | None = None,
        what_did_not_change: list[str] | None = None,
    ) -> None:
        self.significance = significance
        self.next_recommended_step = next_recommended_step
        self.non_goals = non_goals or []
        self.what_did_not_change = what_did_not_change or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "significance": self.significance,
            "next_recommended_step": self.next_recommended_step,
            "non_goals": self.non_goals,
            "what_did_not_change": self.what_did_not_change,
        }


class PRSummary:
    """Summary of the PR draft generation result."""

    def __init__(
        self,
        commit_title: str = "",
        extended_description: str = "",
        files_changed: int = 0,
        tests_affected: int = 0,
    ) -> None:
        self.commit_title = commit_title
        self.extended_description = extended_description
        self.files_changed = files_changed
        self.tests_affected = tests_affected

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_title": self.commit_title,
            "extended_description": self.extended_description,
            "files_changed": self.files_changed,
            "tests_affected": self.tests_affected,
        }


class PRDraft:
    """A complete PR draft record."""

    def __init__(
        self,
        draft_id: str = "",
        work_item_id: str = "",
        validation_run_id: str = "",
        proposal_id: str = "",
        patch_run_id: str = "",
        status: PRDraftStatus = PRDraftStatus.PENDING,
        summary: PRSummary | None = None,
        validation_section: PRValidationSection | None = None,
        strategic_section: PRStrategicSection | None = None,
        known_limitations: list[str] | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str = "",
    ) -> None:
        self.draft_id = draft_id or str(uuid4())
        self.work_item_id = work_item_id
        self.validation_run_id = validation_run_id
        self.proposal_id = proposal_id
        self.patch_run_id = patch_run_id
        self.status = status
        self.summary = summary
        self.validation_section = validation_section
        self.strategic_section = strategic_section
        self.known_limitations = known_limitations or []
        self.started_at = started_at or datetime.now(timezone.utc).isoformat()
        self.completed_at = completed_at
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "work_item_id": self.work_item_id,
            "validation_run_id": self.validation_run_id,
            "proposal_id": self.proposal_id,
            "patch_run_id": self.patch_run_id,
            "status": self.status.value,
            "summary": self.summary.to_dict() if self.summary else None,
            "validation_section": (
                self.validation_section.to_dict()
                if self.validation_section
                else None
            ),
            "strategic_section": (
                self.strategic_section.to_dict()
                if self.strategic_section
                else None
            ),
            "known_limitations": self.known_limitations,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# PRDraftGenerator
# ---------------------------------------------------------------------------


class PRDraftGenerator:
    """Generates merge-ready PR draft artifacts from validation evidence.

    Safety:
    - No GitHub API, no PR creation, no merge behavior
    - No network dependency, no Git operations
    - Read-only consumption of upstream registries and artifacts
    - Validates all input IDs before processing

    Non-goals: no review finding ingestion, no automatic fixes,
    no learning, no autonomous merge.
    """

    def __init__(
        self,
        db_path: str | None = None,
        artifacts_root: str | None = None,
    ) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        self._artifacts_root = Path(
            artifacts_root or os.environ.get("AXIOM_ARTIFACTS_ROOT", "artifacts"),
        )

    # -- public API ---------------------------------------------------------

    def generate(
        self,
        work_item_id: str = "",
        validation_run_id: str = "",
    ) -> PRDraft:
        """Generate a PR draft from a work item or validation run.

        At least one of work_item_id or validation_run_id must be provided.
        Raises ValueError if inputs are invalid or not found.
        """
        if not work_item_id and not validation_run_id:
            raise ValueError(
                "At least one of work_item_id or validation_run_id required",
            )

        self._validate_id_segment(work_item_id, "work_item_id")
        self._validate_id_segment(validation_run_id, "validation_run_id")

        draft = PRDraft(
            work_item_id=work_item_id,
            validation_run_id=validation_run_id,
        )

        try:
            work_item = self._load_work_item(work_item_id) if work_item_id else {}
            validation_run = (
                self._load_validation_run(validation_run_id)
                if validation_run_id
                else {}
            )

            if validation_run_id and not validation_run:
                raise ValueError(
                    f"Validation run not found: {validation_run_id}",
                )

            if work_item_id and not work_item:
                raise ValueError(f"Work item not found: {work_item_id}")

            patch_run_id = validation_run.get("patch_run_id", "")
            proposal_id = validation_run.get("proposal_id", "")
            self._validate_id_segment(patch_run_id, "patch_run_id")
            self._validate_id_segment(proposal_id, "proposal_id")
            draft.patch_run_id = patch_run_id
            draft.proposal_id = proposal_id

            patch_run = (
                self._load_patch_run(patch_run_id) if patch_run_id else {}
            )
            proposal = (
                self._load_proposal(proposal_id) if proposal_id else {}
            )

            draft.summary = self._build_summary(
                work_item, validation_run, patch_run, proposal,
            )
            draft.validation_section = self._build_validation_section(
                validation_run,
            )
            draft.strategic_section = self._build_strategic_section(
                work_item, proposal,
            )
            draft.known_limitations = self._extract_limitations(
                work_item, proposal,
            )

            draft.status = PRDraftStatus.GENERATED
            draft.completed_at = datetime.now(timezone.utc).isoformat()

        except ValueError:
            raise
        except Exception as exc:
            draft.status = PRDraftStatus.FAILED
            draft.error = f"Unexpected error: {exc}"
            draft.completed_at = datetime.now(timezone.utc).isoformat()

        run_dir = self._create_run_dir(draft.draft_id)
        self._write_request(run_dir, draft)
        self._write_result(run_dir, draft)
        self._write_summary_md(run_dir, draft)
        self._write_pass_fail(run_dir, draft)

        return draft

    def list_drafts(self) -> list[dict[str, Any]]:
        """List all PR drafts from artifact directories."""
        drafts_dir = self._artifacts_root / "pr_drafts"
        if not drafts_dir.exists():
            return []

        results = []
        for run_dir in sorted(drafts_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            result_file = run_dir / "pr_result.json"
            if result_file.exists():
                try:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                    results.append(data)
                except (json.JSONDecodeError, OSError):
                    continue
        return results

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Get a specific PR draft by ID."""
        self._validate_id_segment(draft_id, "draft_id")
        result_file = (
            self._artifacts_root / "pr_drafts" / draft_id / "pr_result.json"
        )
        if not result_file.exists():
            return None
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, label: str) -> None:
        """Reject path-traversal attempts in ID segments."""
        if not value:
            return
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"Invalid {label}: must not contain '..', '/', or '\\\\'",
            )
        if value != Path(value).name:
            raise ValueError(f"Invalid {label}: not a simple filename")

    # -- data loading -------------------------------------------------------

    def _load_work_item(self, work_item_id: str) -> dict[str, Any]:
        """Load work item from registry."""
        try:
            from axiom_core.work_item_registry import WorkItemRegistry

            registry = WorkItemRegistry(db_path=self._db_path)
            item = registry.get_item(work_item_id)
            if item:
                return item.to_dict()
        except Exception:
            pass
        return {}

    def _load_validation_run(self, run_id: str) -> dict[str, Any]:
        """Load validation run from artifact directory."""
        result_file = (
            self._artifacts_root / "code_validation_runs" / run_id
            / "validation_result.json"
        )
        if not result_file.exists():
            return {}
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_patch_run(self, patch_run_id: str) -> dict[str, Any]:
        """Load patch run from artifact directory."""
        if not patch_run_id:
            return {}
        result_file = (
            self._artifacts_root / "patch_runs" / patch_run_id
            / "patch_result.json"
        )
        if not result_file.exists():
            return {}
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Load patch proposal from registry."""
        if not proposal_id:
            return {}
        try:
            from axiom_core.patch_proposal import PatchProposalRegistry

            registry = PatchProposalRegistry(db_path=self._db_path)
            proposal = registry.get_proposal(proposal_id)
            if proposal:
                return proposal.to_dict()
        except Exception:
            pass
        return {}

    # -- draft building -----------------------------------------------------

    def _build_summary(
        self,
        work_item: dict[str, Any],
        validation_run: dict[str, Any],
        patch_run: dict[str, Any],
        proposal: dict[str, Any],
    ) -> PRSummary:
        """Build the PR summary from gathered context."""
        title = self._generate_commit_title(work_item, proposal)
        description = self._generate_description(
            work_item, validation_run, patch_run, proposal,
        )
        files_changed = len(patch_run.get("steps", []))
        tests_affected = sum(
            1 for step in patch_run.get("steps", [])
            if "test" in step.get("file_path", "").lower()
        )

        return PRSummary(
            commit_title=title,
            extended_description=description,
            files_changed=files_changed,
            tests_affected=tests_affected,
        )

    def _generate_commit_title(
        self,
        work_item: dict[str, Any],
        proposal: dict[str, Any],
    ) -> str:
        """Generate a conventional commit title."""
        item_type = work_item.get("item_type", "feature")
        title = work_item.get("title", "")

        type_prefix_map = {
            "bug_fix": "fix",
            "feature": "feat",
            "cleanup": "chore",
            "test": "test",
            "documentation": "docs",
            "refactor": "refactor",
            "validation": "test",
            "investigation": "chore",
            "review_finding": "fix",
        }
        prefix = type_prefix_map.get(item_type, "feat")

        if title:
            return f"{prefix}: {title}"
        if proposal.get("plan_id"):
            return f"{prefix}: implement plan {proposal['plan_id']}"
        return f"{prefix}: automated change"

    def _generate_description(
        self,
        work_item: dict[str, Any],
        validation_run: dict[str, Any],
        patch_run: dict[str, Any],
        proposal: dict[str, Any],
    ) -> str:
        """Generate the extended PR description."""
        lines: list[str] = []

        if work_item.get("description"):
            lines.append(work_item["description"])
            lines.append("")

        if patch_run.get("steps"):
            lines.append("## Key Changes")
            lines.append("")
            for step in patch_run["steps"]:
                fp = step.get("file_path", "")
                edit_type = step.get("edit_type", "modify")
                lines.append(f"- {edit_type}: `{fp}`")
            lines.append("")

        if proposal.get("risk_level"):
            lines.append(f"**Risk level:** {proposal['risk_level']}")
            lines.append("")

        summary = validation_run.get("summary", {})
        if summary:
            lines.append("## Validation")
            lines.append("")
            passed = summary.get("overall_passed", False)
            lines.append(
                f"- Overall: **{'PASSED' if passed else 'FAILED'}**",
            )
            lines.append(
                f"- Stages passed: {summary.get('stages_passed', 0)}",
            )
            lines.append(
                f"- Stages failed: {summary.get('stages_failed', 0)}",
            )
            lines.append(
                f"- Stages skipped: {summary.get('stages_skipped', 0)}",
            )
            lines.append("")

        return "\n".join(lines).strip()

    def _build_validation_section(
        self, validation_run: dict[str, Any],
    ) -> PRValidationSection:
        """Extract validation evidence into structured section."""
        summary = validation_run.get("summary", {})
        evidence = validation_run.get("evidence", [])

        return PRValidationSection(
            validation_run_id=validation_run.get("run_id", ""),
            status=validation_run.get("status", ""),
            overall_passed=summary.get("overall_passed", False),
            stages_passed=summary.get("stages_passed", 0),
            stages_failed=summary.get("stages_failed", 0),
            stages_skipped=summary.get("stages_skipped", 0),
            evidence_paths=[e.get("artifact_path", "") for e in evidence],
        )

    def _build_strategic_section(
        self,
        work_item: dict[str, Any],
        proposal: dict[str, Any],
    ) -> PRStrategicSection:
        """Build the strategic significance section."""
        item_type = work_item.get("item_type", "")
        title = work_item.get("title", "")

        significance = self._derive_significance(item_type, title)
        next_step = self._derive_next_step(item_type)

        non_goals = [
            "No review finding ingestion",
            "No automatic fixes",
            "No PR opening",
            "No learning",
        ]

        what_did_not_change = self._derive_what_did_not_change(proposal)

        return PRStrategicSection(
            significance=significance,
            next_recommended_step=next_step,
            non_goals=non_goals,
            what_did_not_change=what_did_not_change,
        )

    def _derive_significance(self, item_type: str, title: str) -> str:
        """Derive strategic significance from work item type."""
        type_significance = {
            "bug_fix": "Improves reliability of existing capability",
            "feature": "Extends Axiom capability surface",
            "cleanup": "Reduces technical debt",
            "test": "Strengthens verification coverage",
            "documentation": "Improves system documentation",
            "refactor": "Improves internal architecture",
            "validation": "Strengthens the validation backbone",
            "investigation": "Advances understanding of system behavior",
            "review_finding": "Addresses review-identified quality gap",
        }
        base = type_significance.get(item_type, "Advances system capability")
        if title:
            return f"{base}: {title}"
        return base

    def _derive_next_step(self, item_type: str) -> str:
        """Derive next recommended step."""
        type_next_steps = {
            "bug_fix": "Verify fix in production context",
            "feature": "Integration testing with dependent systems",
            "cleanup": "Verify no behavioral regression",
            "test": "Run full validation suite",
            "documentation": "Review for accuracy",
            "refactor": "Verify all dependent tests pass",
            "validation": "Deploy validation to CI pipeline",
            "investigation": "Act on findings",
            "review_finding": "Close originating review thread",
        }
        return type_next_steps.get(item_type, "Review and merge")

    def _derive_what_did_not_change(
        self, proposal: dict[str, Any],
    ) -> list[str]:
        """List what was not affected by this change."""
        items = [
            "No Git operations performed",
            "No GitHub/external API calls",
            "No network dependencies introduced",
        ]
        if proposal.get("rollback_notes"):
            items.append(f"Rollback: {proposal['rollback_notes']}")
        return items

    def _extract_limitations(
        self,
        work_item: dict[str, Any],
        proposal: dict[str, Any],
    ) -> list[str]:
        """Extract known limitations from context."""
        limitations: list[str] = []
        if proposal.get("risks"):
            for risk in proposal["risks"]:
                if isinstance(risk, dict):
                    limitations.append(risk.get("description", str(risk)))
                else:
                    limitations.append(str(risk))
        return limitations

    # -- evidence writing ---------------------------------------------------

    def _create_run_dir(self, draft_id: str) -> Path:
        run_dir = self._artifacts_root / "pr_drafts" / draft_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _write_request(self, run_dir: Path, draft: PRDraft) -> None:
        data = {
            "draft_id": draft.draft_id,
            "work_item_id": draft.work_item_id,
            "validation_run_id": draft.validation_run_id,
            "requested_at": draft.started_at,
        }
        (run_dir / "pr_request.json").write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )

    def _write_result(self, run_dir: Path, draft: PRDraft) -> None:
        (run_dir / "pr_result.json").write_text(
            json.dumps(draft.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _write_summary_md(self, run_dir: Path, draft: PRDraft) -> None:
        lines = [
            "# PR Draft Summary",
            "",
            f"**Draft ID:** {draft.draft_id}",
            f"**Work Item:** {draft.work_item_id or '(none)'}",
            f"**Validation Run:** {draft.validation_run_id or '(none)'}",
            f"**Status:** {draft.status.value}",
            "",
        ]

        if draft.summary:
            lines.extend([
                "## Commit",
                "",
                f"**Title:** {draft.summary.commit_title}",
                "",
                draft.summary.extended_description,
                "",
            ])

        if draft.validation_section:
            vs = draft.validation_section
            lines.extend([
                "## Validation",
                "",
                f"- Run: {vs.validation_run_id}",
                f"- Status: {vs.status}",
                f"- Passed: {'YES' if vs.overall_passed else 'NO'}",
                f"- Stages passed: {vs.stages_passed}",
                f"- Stages failed: {vs.stages_failed}",
                f"- Stages skipped: {vs.stages_skipped}",
                "",
            ])
            if vs.evidence_paths:
                lines.append("### Evidence")
                lines.append("")
                for path in vs.evidence_paths:
                    lines.append(f"- `{path}`")
                lines.append("")

        if draft.strategic_section:
            ss = draft.strategic_section
            lines.extend([
                "## Strategic Significance",
                "",
                ss.significance,
                "",
                f"**Next recommended step:** {ss.next_recommended_step}",
                "",
            ])
            if ss.what_did_not_change:
                lines.append("### What Did Not Change")
                lines.append("")
                for item in ss.what_did_not_change:
                    lines.append(f"- {item}")
                lines.append("")
            if ss.non_goals:
                lines.append("### Non-Goals")
                lines.append("")
                for item in ss.non_goals:
                    lines.append(f"- {item}")
                lines.append("")

        if draft.known_limitations:
            lines.extend(["## Known Limitations", ""])
            for lim in draft.known_limitations:
                lines.append(f"- {lim}")
            lines.append("")

        if draft.error:
            lines.extend(["## Error", "", draft.error, ""])

        (run_dir / "pr_summary.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )

    def _write_pass_fail(self, run_dir: Path, draft: PRDraft) -> None:
        data = {
            "draft_id": draft.draft_id,
            "work_item_id": draft.work_item_id,
            "passed": draft.status == PRDraftStatus.GENERATED,
            "status": draft.status.value,
            "timestamp": (
                draft.completed_at or datetime.now(timezone.utc).isoformat()
            ),
        }
        (run_dir / "pass_fail.json").write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )
