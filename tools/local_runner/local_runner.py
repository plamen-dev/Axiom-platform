"""Axiom Local Runner v0 — restricted local developer/agent execution harness.

Security model:
- No arbitrary shell commands.
- Only named allowlisted actions.
- Workspace restricted to allowed base paths.
- Timeout handling with process kill.
- All stdout/stderr captured to artifact files.
- No secret reading, no external uploads, no file deletion outside artifacts.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Allowed workspace base paths
# ---------------------------------------------------------------------------

ALLOWED_WORKSPACE_BASES_WINDOWS = [
    r"C:\Dev\Axiom",
]

ALLOWED_WORKSPACE_BASES_POSIX = [
    str(Path.home() / "repos"),
    str(Path.home() / "Dev" / "Axiom"),
    "/home",
]

# ---------------------------------------------------------------------------
# Allowed actions → fixed commands
# ---------------------------------------------------------------------------

def _get_allowed_actions() -> dict[str, dict]:
    """Build allowed actions dict.

    Uses 'poetry run ...' instead of 'python -m poetry run ...' because
    inside a Poetry virtualenv the venv Python does not have the poetry
    module installed. 'poetry' is on PATH as a standalone CLI tool.
    """
    return {
        "git_status": {
            "commands": [
                ["git", "status", "--short"],
                ["git", "branch", "--show-current"],
                ["git", "log", "-1", "--oneline"],
            ],
            "description": "Show git status, current branch, and last commit.",
        },
        "pytest": {
            "commands": [
                ["poetry", "run", "pytest"],
            ],
            "description": "Run the full pytest suite via Poetry.",
        },
        "ruff": {
            "commands": [
                ["poetry", "run", "ruff", "check", "."],
            ],
            "description": "Run ruff linter on the workspace.",
        },
        "test_grids": {
            "commands": [
                ["poetry", "run", "axiom", "test-grids", "--mode", "simulate"],
            ],
            "description": "Run grid simulation test harness.",
        },
        "test_levels": {
            "commands": [
                ["poetry", "run", "axiom", "test-levels", "--mode", "simulate"],
            ],
            "description": "Run level simulation test harness.",
        },
        "dotnet_build_revit_2027": {
            "commands": [
                ["dotnet", "build", "src/axiom_revit/Axiom.Revit.2027.sln",
                 "-c", "Release", "-p:Platform=x64"],
            ],
            "description": "Build the Revit 2027 solution (Release|x64). Does not deploy.",
        },
        "deploy_revit_2027": {
            "commands": [
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/deploy-revit-2027.ps1"],
            ],
            "description": "Build and deploy Axiom to Revit 2027.",
        },
        "collect_revit_journals": {
            "commands": [],
            "description": "Placeholder -- collect Revit journal files.",
            "not_implemented": True,
            "planned_paths": [
                r"%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit 2027\Journals",
            ],
        },
        "kill_revit": {
            "commands": [],
            "description": "Placeholder -- kill running Revit processes.",
            "not_implemented": True,
            "requires_flag": "allow_kill_revit",
        },
        "test_pr_snapshot": {
            "commands": [
                ["poetry", "run", "pytest", "tests/test_pr_snapshot.py"],
            ],
            "description": "Run PR evidence snapshot workflow tests.",
        },
        "test_set_parameter_value": {
            "commands": [
                ["poetry", "run", "pytest", "tests/test_set_parameter_value.py"],
            ],
            "description": "Run SetParameterValue v0 tests.",
        },
        "test_validation_loop": {
            "commands": [
                ["poetry", "run", "pytest", "tests/test_validation_loop.py"],
            ],
            "description": "Run Validation Automation Loop v0 tests.",
        },
    }


# Keep a module-level reference for validation (action names only)
ALLOWED_ACTIONS = _get_allowed_actions()

DEFAULT_TIMEOUT = 300


class RunResult:
    """Result of a local runner execution."""

    def __init__(self):
        self.run_id: str = ""
        self.action: str = ""
        self.workspace: str = ""
        self.started_at: str = ""
        self.completed_at: str = ""
        self.duration_ms: int = 0
        self.exit_code: int = -1
        self.timed_out: bool = False
        self.status: str = "pending"
        self.command_executed: str = ""
        self.stdout: str = ""
        self.stderr: str = ""
        self.error_message: str = ""
        self.artifact_dir: str = ""
        self.prompt: str = ""
        self.resolved_action: str = ""
        self.command_display: str = ""


def validate_workspace(workspace: str) -> str | None:
    """Validate workspace path is within allowed bases. Returns error message or None."""
    workspace_path = Path(workspace).resolve()

    if platform.system() == "Windows":
        bases = ALLOWED_WORKSPACE_BASES_WINDOWS
    else:
        bases = ALLOWED_WORKSPACE_BASES_POSIX

    for base in bases:
        try:
            base_path = Path(base).resolve()
            if workspace_path == base_path or base_path in workspace_path.parents:
                return None
        except (OSError, ValueError):
            continue

    return (
        f"Workspace '{workspace}' is outside allowed paths. "
        f"Allowed: {', '.join(bases)}"
    )


def validate_task(task: dict) -> str | None:
    """Validate task.json structure. Returns error message or None."""
    action = task.get("action")
    if not action:
        return "Missing required field: action"

    if action not in ALLOWED_ACTIONS:
        return f"Unknown action '{action}'. Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}"

    workspace = task.get("workspace")
    if not workspace:
        return "Missing required field: workspace"

    ws_error = validate_workspace(workspace)
    if ws_error:
        return ws_error

    # Check for shell injection attempts
    if "command" in task or "shell" in task or "cmd" in task:
        return "Arbitrary command execution is not allowed. Use named actions only."

    return None


def _build_environment_summary(workspace: str) -> dict:
    """Collect safe environment information."""
    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version,
        "workspace": workspace,
        "cwd": os.getcwd(),
        "user": os.environ.get("USERNAME", os.environ.get("USER", "")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _write_failure_summary(result: RunResult, artifact_dir: Path) -> Path:
    """Write a failure_summary.md with diagnostics."""
    path = artifact_dir / "failure_summary.md"

    stdout_lines = result.stdout.splitlines()
    stderr_lines = result.stderr.splitlines()
    last_stdout = "\n".join(stdout_lines[-50:]) if stdout_lines else "(empty)"
    last_stderr = "\n".join(stderr_lines[-50:]) if stderr_lines else "(empty)"

    likely_reason = "Unknown"
    if result.timed_out:
        likely_reason = "Action timed out after configured timeout."
    elif result.exit_code != 0:
        if "ModuleNotFoundError" in result.stderr:
            likely_reason = "Missing Python module dependency."
        elif "Could not find" in result.stderr or "not found" in result.stderr.lower():
            likely_reason = "Required tool or file not found."
        elif "FAILED" in result.stdout:
            likely_reason = "Test failures detected."
        elif "error" in result.stderr.lower():
            likely_reason = "Execution error — see stderr below."
        else:
            likely_reason = f"Process exited with code {result.exit_code}."

    suggested = "Review the stderr output and fix the root cause."
    if "test" in result.action.lower():
        suggested = "Review failing tests, fix code, and re-run."
    elif result.action == "dotnet_build_revit_2027":
        suggested = "Check build errors. Ensure .NET SDK and Revit API DLLs are available."
    elif result.action == "deploy_revit_2027":
        suggested = "Check if Revit is running (DLL lock). Close Revit and retry."

    lines = [
        f"# Failure Summary: {result.action}",
        "",
        f"- **Action:** {result.action}",
        f"- **Status:** {result.status}",
        f"- **Exit code:** {result.exit_code}",
        f"- **Timed out:** {result.timed_out}",
        f"- **Duration:** {result.duration_ms}ms",
        f"- **Command:** {result.command_executed}",
        "",
        "## Likely Failure Reason",
        "",
        likely_reason,
        "",
        "## Last 50 Lines of stderr",
        "",
        "```",
        last_stderr,
        "```",
        "",
        "## Last 50 Lines of stdout",
        "",
        "```",
        last_stdout,
        "```",
        "",
        "## Suggested Next Action",
        "",
        suggested,
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _format_command_display(action_def: dict) -> str:
    """Format the allowlisted commands as a human-readable string."""
    commands = action_def.get("commands", [])
    if not commands:
        return "(not implemented)"
    return " && ".join(" ".join(cmd) for cmd in commands)


def _interpret_result(result: RunResult) -> str:
    """Produce a human-readable interpretation of the run result."""
    if result.status == "success":
        action = result.resolved_action or result.action
        if action == "ruff":
            return "No lint violations reported."
        if action.startswith("test_") or action == "pytest":
            # Parse pytest summary line: "X passed, Y skipped, Z failed"
            match = re.search(
                r"(\d+ passed(?:, \d+ \w+)*)",
                result.stdout,
            )
            if match:
                return match.group(1) + "."
            return "Tests passed (summary not parsed)."
        if action == "git_status":
            return "Repository state captured."
        return "Action completed successfully."
    if result.status == "timed_out":
        return "Action timed out. See failure_summary.md for details."
    if result.status == "not_implemented":
        return f"Action not yet implemented: {result.error_message}"
    if result.status == "failed":
        # Include last useful line from stderr or stdout
        for source in (result.stderr, result.stdout):
            lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
            if lines:
                last = lines[-1][:200]
                return f"Action failed (exit code {result.exit_code}). Last output: {last}\nSee failure_summary.md for details."
        return f"Action failed with exit code {result.exit_code}. See failure_summary.md for details."
    return f"Status: {result.status}"


def _write_result_summary(result: RunResult, task: dict, artifact_dir: Path) -> Path:
    """Write result_summary.md for every run (success or failure)."""
    path = artifact_dir / "result_summary.md"

    prompt = result.prompt or "N/A"
    interpretation = _interpret_result(result)

    artifacts_list = [
        "task.json",
        "run_log.json",
        "environment_summary.json",
        "stdout.txt",
        "stderr.txt",
        "result_summary.md",
    ]
    if result.status != "success":
        artifacts_list.append("failure_summary.md")

    lines = [
        f"# Result Summary: {result.resolved_action or result.action}",
        "",
        "## Original Prompt/Request",
        "",
        prompt,
        "",
        "## Resolved Action",
        "",
        result.resolved_action or result.action,
        "",
        "## Command Executed",
        "",
        f"`{result.command_display}`" if result.command_display else "(none)",
        "",
        "## Execution Metadata",
        "",
        f"- **Status:** {result.status}",
        f"- **Exit code:** {result.exit_code}",
        f"- **Duration:** {result.duration_ms}ms",
        f"- **Workspace:** {result.workspace}",
        f"- **Timed out:** {result.timed_out}",
        f"- **Started at:** {result.started_at}",
        f"- **Completed at:** {result.completed_at}",
        "",
        "## Result",
        "",
        interpretation,
        "",
        "## Artifacts",
        "",
    ]
    for name in artifacts_list:
        lines.append(f"- `{name}`")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def execute_task(task: dict, artifact_base: str = "artifacts/local_runner_runs") -> RunResult:
    """Execute a validated task and produce artifacts.

    Args:
        task: Parsed task.json dict.
        artifact_base: Base directory for run artifacts.

    Returns:
        RunResult with execution details.
    """
    result = RunResult()
    result.action = task.get("action", "")
    result.workspace = task.get("workspace", "")
    result.run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    result.prompt = task.get("prompt", "") or task.get("metadata", {}).get("purpose", "") or ""
    result.resolved_action = result.action

    # Validate
    error = validate_task(task)
    if error:
        result.status = "blocked"
        result.error_message = error
        result.started_at = datetime.now(timezone.utc).isoformat()
        result.completed_at = result.started_at
        return result

    actions = _get_allowed_actions()
    action_def = actions[result.action]
    timeout = task.get("timeout_seconds", DEFAULT_TIMEOUT)

    # Create artifact directory
    artifact_dir = Path(artifact_base) / result.run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result.artifact_dir = str(artifact_dir)

    # Copy task.json into artifacts
    task_copy_path = artifact_dir / "task.json"
    task_copy_path.write_text(json.dumps(task, indent=2), encoding="utf-8")

    # Write environment summary
    env_summary = _build_environment_summary(result.workspace)
    env_path = artifact_dir / "environment_summary.json"
    env_path.write_text(json.dumps(env_summary, indent=2), encoding="utf-8")

    result.command_display = _format_command_display(action_def)

    # Handle not-implemented actions
    if action_def.get("not_implemented"):
        requires_flag = action_def.get("requires_flag")
        if requires_flag and not task.get("metadata", {}).get(requires_flag):
            result.status = "not_implemented"
            result.error_message = (
                f"Action '{result.action}' is not yet implemented. "
                f"Requires flag: {requires_flag}=true in metadata."
            )
        else:
            result.status = "not_implemented"
            result.error_message = f"Action '{result.action}' is not yet implemented."

        result.started_at = datetime.now(timezone.utc).isoformat()
        result.completed_at = result.started_at
        result.command_executed = result.action

        # Write artifacts
        (artifact_dir / "stdout.txt").write_text("", encoding="utf-8")
        (artifact_dir / "stderr.txt").write_text(result.error_message, encoding="utf-8")
        _write_run_log(result, artifact_dir)
        _write_failure_summary(result, artifact_dir)
        _write_result_summary(result, task, artifact_dir)
        return result

    # Execute commands
    commands = action_def["commands"]
    result.command_executed = result.action
    result.started_at = datetime.now(timezone.utc).isoformat()

    all_stdout: list[str] = []
    all_stderr: list[str] = []
    start_time = time.monotonic()

    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                cwd=result.workspace,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            all_stdout.append(proc.stdout)
            all_stderr.append(proc.stderr)
            result.exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            result.timed_out = True
            result.exit_code = -1
            all_stderr.append(f"TIMEOUT: Command timed out after {timeout}s")
            break
        except FileNotFoundError as e:
            result.exit_code = -1
            all_stderr.append(f"Command not found: {e}")
            break
        except OSError as e:
            result.exit_code = -1
            all_stderr.append(f"OS error: {e}")
            break

    elapsed = time.monotonic() - start_time
    result.duration_ms = int(elapsed * 1000)
    result.completed_at = datetime.now(timezone.utc).isoformat()
    result.stdout = "\n".join(all_stdout)
    result.stderr = "\n".join(all_stderr)

    if result.timed_out:
        result.status = "timed_out"
    elif result.exit_code == 0:
        result.status = "success"
    else:
        result.status = "failed"

    # Write artifacts
    (artifact_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    _write_run_log(result, artifact_dir)

    if result.status != "success":
        _write_failure_summary(result, artifact_dir)

    _write_result_summary(result, task, artifact_dir)

    return result


def _write_run_log(result: RunResult, artifact_dir: Path) -> Path:
    """Write run_log.json to artifact directory."""
    path = artifact_dir / "run_log.json"
    log = {
        "run_id": result.run_id,
        "action": result.action,
        "prompt": result.prompt or "N/A",
        "resolved_action": result.resolved_action or result.action,
        "command_executed": result.command_display or result.command_executed,
        "workspace": result.workspace,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_ms": result.duration_ms,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "status": result.status,
        "stdout_path": str(artifact_dir / "stdout.txt"),
        "stderr_path": str(artifact_dir / "stderr.txt"),
        "result_summary_path": str(artifact_dir / "result_summary.md"),
        "failure_summary_path": (
            str(artifact_dir / "failure_summary.md")
            if result.status != "success" else ""
        ),
    }
    if result.error_message:
        log["error_message"] = result.error_message
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return path


def run_from_task_file(task_path: str, artifact_base: str = "artifacts/local_runner_runs") -> RunResult:
    """Load a task.json file and execute it."""
    task_file = Path(task_path)
    if not task_file.exists():
        result = RunResult()
        result.status = "blocked"
        result.error_message = f"Task file not found: {task_path}"
        return result

    try:
        task = json.loads(task_file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as e:
        result = RunResult()
        result.status = "blocked"
        result.error_message = f"Failed to parse task file: {e}"
        return result

    return execute_task(task, artifact_base=artifact_base)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Axiom Local Runner")
    parser.add_argument("--task", required=True, help="Path to task.json")
    parser.add_argument(
        "--artifact-dir",
        default="artifacts/local_runner_runs",
        help="Base directory for run artifacts",
    )
    args = parser.parse_args()

    run_result = run_from_task_file(args.task, artifact_base=args.artifact_dir)
    print(f"Status: {run_result.status}")
    print(f"Exit code: {run_result.exit_code}")
    if run_result.artifact_dir:
        print(f"Artifacts: {run_result.artifact_dir}")
    if run_result.error_message:
        print(f"Error: {run_result.error_message}")
    sys.exit(0 if run_result.status == "success" else 1)
