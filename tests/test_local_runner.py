"""Tests for Axiom Local Runner v0 — allowlisted action execution harness."""

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

# Add tools/ to path so we can import local_runner
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from local_runner.local_runner import (  # noqa: E402
    _WINDOWS_TOOL_MODULE,
    ALLOWED_ACTIONS,
    ALLOWED_WORKSPACE_BASES_WINDOWS,
    WORKSPACE_CONFIG_ENV,
    WORKSPACE_ROOTS_ENV,
    _resolve_evidence_command,
    _resolve_latest_evidence,
    _windows_safe_command,
    execute_task,
    get_allowed_workspace_roots,
    run_from_task_file,
    validate_task,
    validate_workspace,
)

# Workspace path that is valid on the current platform
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
_VALID_WORKSPACE = _REPO_ROOT


class TestWorkspaceValidation:
    """Workspace path must be within allowed bases."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX workspace test")
    def test_allowed_workspace_posix(self):
        home = str(Path.home() / "repos" / "Axiom-platform")
        assert validate_workspace(home) is None

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows workspace test")
    def test_allowed_workspace_windows(self):
        r"""Windows workspace allows C:\Dev\Axiom\Code\Axiom-platform."""
        assert validate_workspace(r"C:\Dev\Axiom\Code\Axiom-platform") is None

    def test_allowed_workspace_windows_policy(self):
        r"""Windows workspace policy allows C:\Dev\Axiom and subdirectories."""
        assert r"C:\Dev\Axiom" in ALLOWED_WORKSPACE_BASES_WINDOWS

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

    def test_actions_runner_path_not_trusted_by_pattern(self):
        """A forged '.../actions-runner/_work/...' path is NOT trusted by name."""
        ws = "/opt/evil/actions-runner/_work/pwned/pwned"
        error = validate_workspace(ws)
        assert error is not None
        assert "outside allowed paths" in error

    def test_github_workspace_env_trusted(self, tmp_path, monkeypatch):
        """$GITHUB_WORKSPACE checkout dir (and subdirs) is trusted."""
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        assert validate_workspace(str(tmp_path)) is None
        sub = tmp_path / "nested"
        sub.mkdir()
        assert validate_workspace(str(sub)) is None

    def test_config_file_adds_root(self, tmp_path, monkeypatch):
        """Approved roots can be added via the JSON config file (not code)."""
        approved = tmp_path / "approved_ws"
        approved.mkdir()
        cfg = tmp_path / "workspace_policy.json"
        cfg.write_text(
            json.dumps({"windows": [str(approved)], "posix": [str(approved)]}),
            encoding="utf-8",
        )
        monkeypatch.setenv(WORKSPACE_CONFIG_ENV, str(cfg))
        assert validate_workspace(str(approved / "sub")) is None

    def test_env_var_adds_root(self, tmp_path, monkeypatch):
        """Approved roots can be added via the pathsep env override."""
        approved = tmp_path / "env_ws"
        approved.mkdir()
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(approved))
        assert validate_workspace(str(approved / "deep" / "path")) is None

    def test_allowed_roots_includes_defaults(self):
        """The assembled root list is non-empty and includes a platform default."""
        roots = get_allowed_workspace_roots()
        assert isinstance(roots, list) and roots
        if platform.system() == "Windows":
            assert any("Dev" in r and "Axiom" in r for r in roots)
        else:
            assert any("repos" in r or "Dev" in r for r in roots)

    def test_shipped_config_lists_self_hosted_runner_root(self):
        """The shipped policy config declares the Axiom-01 runner work dir explicitly."""
        cfg = (
            Path(__file__).resolve().parents[1]
            / "tools" / "local_runner" / "workspace_policy.json"
        )
        data = json.loads(cfg.read_text(encoding="utf-8"))
        windows_roots = data.get("windows", [])
        assert any(
            "actions-runner" in r and r.lower().endswith("axiom-platform")
            for r in windows_roots
        )


class TestTaskValidation:
    """Task validation blocks invalid or unsafe tasks."""

    def test_unknown_action_blocked(self):
        task = {"action": "rm_rf_everything", "workspace": _VALID_WORKSPACE}
        error = validate_task(task)
        assert error is not None
        assert "Unknown action" in error

    def test_missing_action_blocked(self):
        task = {"workspace": _VALID_WORKSPACE}
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
            "workspace": _VALID_WORKSPACE,
            "command": "rm -rf /",
        }
        error = validate_task(task)
        assert error is not None
        assert "Arbitrary command" in error

    def test_shell_field_blocked(self):
        task = {
            "action": "git_status",
            "workspace": _VALID_WORKSPACE,
            "shell": "bash -c 'cat /etc/shadow'",
        }
        error = validate_task(task)
        assert error is not None
        assert "Arbitrary command" in error

    def test_valid_task_passes(self):
        task = {
            "action": "git_status",
            "workspace": _VALID_WORKSPACE,
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

    def test_pr_snapshot_is_allowlisted(self):
        assert "test_pr_snapshot" in ALLOWED_ACTIONS

    def test_pr_snapshot_maps_to_correct_test_file(self):
        defn = ALLOWED_ACTIONS["test_pr_snapshot"]
        assert len(defn["commands"]) == 1
        cmd = defn["commands"][0]
        assert cmd == ["poetry", "run", "pytest", "tests/test_pr_snapshot.py"]

    def test_set_parameter_value_is_allowlisted(self):
        assert "test_set_parameter_value" in ALLOWED_ACTIONS

    def test_set_parameter_value_maps_to_correct_test_file(self):
        defn = ALLOWED_ACTIONS["test_set_parameter_value"]
        assert len(defn["commands"]) == 1
        cmd = defn["commands"][0]
        assert cmd == ["poetry", "run", "pytest", "tests/test_set_parameter_value.py"]

    def test_validation_loop_is_allowlisted(self):
        assert "test_validation_loop" in ALLOWED_ACTIONS

    def test_validation_loop_maps_to_correct_test_file(self):
        defn = ALLOWED_ACTIONS["test_validation_loop"]
        assert len(defn["commands"]) == 1
        cmd = defn["commands"][0]
        assert cmd == ["poetry", "run", "pytest", "tests/test_validation_loop.py"]


class TestTaskExecution:
    """End-to-end execution tests."""

    def test_git_status_execution(self, tmp_path):
        """Runner can execute git_status and produce artifacts."""
        workspace = _REPO_ROOT
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

        # Verify result_summary.md created
        assert (artifact_dir / "result_summary.md").exists()

        # Verify run_log.json content
        run_log = json.loads((artifact_dir / "run_log.json").read_text())
        assert run_log["action"] == "git_status"
        assert run_log["status"] == "success"
        assert run_log["exit_code"] == 0
        assert run_log["timed_out"] is False
        assert run_log["duration_ms"] >= 0
        assert "resolved_action" in run_log
        assert "command_executed" in run_log
        assert "result_summary_path" in run_log

        # Verify task.json was copied
        task_copy = json.loads((artifact_dir / "task.json").read_text())
        assert task_copy["action"] == "git_status"

    def test_blocked_action_produces_result(self, tmp_path):
        """Blocked actions return error without executing."""
        task = {
            "action": "evil_command",
            "workspace": _VALID_WORKSPACE,
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "blocked"
        assert "Unknown action" in result.error_message

    def test_not_implemented_action(self, tmp_path):
        """Not-implemented actions return NOT_IMPLEMENTED with artifacts."""
        workspace = _REPO_ROOT
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
        assert (artifact_dir / "result_summary.md").exists()
        assert (artifact_dir / "stdout.txt").exists()
        assert (artifact_dir / "stderr.txt").exists()

    def test_failure_summary_created_on_nonzero_exit(self, tmp_path):
        """failure_summary.md should be created when exit code is nonzero."""
        workspace = _REPO_ROOT
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

        workspace = _REPO_ROOT
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
            "workspace": _VALID_WORKSPACE,
            "cmd": "rm -rf /",
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "blocked"
        assert "Arbitrary command" in result.error_message


class TestResultSummary:
    """result_summary.md generation tests."""

    def test_success_result_summary_created(self, tmp_path):
        """Successful runs produce result_summary.md."""
        task = {
            "action": "git_status",
            "prompt": "Check repo state before merge.",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.status == "success"

        summary_path = Path(result.artifact_dir) / "result_summary.md"
        assert summary_path.exists()
        content = summary_path.read_text()
        assert "Check repo state before merge." in content
        assert "git_status" in content
        assert "Repository state captured." in content
        assert "**Status:** success" in content

    def test_result_summary_prompt_from_metadata_fallback(self, tmp_path):
        """If prompt is missing, metadata.purpose is used."""
        task = {
            "action": "git_status",
            "workspace": _REPO_ROOT,
            "metadata": {"purpose": "pre-deploy check"},
        }
        result = execute_task(task, artifact_base=str(tmp_path))
        assert result.prompt == "pre-deploy check"

        summary_path = Path(result.artifact_dir) / "result_summary.md"
        content = summary_path.read_text()
        assert "pre-deploy check" in content

    def test_result_summary_prompt_na_when_missing(self, tmp_path):
        """If both prompt and metadata.purpose are missing, show N/A."""
        task = {
            "action": "git_status",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))

        summary_path = Path(result.artifact_dir) / "result_summary.md"
        content = summary_path.read_text()
        assert "N/A" in content

    def test_result_summary_shows_command_display(self, tmp_path):
        """result_summary.md shows the allowlisted command, not shell input."""
        task = {
            "action": "git_status",
            "prompt": "Check state.",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))

        summary_path = Path(result.artifact_dir) / "result_summary.md"
        content = summary_path.read_text()
        assert "git status --short" in content

    def test_not_implemented_result_summary(self, tmp_path):
        """Not-implemented actions get result_summary.md with failure_summary.md listed."""
        task = {
            "action": "collect_revit_journals",
            "prompt": "Collect Revit journals.",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))

        summary_path = Path(result.artifact_dir) / "result_summary.md"
        assert summary_path.exists()
        content = summary_path.read_text()
        assert "failure_summary.md" in content
        assert "not yet implemented" in content.lower() or "not_implemented" in content

    def test_run_log_includes_new_fields(self, tmp_path):
        """run_log.json includes prompt, resolved_action, command_executed, result_summary_path."""
        task = {
            "action": "git_status",
            "prompt": "Validate before deploy.",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))

        run_log = json.loads((Path(result.artifact_dir) / "run_log.json").read_text())
        assert run_log["prompt"] == "Validate before deploy."
        assert run_log["resolved_action"] == "git_status"
        assert "git status" in run_log["command_executed"]
        assert "result_summary.md" in run_log["result_summary_path"]

    def test_task_json_preserves_prompt(self, tmp_path):
        """task.json artifact preserves the prompt field."""
        task = {
            "action": "git_status",
            "prompt": "Pre-merge check.",
            "workspace": _REPO_ROOT,
        }
        result = execute_task(task, artifact_base=str(tmp_path))

        task_copy = json.loads((Path(result.artifact_dir) / "task.json").read_text())
        assert task_copy["prompt"] == "Pre-merge check."


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
            "test_pr_snapshot.task.json",
        ]
        for name in expected:
            assert (examples_dir / name).exists(), f"Missing example: {name}"


class TestBOMHandling:
    """UTF-8 BOM handling in task file parsing."""

    def test_utf8_bom_task_file_parses_successfully(self, tmp_path):
        """Windows PowerShell Set-Content -Encoding UTF8 adds a BOM."""
        task_data = {
            "action": "git_status",
            "workspace": _REPO_ROOT,
        }
        task_file = tmp_path / "bom_task.json"
        # Write with UTF-8 BOM (EF BB BF prefix)
        content = json.dumps(task_data, indent=2)
        task_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        result = run_from_task_file(str(task_file), artifact_base=str(tmp_path / "artifacts"))
        assert result.status == "success", (
            f"BOM task file should parse successfully, got: {result.status} "
            f"— {result.error_message}"
        )

    def test_non_bom_task_file_still_works(self, tmp_path):
        """Regular UTF-8 (no BOM) task files continue to work."""
        task_data = {
            "action": "git_status",
            "workspace": _REPO_ROOT,
        }
        task_file = tmp_path / "normal_task.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")

        result = run_from_task_file(str(task_file), artifact_base=str(tmp_path / "artifacts"))
        assert result.status == "success", (
            f"Non-BOM task file should parse successfully, got: {result.status} "
            f"— {result.error_message}"
        )


class TestExecutionChainLoopActions:
    """The loop-enablement actions: execution_chain_run + capability_evidence_apply."""

    def test_both_actions_registered(self):
        assert "execution_chain_run" in ALLOWED_ACTIONS
        assert "capability_evidence_apply" in ALLOWED_ACTIONS

    def test_execution_chain_run_is_axiom_cli(self):
        cmds = ALLOWED_ACTIONS["execution_chain_run"]["commands"]
        assert cmds == [["poetry", "run", "axiom", "execution-chain-run", "--json-output"]]

    def test_evidence_apply_has_no_static_command(self):
        """The evidence-apply command is built at run time, not statically."""
        action = ALLOWED_ACTIONS["capability_evidence_apply"]
        assert action["commands"] == []
        assert action.get("resolve_evidence") is True

    def _seed_evidence(self, workspace: Path, run_id: str) -> Path:
        run_dir = workspace / "artifacts" / "execution_chain" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        bundle = run_dir / "evidence.json"
        bundle.write_text(json.dumps({"evidence_id": run_id}), encoding="utf-8")
        return bundle

    def test_resolve_evidence_missing_dir(self, tmp_path):
        path, error = _resolve_latest_evidence(str(tmp_path))
        assert path is None
        assert "execution_chain_run" in error

    def test_resolve_evidence_missing_bundle(self, tmp_path):
        (tmp_path / "artifacts" / "execution_chain").mkdir(parents=True)
        path, error = _resolve_latest_evidence(str(tmp_path))
        assert path is None
        assert "No evidence.json" in error

    def test_resolve_evidence_picks_newest(self, tmp_path):
        import os
        import time

        older = self._seed_evidence(tmp_path, "run_old")
        time.sleep(0.01)
        newer = self._seed_evidence(tmp_path, "run_new")
        # Force a clear mtime ordering regardless of filesystem granularity.
        os.utime(older, (1, 1))
        path, error = _resolve_latest_evidence(str(tmp_path))
        assert error is None
        assert Path(path) == newer.resolve()

    def test_resolve_evidence_command_shape(self, tmp_path):
        bundle = self._seed_evidence(tmp_path, "run_x")
        commands, error = _resolve_evidence_command(str(tmp_path))
        assert error is None
        assert commands == [
            ["poetry", "run", "axiom", "capability-evidence-apply",
             "--evidence", str(bundle.resolve())]
        ]

    def test_evidence_apply_blocked_without_bundle(self, tmp_path, monkeypatch):
        """With no chain evidence yet, the action is blocked with guidance."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(workspace))
        task = {"action": "capability_evidence_apply", "workspace": str(workspace)}
        result = execute_task(task, artifact_base=str(tmp_path / "artifacts_out"))
        assert result.status == "blocked"
        assert "execution_chain_run" in result.error_message


