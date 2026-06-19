"""Code Validation Orchestrator v1.

Validates patch application results through governed stages: targeted tests,
full pytest, ruff linting, CLI walkthrough placeholders, and artifact
inspection placeholders.

Chain: Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
      -> Patch Application -> Code Validation (this module)

Non-goals: no review ingestion, no automatic fixes, no PR generation,
no learning, no autonomous merge.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ValidationRunStatus(str, Enum):
    """Overall status of a code validation run."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    REFUSED = "refused"
    SIMULATED = "simulated"


class StageStatus(str, Enum):
    """Status of an individual validation stage."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REFUSED = "refused"
    BLOCKED = "blocked"
    SIMULATED = "simulated"


class StageKind(str, Enum):
    """Types of validation stages."""

    TARGETED_TESTS = "targeted_tests"
    FULL_PYTEST = "full_pytest"
    RUFF = "ruff"
    CLI_WALKTHROUGH = "cli_walkthrough"
    ARTIFACT_INSPECTION = "artifact_inspection"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CodeValidationEvidence:
    """Evidence artifact produced during validation."""

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


class CodeValidationStageResult:
    """Result of a single stage execution."""

    def __init__(
        self,
        exit_code: int = -1,
        stdout: str = "",
        stderr: str = "",
        duration_ms: int = 0,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout_length": len(self.stdout),
            "stderr_length": len(self.stderr),
            "duration_ms": self.duration_ms,
        }


class CodeValidationStage:
    """A single validation stage with command, result, and status."""

    def __init__(
        self,
        stage_id: str = "",
        kind: StageKind = StageKind.TARGETED_TESTS,
        command: str = "",
        description: str = "",
        required: bool = True,
        status: StageStatus = StageStatus.PENDING,
        result: CodeValidationStageResult | None = None,
        error: str = "",
    ) -> None:
        self.stage_id = stage_id or str(uuid4())
        self.kind = kind
        self.command = command
        self.description = description
        self.required = required
        self.status = status
        self.result = result
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "kind": self.kind.value,
            "command": self.command,
            "description": self.description,
            "required": self.required,
            "status": self.status.value,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


class CodeValidationSummary:
    """Aggregate summary of a validation run."""

    def __init__(
        self,
        total_stages: int = 0,
        stages_passed: int = 0,
        stages_failed: int = 0,
        stages_skipped: int = 0,
        stages_simulated: int = 0,
        stages_refused: int = 0,
        stages_blocked: int = 0,
        overall_passed: bool = False,
        error: str = "",
    ) -> None:
        self.total_stages = total_stages
        self.stages_passed = stages_passed
        self.stages_failed = stages_failed
        self.stages_skipped = stages_skipped
        self.stages_simulated = stages_simulated
        self.stages_refused = stages_refused
        self.stages_blocked = stages_blocked
        self.overall_passed = overall_passed
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_stages": self.total_stages,
            "stages_passed": self.stages_passed,
            "stages_failed": self.stages_failed,
            "stages_skipped": self.stages_skipped,
            "stages_simulated": self.stages_simulated,
            "stages_refused": self.stages_refused,
            "stages_blocked": self.stages_blocked,
            "overall_passed": self.overall_passed,
            "error": self.error,
        }


class CodeValidationRun:
    """A complete code validation run."""

    def __init__(
        self,
        run_id: str = "",
        patch_run_id: str = "",
        proposal_id: str = "",
        simulate: bool = False,
        status: ValidationRunStatus = ValidationRunStatus.PENDING,
        stages: list[CodeValidationStage] | None = None,
        evidence: list[CodeValidationEvidence] | None = None,
        summary: CodeValidationSummary | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid4())
        self.patch_run_id = patch_run_id
        self.proposal_id = proposal_id
        self.simulate = simulate
        self.status = status
        self.stages = stages or []
        self.evidence = evidence or []
        self.summary = summary
        self.started_at = started_at or datetime.now(timezone.utc).isoformat()
        self.completed_at = completed_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "patch_run_id": self.patch_run_id,
            "proposal_id": self.proposal_id,
            "simulate": self.simulate,
            "status": self.status.value,
            "stages": [s.to_dict() for s in self.stages],
            "evidence": [e.to_dict() for e in self.evidence],
            "summary": self.summary.to_dict() if self.summary else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# Allowlisted commands — only these may be executed
# ---------------------------------------------------------------------------

_ALLOWLISTED_COMMANDS: dict[str, str] = {
    "targeted_tests": "poetry run pytest {test_files} -x -q",
    "full_pytest": "poetry run pytest -x -q",
    "ruff": "poetry run ruff check {files}",
}

_PLACEHOLDER_STAGES = {"cli_walkthrough", "artifact_inspection"}


# ---------------------------------------------------------------------------
# CodeValidationOrchestrator
# ---------------------------------------------------------------------------


class CodeValidationOrchestrator:
    """Validates patch application results through governed stages.

    Safety:
    - Refuses unknown or unsuccessful patch runs
    - Allowlisted commands only (no arbitrary execution)
    - Repo-root boundary enforcement
    - No git operations, no network dependency

    Non-goals: no review ingestion, no automatic fixes, no PR generation,
    no learning, no autonomous merge.
    """

    def __init__(
        self,
        db_path: str | None = None,
        workspace_root: str | None = None,
        artifacts_root: str | None = None,
    ) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        self._workspace_root = Path(
            workspace_root or os.environ.get("AXIOM_WORKSPACE_ROOT", "."),
        ).resolve()
        self._artifacts_root = Path(
            artifacts_root or os.environ.get("AXIOM_ARTIFACTS_ROOT", "artifacts"),
        )

    # -- public API ---------------------------------------------------------

    def validate(
        self,
        patch_run_id: str,
        simulate: bool = False,
    ) -> CodeValidationRun:
        """Validate a patch application run.

        Raises ValueError if the patch run is not found or was not successful.
        """
        patch_run = self._get_patch_run(patch_run_id)

        run = CodeValidationRun(
            patch_run_id=patch_run_id,
            proposal_id=patch_run.get("proposal_id", ""),
            simulate=simulate,
            status=ValidationRunStatus.RUNNING,
        )

        run_dir = self._create_run_dir(run.run_id)
        self._write_request(run_dir, run, patch_run)

        stages = self._build_stages(patch_run)
        try:
            self._execute_stages(run, stages, run_dir, simulate)
            has_required_failures = any(
                s.status == StageStatus.FAILED and s.required
                for s in run.stages
            )
            if has_required_failures:
                run.status = ValidationRunStatus.FAILED
            elif simulate:
                run.status = ValidationRunStatus.SIMULATED
            else:
                run.status = ValidationRunStatus.PASSED
        except Exception as exc:
            run.status = ValidationRunStatus.FAILED
            run.stages.append(
                CodeValidationStage(
                    kind=StageKind.FULL_PYTEST,
                    description="Orchestrator error (not a specific stage)",
                    status=StageStatus.FAILED,
                    required=True,
                    error=f"Unexpected orchestrator error: {exc}",
                ),
            )

        run.summary = self._build_summary(run)
        run.completed_at = datetime.now(timezone.utc).isoformat()
        self._write_summary_md(run_dir, run)
        self._write_pass_fail(run_dir, run)
        self._write_result(run_dir, run)

        return run

    def list_runs(self) -> list[dict[str, Any]]:
        """List all validation runs from artifact directories."""
        runs_dir = self._artifacts_root / "code_validation_runs"
        if not runs_dir.exists():
            return []

        results = []
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            result_file = run_dir / "validation_result.json"
            if result_file.exists():
                try:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                    results.append(data)
                except (json.JSONDecodeError, OSError):
                    continue
        return results

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a specific validation run by ID."""
        self._validate_id_segment(run_id, "run_id")
        result_file = (
            self._artifacts_root / "code_validation_runs" / run_id
            / "validation_result.json"
        )
        if not result_file.exists():
            return None
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # -- safety gate --------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, label: str) -> None:
        """Reject path-traversal attempts in ID segments."""
        if not value or ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"Invalid {label}: must not contain '..', '/', or '\\'",
            )
        if value != Path(value).name:
            raise ValueError(f"Invalid {label}: not a simple filename")

    @staticmethod
    def _validate_file_path(path: str) -> None:
        """Reject file paths that could inject arguments or traverse."""
        if not path:
            raise ValueError("Empty file path")
        if path.startswith("-"):
            raise ValueError(
                f"File path must not start with '-': {path}",
            )
        if ".." in path:
            raise ValueError(
                f"File path must not contain '..': {path}",
            )

    def _get_patch_run(self, patch_run_id: str) -> dict[str, Any]:
        """Load and validate a patch application run result."""
        self._validate_id_segment(patch_run_id, "patch_run_id")
        result_file = (
            self._artifacts_root / "patch_runs" / patch_run_id
            / "patch_result.json"
        )
        if not result_file.exists():
            raise ValueError(
                f"Patch run not found: {patch_run_id} "
                f"(no patch_result.json at {result_file})",
            )

        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                f"Cannot read patch run result: {patch_run_id} ({exc})",
            )

        status = data.get("status", "")
        if status not in ("completed", "simulated"):
            raise ValueError(
                f"Patch run {patch_run_id} has status '{status}' — "
                f"only completed or simulated runs can be validated",
            )

        result = data.get("result", {})
        if not result.get("success", False):
            raise ValueError(
                f"Patch run {patch_run_id} was not successful "
                f"(success={result.get('success')})",
            )

        return data

    # -- stage building -----------------------------------------------------

    def _build_stages(
        self, patch_run: dict[str, Any],
    ) -> list[CodeValidationStage]:
        """Build the deterministic stage list from patch run metadata."""
        stages: list[CodeValidationStage] = []
        changed_files = self._extract_changed_files(patch_run)
        test_files = [f for f in changed_files if self._is_test_file(f)]
        src_files = [f for f in changed_files if not self._is_test_file(f)]

        if test_files:
            quoted_tests = " ".join(shlex.quote(f) for f in test_files)
            stages.append(CodeValidationStage(
                kind=StageKind.TARGETED_TESTS,
                command=_ALLOWLISTED_COMMANDS["targeted_tests"].format(
                    test_files=quoted_tests,
                ),
                description=f"Run targeted tests: {', '.join(test_files)}",
                required=True,
            ))

        stages.append(CodeValidationStage(
            kind=StageKind.FULL_PYTEST,
            command=_ALLOWLISTED_COMMANDS["full_pytest"],
            description="Run full pytest suite",
            required=True,
        ))

        if src_files:
            quoted_srcs = " ".join(shlex.quote(f) for f in src_files)
            stages.append(CodeValidationStage(
                kind=StageKind.RUFF,
                command=_ALLOWLISTED_COMMANDS["ruff"].format(
                    files=quoted_srcs,
                ),
                description=f"Ruff check: {', '.join(src_files)}",
                required=True,
            ))

        stages.append(CodeValidationStage(
            kind=StageKind.CLI_WALKTHROUGH,
            command="",
            description="CLI walkthrough (placeholder — not yet implemented)",
            required=False,
        ))

        stages.append(CodeValidationStage(
            kind=StageKind.ARTIFACT_INSPECTION,
            command="",
            description="Artifact inspection (placeholder — not yet implemented)",
            required=False,
        ))

        return stages

    def _extract_changed_files(
        self, patch_run: dict[str, Any],
    ) -> list[str]:
        """Extract and validate file paths from patch run steps."""
        files = []
        for step in patch_run.get("steps", []):
            fp = step.get("file_path", "")
            if fp:
                self._validate_file_path(fp)
                files.append(fp)
        return files

    def _is_test_file(self, path: str) -> bool:
        name = Path(path).name
        return name.startswith("test_") or name.endswith("_test.py")

    # -- stage execution ----------------------------------------------------

    def _execute_stages(
        self,
        run: CodeValidationRun,
        stages: list[CodeValidationStage],
        run_dir: Path,
        simulate: bool,
    ) -> None:
        for stage in stages:
            if stage.kind.value in _PLACEHOLDER_STAGES:
                stage.status = StageStatus.SKIPPED
                stage.error = "Placeholder — not yet implemented"
                run.stages.append(stage)
                continue

            if not stage.command:
                stage.status = StageStatus.SKIPPED
                stage.error = "No command specified"
                run.stages.append(stage)
                continue

            if not self._is_command_allowed(stage.command):
                stage.status = StageStatus.REFUSED
                stage.error = "Command not in allowlist"
                run.stages.append(stage)
                continue

            if simulate:
                stage.status = StageStatus.SIMULATED
                stage.result = CodeValidationStageResult(
                    exit_code=0, stdout="(simulated)", stderr="",
                    duration_ms=0,
                )
                run.stages.append(stage)
                continue

            try:
                stage_result = self._run_command(stage.command)
                stage.result = stage_result
                stage.status = (
                    StageStatus.PASSED
                    if stage_result.exit_code == 0
                    else StageStatus.FAILED
                )
                if stage_result.exit_code != 0:
                    stage.error = (
                        f"Exit code {stage_result.exit_code}"
                    )
                self._write_stage_output(run_dir, stage)
            except Exception as exc:
                stage.status = StageStatus.FAILED
                stage.error = str(exc)

            run.stages.append(stage)

    def _is_command_allowed(self, command: str) -> bool:
        """Check if a command matches the allowlist patterns."""
        for template in _ALLOWLISTED_COMMANDS.values():
            prefix = template.split("{")[0].strip()
            if command.startswith(prefix):
                return True
        return False

    def _run_command(self, command: str) -> CodeValidationStageResult:
        """Execute a command within the workspace root."""
        start = datetime.now(timezone.utc)
        try:
            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self._workspace_root),
            )
            elapsed = int(
                (datetime.now(timezone.utc) - start).total_seconds() * 1000,
            )
            return CodeValidationStageResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = int(
                (datetime.now(timezone.utc) - start).total_seconds() * 1000,
            )
            return CodeValidationStageResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out after 300 seconds",
                duration_ms=elapsed,
            )

    def _write_stage_output(
        self, run_dir: Path, stage: CodeValidationStage,
    ) -> None:
        """Write stage stdout/stderr to evidence directories."""
        if stage.result is None:
            return

        if stage.kind == StageKind.TARGETED_TESTS:
            out_dir = run_dir / "test_outputs"
        elif stage.kind == StageKind.FULL_PYTEST:
            out_dir = run_dir / "test_outputs"
        elif stage.kind == StageKind.RUFF:
            out_dir = run_dir / "ruff_output"
        elif stage.kind == StageKind.CLI_WALKTHROUGH:
            out_dir = run_dir / "walkthroughs"
        else:
            out_dir = run_dir / "misc_output"

        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = stage.stage_id[:12]

        if stage.result.stdout:
            (out_dir / f"{safe_name}_stdout.txt").write_text(
                stage.result.stdout, encoding="utf-8",
            )
        if stage.result.stderr:
            (out_dir / f"{safe_name}_stderr.txt").write_text(
                stage.result.stderr, encoding="utf-8",
            )

    # -- summary ------------------------------------------------------------

    def _build_summary(self, run: CodeValidationRun) -> CodeValidationSummary:
        counts = {s.value: 0 for s in StageStatus}
        for stage in run.stages:
            counts[stage.status.value] += 1

        has_required_failure = any(
            s.status == StageStatus.FAILED and s.required
            for s in run.stages
        )
        overall_passed = not has_required_failure and run.status != ValidationRunStatus.FAILED

        return CodeValidationSummary(
            total_stages=len(run.stages),
            stages_passed=counts["passed"],
            stages_failed=counts["failed"],
            stages_skipped=counts["skipped"],
            stages_simulated=counts["simulated"],
            stages_refused=counts["refused"],
            stages_blocked=counts["blocked"],
            overall_passed=overall_passed,
            error="" if overall_passed else "One or more required stages failed",
        )

    # -- evidence writing ---------------------------------------------------

    def _create_run_dir(self, run_id: str) -> Path:
        run_dir = self._artifacts_root / "code_validation_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _write_request(
        self, run_dir: Path, run: CodeValidationRun,
        patch_run: dict[str, Any],
    ) -> None:
        data = {
            "run_id": run.run_id,
            "patch_run_id": run.patch_run_id,
            "proposal_id": run.proposal_id,
            "simulate": run.simulate,
            "requested_at": run.started_at,
            "patch_run_status": patch_run.get("status", ""),
        }
        (run_dir / "validation_request.json").write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )
        run.evidence.append(CodeValidationEvidence(
            artifact_type="validation_request",
            artifact_path=str(run_dir / "validation_request.json"),
            description="Validation run request metadata",
        ))

    def _write_result(
        self, run_dir: Path, run: CodeValidationRun,
    ) -> None:
        result_path = str(run_dir / "validation_result.json")
        run.evidence.append(CodeValidationEvidence(
            artifact_type="validation_result",
            artifact_path=result_path,
            description="Full validation run result",
        ))
        (run_dir / "validation_result.json").write_text(
            json.dumps(run.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _write_summary_md(
        self, run_dir: Path, run: CodeValidationRun,
    ) -> None:
        summary = run.summary
        lines = [
            "# Code Validation Summary",
            "",
            f"**Run ID:** {run.run_id}",
            f"**Patch Run:** {run.patch_run_id}",
            f"**Proposal:** {run.proposal_id}",
            f"**Simulate:** {run.simulate}",
            f"**Status:** {run.status.value}",
            "",
        ]

        if summary:
            lines.extend([
                "## Results",
                "",
                "| Metric | Count |",
                "|--------|-------|",
                f"| Total stages | {summary.total_stages} |",
                f"| Passed | {summary.stages_passed} |",
                f"| Failed | {summary.stages_failed} |",
                f"| Skipped | {summary.stages_skipped} |",
                f"| Simulated | {summary.stages_simulated} |",
                f"| Refused | {summary.stages_refused} |",
                f"| Blocked | {summary.stages_blocked} |",
                "",
                f"**Overall:** {'PASSED' if summary.overall_passed else 'FAILED'}",
                "",
            ])

        if run.stages:
            lines.extend(["## Stages", ""])
            for i, stage in enumerate(run.stages, 1):
                marker = {
                    "passed": "PASSED",
                    "failed": "FAILED",
                    "skipped": "SKIPPED",
                    "simulated": "SIMULATED",
                    "refused": "REFUSED",
                    "blocked": "BLOCKED",
                }.get(stage.status.value, stage.status.value)
                lines.append(
                    f"{i}. **[{marker}]** {stage.kind.value}: "
                    f"{stage.description}",
                )
                if stage.error:
                    lines.append(f"   - Error: {stage.error}")
                if stage.result and stage.result.exit_code != 0:
                    lines.append(
                        f"   - Exit code: {stage.result.exit_code}",
                    )
            lines.append("")

        (run_dir / "validation_summary.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )
        run.evidence.append(CodeValidationEvidence(
            artifact_type="validation_summary",
            artifact_path=str(run_dir / "validation_summary.md"),
            description="Human-readable validation summary",
        ))

    def _write_pass_fail(
        self, run_dir: Path, run: CodeValidationRun,
    ) -> None:
        data = {
            "run_id": run.run_id,
            "patch_run_id": run.patch_run_id,
            "passed": run.summary.overall_passed if run.summary else False,
            "status": run.status.value,
            "timestamp": run.completed_at or datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / "pass_fail.json").write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )
        run.evidence.append(CodeValidationEvidence(
            artifact_type="pass_fail",
            artifact_path=str(run_dir / "pass_fail.json"),
            description="Machine-readable pass/fail verdict",
        ))
