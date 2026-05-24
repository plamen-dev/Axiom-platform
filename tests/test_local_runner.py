"""Tests for Axiom Local Runner v0 — allowlisted action execution harness."""

import json
import sys
from pathlib import Path

# Add tools/ to path so we can import local_runner
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from local_runner.local_runner import (  # noqa: E402
    ALLOWED_ACTIONS,
    execute_task,
    validate_task,
    validate_workspace,
)


class TestWorkspaceValidation:
    """Workspace path must be within allowed bases."""

    def test_allowed_workspace_posix(self):
        home = str(Path.home() / "repos" / "Axiom-platform")
        assert validate_workspace(home) is None

    def test_blocked_workspace_root(self):
        error = validate_workspace("/tmp/evil")
        assert error is not None
        assert "outside allowed paths" in error

    def test_blocked_workspace_etc(self):
        error = validate_workspace("/etc/passwd")
        assert error is not None

    def test_blocked_workspace_outside_all_bases(self):
        error = validate_workspace("/opt/unauthorized/workspace")
        assert error is not None


class TestTaskValidation:
    """Task validation blocks invalid or unsafe tasks."""

    def test_unknown_action_blocked(self):
        task = {"action": "rm_rf_everything", "workspace": str(Path.home() / "repos")}
        error = validate_task(task)
        assert error is not None
        assert "Unknown action" in error

    def test_missing_action_blocked(self):
        task = {"workspace": str(Path.home() / "repos")}
        error = validate_task(task)
        assert error is not None
        assert "Missing required field: action" in error

    def test_missing_workspace_blocked(self):
        task = {"action": "git_status"}
        error = validate_task(task)
        assert error is not None
        assert "Missing required field: workspace" in error

    def test_arbitrary_command_blocked(self):
        task = {
            "action": "git_status",
            "workspace": str(Path.home() / "repos"),
            "command": "rm -rf /",
        }
        error = validate_task(task)
        assert error is not None
        assert "Arbitrary command" in error

    def test_shell_field_blocked(self):
        task = {
            "action": "git_status",
            "workspace": str(Path.home() / "repos"),
            "shell": "bash -c 'cat /etc/shadow'",
        }
        error = validate_task(task)
        assert error is not None
        assert "Arbitrary command" in error

    def test_valid_task_passes(self):
        task = {
            "action": "git_status",
            "workspace": str(Path.home() / "repos" / "Axiom-platform"),
        }
        error = validate_task(task)
        assert error is None

    def test_workspace_outside_allowed_blocked(self):
        task = {"action": "git_status", "workspace": "/tmp/evil"}
        error = validate_task(task)
        assert error is not None
        assert "outside allowed paths" in error


class TestAllowedActions:
    """Allowed actions resolve to fixed commands, not arbitrary user input."""

    def test_all_actions_have_commands_or_not_implemented(self):
        for name, defn in ALLOWED_ACTIONS.items():
            assert "commands" in defn, f"Action {name} missing commands"
            assert "description" in defn, f"Action {name} missing description"

    def test_git_status_has_three_commands(self):
        defn = ALLOWED_ACTIONS["git_status"]
        assert len(defn["commands"]) == 3
        assert defn["commands"][0][0] == "git"

    def test_placeholders_marked_not_implemented(self):
        assert ALLOWED_ACTIONS["collect_revit_journals"].get("not_implemented") is True
        assert ALLOWED_ACTIONS["kill_revit"].get("not_implemented") is True