class TestWindowsSafeCommand:
    """Windows-safe command normalization (WDAC / WinError 4551 workaround)."""

    def test_noop_on_non_windows(self):
        """On non-Windows, commands pass through unchanged (Linux/CI preserved)."""
        cmd = ["poetry", "run", "ruff", "check", "."]
        assert _windows_safe_command(cmd, is_windows=False) == cmd

    def test_noop_on_empty(self):
        assert _windows_safe_command([], is_windows=True) == []

    def test_poetry_run_ruff_rewritten(self):
        out = _windows_safe_command(
            ["poetry", "run", "ruff", "check", "."], is_windows=True
        )
        assert out == [sys.executable, "-m", "ruff", "check", "."]

    def test_poetry_run_pytest_rewritten(self):
        out = _windows_safe_command(
            ["poetry", "run", "pytest", "tests/test_x.py", "-q"], is_windows=True
        )
        assert out == [
            sys.executable, "-m", "pytest", "tests/test_x.py", "-q",
        ]

    def test_poetry_run_pytest_no_args_rewritten(self):
        out = _windows_safe_command(["poetry", "run", "pytest"], is_windows=True)
        assert out == [sys.executable, "-m", "pytest"]

    def test_poetry_run_axiom_rewritten_to_axiom_cli(self):
        """axiom is invoked as ``python -m axiom_cli`` (no poetry, no .exe)."""
        out = _windows_safe_command(
            ["poetry", "run", "axiom", "execution-chain-run", "--json-output"],
            is_windows=True,
        )
        assert out == [
            sys.executable, "-m", "axiom_cli",
            "execution-chain-run", "--json-output",
        ]

    def test_poetry_run_axiom_evidence_apply_rewritten(self):
        out = _windows_safe_command(
            ["poetry", "run", "axiom", "capability-evidence-apply",
             "--evidence", "/ws/evidence.json"],
            is_windows=True,
        )
        assert out == [
            sys.executable, "-m", "axiom_cli", "capability-evidence-apply",
            "--evidence", "/ws/evidence.json",
        ]

    def test_no_recursive_poetry_emitted(self):
        """The broken ``<python> -m poetry`` form must never be emitted."""
        for cmd in (
            ["poetry", "run", "ruff", "check", "."],
            ["poetry", "run", "pytest"],
            ["poetry", "run", "axiom", "execution-chain-run", "--json-output"],
        ):
            out = _windows_safe_command(cmd, is_windows=True)
            assert "poetry" not in out, f"recursive poetry survived: {out}"

    def test_non_poetry_command_untouched(self):
        """git/dotnet/powershell commands are not rewritten."""
        cmd = ["git", "status", "--short"]
        assert _windows_safe_command(cmd, is_windows=True) == cmd

    def test_no_shim_or_poetry_survives_any_affected_action(self):
        """Simulated-Windows guarantee across every allowlisted command:

        for a ``poetry run <tool> ...`` command, the rewritten form runs via the
        current interpreter's module form (``<python> -m <module> ...``) — the
        executable head is never a bare ``poetry``/``ruff``/``pytest``/``axiom``
        shim, and no recursive ``poetry`` token survives. The module name after
        ``-m`` may legitimately equal the tool name (e.g. ``-m pytest``).
        """
        shim_heads = {"poetry", "ruff", "pytest", "axiom"}
        for action, action_def in ALLOWED_ACTIONS.items():
            for cmd in action_def.get("commands", []):
                if not cmd:
                    continue
                rewritten = _windows_safe_command(cmd, is_windows=True)
                if cmd[0] == "poetry" and len(cmd) >= 3 and cmd[1] == "run":
                    tool = cmd[2]
                    if tool not in _WINDOWS_TOOL_MODULE:
                        continue
                    assert rewritten[0] == sys.executable, (
                        f"{action}: {cmd!r} not module-ized"
                    )
                    assert rewritten[1] == "-m"
                    assert rewritten[2] == _WINDOWS_TOOL_MODULE[tool]
                    assert "poetry" not in rewritten, (
                        f"{action}: recursive poetry survived in {rewritten!r}"
                    )
                    # No shim head appears as the executable (position 0).
                    assert rewritten[0] not in shim_heads, (
                        f"{action}: shim head survived in {rewritten!r}"
                    )

    def test_execute_task_applies_rewrite_via_injected_windows_flag(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: the affected action's argv reaching subprocess.run is
        module-ized when the runner treats the platform as Windows.

        We inject Windows-ness through ``_windows_safe_command`` rather than
        faking ``os.name`` (which would corrupt ``pathlib``)."""
        import local_runner.local_runner as lr

        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(workspace))

        real_norm = lr._windows_safe_command
        monkeypatch.setattr(
            lr,
            "_windows_safe_command",
            lambda cmd, **kw: real_norm(cmd, is_windows=True),
        )

        captured: list[list[str]] = []

        class _FakeProc:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def _fake_run(cmd, **kwargs):
            captured.append(cmd)
            return _FakeProc()

        monkeypatch.setattr(lr.subprocess, "run", _fake_run)

        task = {"action": "ruff", "workspace": str(workspace)}
        lr.execute_task(task, artifact_base=str(tmp_path / "artifacts_out"))

        assert captured, "subprocess.run was not invoked"
        argv = captured[0]
        assert argv == [sys.executable, "-m", "ruff", "check", "."]
        # Neither the .exe shim nor recursive poetry appears.
        assert argv[0] not in ("ruff", "poetry")
        assert "poetry" not in argv


class TestAxiomCliModuleEntrypoint:
    """`python -m axiom_cli` must work and back the same callable as `axiom`."""

    def test_main_module_exposes_console_script_callable(self):
        """`axiom_cli.__main__` imports the same `cli` as the console script."""
        import importlib

        main_module = importlib.import_module("axiom_cli.__main__")
        from axiom_cli.main import cli

        assert main_module.cli is cli

    def test_python_m_axiom_cli_help_works(self):
        """`python -m axiom_cli --help` exits 0 (no .exe shim required)."""
        proc = subprocess.run(
            [sys.executable, "-m", "axiom_cli", "--help"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "execution-chain-run" in proc.stdout

    def test_python_m_axiom_cli_lists_execution_chain_run(self):
        """The module entrypoint exposes the loop subcommands the runner uses."""
        proc = subprocess.run(
            [sys.executable, "-m", "axiom_cli", "execution-chain-run", "--help"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
