"""Live Coding Trial v1 — controlled practical test of the verification stack.

Runs a minimal, deterministic coding trial that validates a small code change
through the existing stack and produces evidence artifacts.

Non-goals: no workflow engine, no autonomous repair loop, no scheduler,
no agent assignment, no architecture changes.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

_logger = logging.getLogger(__name__)


class LiveCodingTrialRunner:
    """Runs a minimal live coding trial and generates evidence."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._trials_dir = self._artifacts_root / "live_coding_trials"
        self._trials_dir.mkdir(parents=True, exist_ok=True)

    def _safe_trial_path(self, trial_id: str) -> Path:
        """Resolve and validate the trial directory stays inside the sandbox."""
        target = (self._trials_dir / trial_id).resolve()
        sandbox = self._trials_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {trial_id!r}"
            )
        return target

    def run_trial(
        self,
        code_file: str = "src/axiom_core/text_utils.py",
        test_file: str = "tests/test_text_utils.py",
        function_name: str = "safe_slug",
        description: str = "",
    ) -> dict[str, Any]:
        """Run a minimal live coding trial."""
        trial_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # Verify code file exists
        code_path = Path(code_file)
        code_exists = code_path.exists()

        # Verify test file exists
        test_path = Path(test_file)
        test_exists = test_path.exists()

        # Run validation commands
        validation_results: list[dict[str, Any]] = []

        # 1. Run targeted tests
        test_result = self._run_command(
            ["python", "-m", "pytest", test_file, "-v", "--tb=short", "-q"],
            label="targeted_pytest",
        )
        validation_results.append(test_result)

        # 2. Run ruff on the code file
        ruff_result = self._run_command(
            ["python", "-m", "ruff", "check", code_file],
            label="ruff_check",
        )
        validation_results.append(ruff_result)

        # Determine pass/fail
        all_passed = all(r["exit_code"] == 0 for r in validation_results)

        # Build trial result
        trial = {
            "trial_id": trial_id,
            "code_file": code_file,
            "test_file": test_file,
            "function_name": function_name,
            "description": description or f"Live coding trial for {function_name}",
            "code_exists": code_exists,
            "test_exists": test_exists,
            "validation_results": validation_results,
            "all_passed": all_passed,
            "escalation_needed": not all_passed,
            "repair_needed": not all_passed,
            "created_at": created_at,
        }

        # Write evidence
        self._write_evidence(trial_id, trial)

        return trial

    def _run_command(
        self,
        cmd: list[str],
        label: str,
    ) -> dict[str, Any]:
        """Run a validation command and capture results."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "label": label,
                "command": " ".join(cmd),
                "exit_code": result.returncode,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
            }
        except subprocess.TimeoutExpired:
            return {
                "label": label,
                "command": " ".join(cmd),
                "exit_code": -1,
                "stdout": "",
                "stderr": "Command timed out after 120 seconds",
            }
        except Exception as exc:
            return {
                "label": label,
                "command": " ".join(cmd),
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
            }

    def _write_evidence(
        self, trial_id: str, trial: dict[str, Any],
    ) -> str:
        """Write evidence bundle for the trial."""
        evidence_dir = self._safe_trial_path(trial_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # live_coding_trial_request.json
        request_data = {
            "trial_id": trial["trial_id"],
            "code_file": trial["code_file"],
            "test_file": trial["test_file"],
            "function_name": trial["function_name"],
            "description": trial["description"],
        }
        (evidence_dir / "live_coding_trial_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # live_coding_trial_result.json
        (evidence_dir / "live_coding_trial_result.json").write_text(
            json.dumps(trial, indent=2, default=str),
            encoding="utf-8",
        )

        # live_coding_trial_summary.md
        md = self._generate_summary(trial)
        (evidence_dir / "live_coding_trial_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        pass_fail = {
            "passed": trial["all_passed"],
            "trial_id": trial_id,
            "function_name": trial["function_name"],
            "escalation_needed": trial["escalation_needed"],
            "repair_needed": trial["repair_needed"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    @staticmethod
    def _generate_summary(trial: dict[str, Any]) -> str:
        """Generate markdown summary of the trial."""
        lines: list[str] = []
        lines.append(f"# Live Coding Trial: {trial['function_name']}")
        lines.append("")
        lines.append(f"- Trial ID: {trial['trial_id']}")
        lines.append(f"- Code File: {trial['code_file']}")
        lines.append(f"- Test File: {trial['test_file']}")
        lines.append(f"- Function: {trial['function_name']}")
        lines.append(f"- Status: {'PASSED' if trial['all_passed'] else 'FAILED'}")
        lines.append(f"- Created: {trial['created_at']}")
        lines.append("")

        if trial.get("description"):
            lines.append("## Description")
            lines.append("")
            lines.append(trial["description"])
            lines.append("")

        lines.append("## Validation Results")
        lines.append("")
        for vr in trial.get("validation_results", []):
            status = "PASS" if vr["exit_code"] == 0 else "FAIL"
            lines.append(f"### {vr['label']} — {status}")
            lines.append("")
            lines.append(f"Command: `{vr['command']}`")
            lines.append(f"Exit code: {vr['exit_code']}")
            if vr.get("stdout"):
                lines.append("")
                lines.append("```")
                lines.append(vr["stdout"][:500])
                lines.append("```")
            lines.append("")

        lines.append("## Escalation / Repair")
        lines.append("")
        if trial["escalation_needed"]:
            lines.append("Escalation object needed: YES (validation failed)")
        else:
            lines.append("No escalation or repair objects needed — validation passed.")
        lines.append("")

        return "\n".join(lines)
