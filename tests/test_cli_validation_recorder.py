"""Tests for the CLI Validation Evidence Recorder.

The recorder runs an explicit plan of allowlisted CLI commands and writes a
durable evidence bundle. Real subprocesses are avoided by injecting a fake
``CommandExecutor`` so success/failure/timeout/governance paths are exercised
deterministically. Path-safety is also asserted against Windows-style shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.validation.cli_validation_recorder import (
    CliValidationRecorder,
    CommandExecution,
    CommandStatus,
    PlanCommand,
    PlanError,
    RunStatus,
    ValidationPlan,
    authorize_command,
    load_plan,
    parse_plan,
)

# ---------------------------------------------------------------------------
# Fake executor
# ---------------------------------------------------------------------------


class FakeExecutor:
    """Returns scripted executions keyed by command name; records calls."""

    def __init__(self, scripted: dict[str, CommandExecution]):
        self.scripted = scripted
        self.calls: list[list[str]] = []

    def execute(
        self, argv: list[str], *, cwd: str, timeout_seconds: int
    ) -> CommandExecution:
        self.calls.append(argv)
        name = argv[0]
        if name not in self.scripted:
            raise AssertionError(f"unexpected command executed: {name}")
        return self.scripted[name]


def _exec(
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    argv: list[str] | None = None,
) -> CommandExecution:
    return CommandExecution(
        argv=argv or ["execution-chain-run"],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        started_at="2024-01-01T00:00:00+00:00",
        completed_at="2024-01-01T00:00:01+00:00",
        duration_ms=1000,
        timed_out=timed_out,
    )


SAFE_CMD = "execution-chain-run"  # READ_ONLY / SAFE in the registry


def _plan(*commands: PlanCommand) -> ValidationPlan:
    return ValidationPlan(
        plan_id="p", title="t", purpose="u", commands=tuple(commands)
    )


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


class TestPlanParsing:
    def test_minimal_valid_plan(self):
        plan = parse_plan(
            {
                "plan_id": "demo",
                "title": "Demo",
                "purpose": "prove",
                "commands": [{"id": "a", "command": SAFE_CMD}],
            }
        )
        assert plan.plan_id == "demo"
        assert plan.commands[0].id == "a"
        assert plan.commands[0].expected_exit_code == 0

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"plan_id": "x"},
            {"plan_id": "x", "title": "t", "purpose": "p", "commands": []},
            {"plan_id": "x", "title": "t", "purpose": "p", "commands": "no"},
            {
                "plan_id": "x",
                "title": "t",
                "purpose": "p",
                "commands": [{"command": SAFE_CMD}],
            },
            {
                "plan_id": "x",
                "title": "t",
                "purpose": "p",
                "commands": [{"id": "a"}],
            },
        ],
    )
    def test_invalid_plans_rejected(self, data):
        with pytest.raises(PlanError):
            parse_plan(data)

    def test_duplicate_command_ids_rejected(self):
        with pytest.raises(PlanError):
            parse_plan(
                {
                    "plan_id": "x",
                    "title": "t",
                    "purpose": "p",
                    "commands": [
                        {"id": "a", "command": SAFE_CMD},
                        {"id": "a", "command": SAFE_CMD},
                    ],
                }
            )

    def test_bad_timeout_rejected(self):
        with pytest.raises(PlanError):
            parse_plan(
                {
                    "plan_id": "x",
                    "title": "t",
                    "purpose": "p",
                    "commands": [
                        {"id": "a", "command": SAFE_CMD, "timeout_seconds": 0}
                    ],
                }
            )

    def test_load_plan_roundtrip(self, tmp_path):
        payload = {
            "plan_id": "demo",
            "title": "Demo",
            "purpose": "prove",
            "commands": [{"id": "a", "command": SAFE_CMD, "args": ["--x", "y"]}],
        }
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(payload), encoding="utf-8")
        plan = load_plan(plan_file)
        assert plan.commands[0].args == ("--x", "y")

    def test_load_missing_file_raises_plan_error(self, tmp_path):
        with pytest.raises(PlanError):
            load_plan(tmp_path / "nope.json")

    def test_example_plans_parse(self):
        root = Path(__file__).resolve().parents[1] / "docs" / "validation_plans"
        for name in ("m4_execution_chain.json", "m2_evidence_promotion.json"):
            plan = load_plan(root / name)
            assert plan.commands


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


class TestGovernance:
    def test_safe_command_allowed(self):
        assert authorize_command(SAFE_CMD).allowed is True

    def test_unknown_command_denied(self):
        decision = authorize_command("rm-rf-everything")
        assert decision.allowed is False
        assert "not in the Runner Command Registry" in decision.reason


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_success_path_writes_full_bundle(self, tmp_path):
        executor = FakeExecutor(
            {SAFE_CMD: _exec(stdout="self-model-build ok", exit_code=0)}
        )
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(
                id="chain",
                command=SAFE_CMD,
                expect_stdout_contains=("self-model-build",),
            )
        )
        result = recorder.record(plan, name="m4")

        assert result.status is RunStatus.PASSED
        assert result.exit_code == 0
        bundle = Path(result.bundle_dir)
        for fname in (
            "validation_run.json",
            "commands.json",
            "environment.json",
            "artifact_manifest.json",
            "assertion_results.json",
            "plan_snapshot.json",
            "report.md",
        ):
            assert (bundle / fname).is_file(), fname
        assert (bundle / "commands" / "01_chain.stdout.txt").read_text() == (
            "self-model-build ok"
        )
        # Bundle is under <artifacts_root>/validation_evidence/<run_id>/
        assert bundle.parent.name == "validation_evidence"
        assert bundle.parent.parent == tmp_path.resolve()

    def test_manifest_lists_files_with_hashes(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec()})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        result = recorder.record(_plan(PlanCommand(id="c", command=SAFE_CMD)))
        manifest = json.loads(
            (Path(result.bundle_dir) / "artifact_manifest.json").read_text()
        )
        assert manifest["file_count"] == len(manifest["files"])
        assert all(len(f["sha256"]) == 64 for f in manifest["files"])

    def test_failed_assertion_marks_run_failed(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec(exit_code=2)})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(PlanCommand(id="c", command=SAFE_CMD, expected_exit_code=0))
        result = recorder.record(plan)
        assert result.status is RunStatus.FAILED
        assert result.exit_code == 1
        assert result.commands[0].status is CommandStatus.FAILED

    def test_timeout_is_failure(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec(exit_code=-1, timed_out=True)})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        result = recorder.record(_plan(PlanCommand(id="c", command=SAFE_CMD)))
        assert result.commands[0].status is CommandStatus.FAILED
        assert result.commands[0].timed_out is True

    def test_failure_stops_subsequent_commands(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec(exit_code=3)})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(id="first", command=SAFE_CMD),
            PlanCommand(id="second", command=SAFE_CMD),
        )
        result = recorder.record(plan)
        assert result.commands[0].status is CommandStatus.FAILED
        assert result.commands[1].status is CommandStatus.SKIPPED
        # Only the first command actually ran.
        assert len(executor.calls) == 1

    def test_continue_on_failure_runs_next(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec(exit_code=3)})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(id="first", command=SAFE_CMD, continue_on_failure=True),
            PlanCommand(id="second", command=SAFE_CMD),
        )
        result = recorder.record(plan)
        assert result.commands[1].status is CommandStatus.FAILED
        assert len(executor.calls) == 2

    def test_unsafe_command_blocked_not_executed(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec()})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(PlanCommand(id="bad", command="totally-not-allowed"))
        result = recorder.record(plan)
        assert result.commands[0].status is CommandStatus.BLOCKED
        assert result.status is RunStatus.FAILED
        assert executor.calls == []  # never executed

    def test_variable_substitution_in_args(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec()})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(
                id="c",
                command=SAFE_CMD,
                args=("--artifacts-root", "${run_dir}/chain", "--x", "${custom}"),
            )
        )
        recorder.record(plan, extra_vars={"custom": "VALUE"})
        argv = executor.calls[0]
        assert argv[0] == SAFE_CMD
        assert argv[-1] == "VALUE"
        assert any("chain" in a and "validation_evidence" in a for a in argv)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_execute(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec()})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(id="ok", command=SAFE_CMD),
            PlanCommand(id="bad", command="not-allowed"),
        )
        preview = recorder.dry_run(plan)
        assert executor.calls == []
        assert preview["all_allowed"] is False
        assert preview["commands"][0]["allowed"] is True
        assert preview["commands"][1]["allowed"] is False


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_artifact_exists_rejects_traversal(self, tmp_path):
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=FakeExecutor({}), repo_root=tmp_path
        )
        result = recorder._artifact_exists_assertion("../../etc/passwd")
        assert result.passed is False
        assert "escapes" in result.detail

    def test_artifact_exists_true_for_real_file(self, tmp_path):
        (tmp_path / "made.txt").write_text("x", encoding="utf-8")
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=FakeExecutor({}), repo_root=tmp_path
        )
        assert recorder._artifact_exists_assertion("made.txt").passed is True

    def test_artifact_exists_assertion_enforced_in_run(self, tmp_path):
        executor = FakeExecutor({SAFE_CMD: _exec()})
        recorder = CliValidationRecorder(
            artifacts_root=tmp_path, executor=executor, repo_root=tmp_path
        )
        plan = _plan(
            PlanCommand(
                id="c",
                command=SAFE_CMD,
                expect_artifact_exists=("does-not-exist.json",),
            )
        )
        result = recorder.record(plan)
        assert result.status is RunStatus.FAILED