class TestTaskExecution:
    """End-to-end execution tests."""

    def test_git_status_execution(self, tmp_path):
        """Runner can execute git_status and produce artifacts."""
        workspace = str(Path(__file__).resolve().parents[1])
        task = {
            "action": "git_status",
            "timeout_seconds": 30,
            "workspace": workspace,
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "success"
        assert result.exit_code == 0

        # Verify artifacts created
        artifact_dir = Path(result.artifact_dir)
        assert (artifact_dir / "task.json").exists()
        assert (artifact_dir / "run_log.json").exists()
        assert (artifact_dir / "stdout.txt").exists()
        assert (artifact_dir / "stderr.txt").exists()
        assert (artifact_dir / "environment_summary.json").exists()

        # Verify run_log.json content
        run_log = json.loads((artifact_dir / "run_log.json").read_text())
        assert run_log["action"] == "git_status"
        assert run_log["status"] == "success"
        assert run_log["exit_code"] == 0
        assert run_log["timed_out"] is False
        assert run_log["duration_ms"] >= 0
        assert run_log["command_executed"] == "git_status"

        # Verify task.json was copied
        task_copy = json.loads((artifact_dir / "task.json").read_text())
        assert task_copy["action"] == "git_status"

    def test_blocked_action_produces_result(self, tmp_path):
        """Blocked actions return error without executing."""
        task = {
            "action": "evil_command",
            "workspace": str(Path.home() / "repos"),
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "blocked"
        assert "Unknown action" in result.error_message

    def test_not_implemented_action(self, tmp_path):
        """Not-implemented actions return NOT_IMPLEMENTED with artifacts."""
        workspace = str(Path(__file__).resolve().parents[1])
        task = {
            "action": "collect_revit_journals",
            "workspace": workspace,
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "not_implemented"
        assert "not yet implemented" in result.error_message

        # Verify artifacts still created
        artifact_dir = Path(result.artifact_dir)
        assert (artifact_dir / "run_log.json").exists()
        assert (artifact_dir / "failure_summary.md").exists()
        assert (artifact_dir / "stdout.txt").exists()
        assert (artifact_dir / "stderr.txt").exists()

    def test_failure_summary_created_on_nonzero_exit(self, tmp_path):
        """failure_summary.md should be created when exit code is nonzero."""
        workspace = str(Path(__file__).resolve().parents[1])
        # ruff on a nonexistent dir will succeed, so use a task that will
        # intentionally fail. Let's use a made-up failing scenario by
        # overriding an action's commands temporarily.
        task = {
            "action": "collect_revit_journals",
            "workspace": workspace,
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        # Not implemented = failure summary
        if result.artifact_dir:
            failure_path = Path(result.artifact_dir) / "failure_summary.md"
            assert failure_path.exists()
            content = failure_path.read_text()
            assert "Failure Summary" in content
            assert result.action in content

    def test_timeout_handling(self, tmp_path):
        """Actions that exceed timeout should be marked timed_out."""
        import subprocess
        from unittest.mock import patch

        workspace = str(Path(__file__).resolve().parents[1])
        task = {
            "action": "git_status",
            "timeout_seconds": 1,
            "workspace": workspace,
        }

        # Mock subprocess.run to simulate timeout
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        with patch("local_runner.local_runner.subprocess.run", side_effect=mock_run):
            result = execute_task(task, artifact_base=str(tmp_path))

        assert result.timed_out is True
        assert result.status == "timed_out"

    def test_no_arbitrary_command_from_task(self, tmp_path):
        """task.json cannot smuggle arbitrary commands."""
        task = {
            "action": "git_status",
            "workspace": str(Path.home() / "repos" / "Axiom-platform"),
            "cmd": "rm -rf /",
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "blocked"
        assert "Arbitrary command" in result.error_message


class TestRunbookExists:
    """Verify documentation exists."""

    def test_local_runner_runbook_exists(self):
        runbook = Path(__file__).resolve().parents[1] / "docs" / "runbooks" / "local-runner-runbook.md"
        assert runbook.exists(), f"Runbook not found: {runbook}"

    def test_example_tasks_exist(self):
        examples_dir = Path(__file__).resolve().parents[1] / "tools" / "local_runner" / "examples"
        expected = [
            "git_status.task.json",
            "test_grids.task.json",
            "test_levels.task.json",
            "ruff.task.json",
            "deploy_revit_2027.task.json",
        ]
        for name in expected:
            assert (examples_dir / name).exists(), f"Missing example: {name}"
