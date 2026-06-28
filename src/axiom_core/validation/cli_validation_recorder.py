"""CLI Validation Evidence Recorder v1 — durable proof of CLI validation runs.

Runs a small, explicit *validation plan* made of allowlisted Axiom CLI commands
and writes a durable evidence bundle (command inputs, outputs, exit codes,
timing, environment metadata, an artifact manifest, and a human-readable
report). The goal is to make validation proof repo/artifact-addressable instead
of relying on manual terminal copy/paste, screenshots, or external context.

Reuses, rather than duplicates, existing governance and safety:

* **Command governance** — every plan command is authorized against the Runner
  Command Registry (:mod:`axiom_core.runner.command_registry`). Only commands
  cataloged as ``SafetyLevel.SAFE`` and not requiring live Revit are allowed by
  default. Unknown / guarded / high-risk / mutation / live-Revit commands are
  refused. The recorder never executes arbitrary shell strings: it builds an
  explicit ``argv`` list (``poetry run axiom <name> <args...>``) and runs it
  without a shell, so there is no shell-injection surface.
* **Path safety** — bundle and artifact-existence checks go through
  :func:`axiom_core.artifact_paths.is_within_sandbox`, preserving traversal
  protection on both POSIX and Windows.

This is validation *evidence infrastructure*. It is not a new runner framework,
not a retry loop, not an implementation worker, and it does not mutate model
state, promote capabilities, or change confidence/readiness directly. Confidence
state only changes if a plan explicitly invokes an existing evidence-promotion
command (e.g. ``capability-evidence-apply``) as one of its steps.

Why not the existing :class:`~axiom_core.validation.evidence_runner.EvidenceRunner`?
That runner is keyed to a fixed ``SUPPORTED_VALIDATIONS`` set of in-process
executors (DiscoveryHarness / CommandRegistry / ValidationRegistry). It cannot
run an explicit, ordered plan of arbitrary allowlisted CLI commands (e.g.
``execution-chain-run`` then ``capability-evidence-apply``) via subprocess and
capture raw per-command stdout/stderr/exit/timing. This recorder fills that gap
while reusing the same command-registry governance and the same
``artifacts/validation_evidence`` root convention.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox
from axiom_core.runner import command_registry as cmdreg

DEFAULT_ARTIFACTS_ROOT = "artifacts"
EVIDENCE_SUBDIR = "validation_evidence"
DEFAULT_COMMAND_TIMEOUT = 120
DEFAULT_INVOCATION_PREFIX: tuple[str, ...] = ("poetry", "run", "axiom")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Plan format
# ---------------------------------------------------------------------------


class PlanError(ValueError):
    """Raised when a validation plan file is missing or malformed."""


@dataclass(frozen=True)
class PlanCommand:
    """One allowlisted CLI command in a validation plan."""

    id: str
    command: str
    args: tuple[str, ...] = ()
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT
    expected_exit_code: int = 0
    expect_stdout_contains: tuple[str, ...] = ()
    expect_stderr_contains: tuple[str, ...] = ()
    expect_artifact_exists: tuple[str, ...] = ()
    continue_on_failure: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "args": list(self.args),
            "timeout_seconds": self.timeout_seconds,
            "expected_exit_code": self.expected_exit_code,
            "expect_stdout_contains": list(self.expect_stdout_contains),
            "expect_stderr_contains": list(self.expect_stderr_contains),
            "expect_artifact_exists": list(self.expect_artifact_exists),
            "continue_on_failure": self.continue_on_failure,
        }


@dataclass(frozen=True)
class ValidationPlan:
    """An explicit, ordered validation plan. Deliberately not a workflow DSL."""

    plan_id: str
    title: str
    purpose: str
    commands: tuple[PlanCommand, ...]

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "purpose": self.purpose,
            "commands": [c.to_dict() for c in self.commands],
        }


def _require_str(data: dict, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{where}: missing or empty string field '{key}'")
    return value


def _coerce_str_list(value: object, where: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PlanError(f"{where}: field '{key}' must be a list of strings")
    return tuple(value)


def parse_plan(data: dict) -> ValidationPlan:
    """Validate and normalize a plan dict into a :class:`ValidationPlan`."""
    if not isinstance(data, dict):
        raise PlanError("Plan must be a JSON object")
    plan_id = _require_str(data, "plan_id", "plan")
    title = _require_str(data, "title", "plan")
    purpose = _require_str(data, "purpose", "plan")
    raw_commands = data.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        raise PlanError("plan: 'commands' must be a non-empty list")

    commands: list[PlanCommand] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_commands):
        where = f"commands[{index}]"
        if not isinstance(raw, dict):
            raise PlanError(f"{where}: must be an object")
        cmd_id = _require_str(raw, "id", where)
        if cmd_id in seen_ids:
            raise PlanError(f"{where}: duplicate command id '{cmd_id}'")
        seen_ids.add(cmd_id)
        command = _require_str(raw, "command", where)
        args = _coerce_str_list(raw.get("args"), where, "args")
        timeout_seconds = raw.get("timeout_seconds", DEFAULT_COMMAND_TIMEOUT)
        if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise PlanError(f"{where}: 'timeout_seconds' must be a positive int")
        expected_exit_code = raw.get("expected_exit_code", 0)
        if not isinstance(expected_exit_code, int):
            raise PlanError(f"{where}: 'expected_exit_code' must be an int")
        commands.append(
            PlanCommand(
                id=cmd_id,
                command=command,
                args=args,
                timeout_seconds=timeout_seconds,
                expected_exit_code=expected_exit_code,
                expect_stdout_contains=_coerce_str_list(
                    raw.get("expect_stdout_contains"), where, "expect_stdout_contains"
                ),
                expect_stderr_contains=_coerce_str_list(
                    raw.get("expect_stderr_contains"), where, "expect_stderr_contains"
                ),
                expect_artifact_exists=_coerce_str_list(
                    raw.get("expect_artifact_exists"), where, "expect_artifact_exists"
                ),
                continue_on_failure=bool(raw.get("continue_on_failure", False)),
            )
        )
    return ValidationPlan(
        plan_id=plan_id, title=title, purpose=purpose, commands=tuple(commands)
    )


def load_plan(plan_path: str | Path) -> ValidationPlan:
    """Load and validate a plan from a JSON file."""
    path = Path(plan_path)
    if not path.is_file():
        raise PlanError(f"Plan file not found: {plan_path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PlanError(f"Failed to read/parse plan file: {exc}") from exc
    return parse_plan(data)


# ---------------------------------------------------------------------------
# Command execution (thin, injectable for tests)
# ---------------------------------------------------------------------------


@dataclass
class CommandExecution:
    """Raw result of executing one command's argv."""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    completed_at: str
    duration_ms: int
    timed_out: bool


class CommandExecutor(Protocol):
    """Executes a resolved argv and captures output. Injectable for tests."""

    def execute(
        self, argv: list[str], *, cwd: str, timeout_seconds: int
    ) -> CommandExecution: ...


class SubprocessCommandExecutor:
    """Default executor: runs ``poetry run axiom <name> <args>`` without a shell."""

    def __init__(self, invocation_prefix: tuple[str, ...] = DEFAULT_INVOCATION_PREFIX):
        self.invocation_prefix = tuple(invocation_prefix)

    def execute(
        self, argv: list[str], *, cwd: str, timeout_seconds: int
    ) -> CommandExecution:
        full_argv = [*self.invocation_prefix, *argv]
        started = _now_iso()
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                full_argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = exc.stdout or "" if isinstance(exc.stdout, str) else ""
            stderr = (
                (exc.stderr if isinstance(exc.stderr, str) else "")
                + f"\nTIMEOUT: command exceeded {timeout_seconds}s"
            )
        except (FileNotFoundError, OSError) as exc:
            exit_code = -1
            stdout = ""
            stderr = f"Command execution error: {exc}"
        duration_ms = int((time.monotonic() - start) * 1000)
        return CommandExecution(
            argv=full_argv,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started,
            completed_at=_now_iso(),
            duration_ms=duration_ms,
            timed_out=timed_out,
        )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


class CommandStatus(str, Enum):
    """Per-command outcome within a recorded run."""

    PASSED = "passed"      # executed; all assertions satisfied
    FAILED = "failed"      # executed; an assertion failed or it timed out
    BLOCKED = "blocked"    # refused by governance; not executed
    SKIPPED = "skipped"    # not run because a prior command stopped the plan


class RunStatus(str, Enum):
    """Overall outcome of a recorded validation run."""

    PASSED = "passed"
    FAILED = "failed"


@dataclass
class AssertionResult:
    """One pass/fail check performed against a command's outcome."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class CommandRecord:
    """Full record of one command attempt within a recorded run."""

    seq: int
    id: str
    command: str
    status: CommandStatus
    argv: list[str] = field(default_factory=list)
    working_dir: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    exit_code: int | None = None
    timed_out: bool = False
    governance_reason: str = ""
    safety_level: str | None = None
    classification: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    assertions: list[AssertionResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status is CommandStatus.PASSED

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "id": self.id,
            "command": self.command,
            "status": self.status.value,
            "argv": self.argv,
            "working_dir": self.working_dir,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "governance_reason": self.governance_reason,
            "safety_level": self.safety_level,
            "classification": self.classification,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "assertions": [a.to_dict() for a in self.assertions],
            "assertions_passed": sum(1 for a in self.assertions if a.passed),
            "assertions_total": len(self.assertions),
        }


@dataclass
class RecorderRunResult:
    """Top-level record of a recorded validation run (also serialized)."""

    run_id: str
    plan_id: str
    name: str
    status: RunStatus
    started_at: str
    finished_at: str
    bundle_dir: str
    commands: list[CommandRecord] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status is RunStatus.PASSED

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "name": self.name,
            "status": self.status.value,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "bundle_dir": self.bundle_dir,
            "commands_total": len(self.commands),
            "commands_passed": sum(1 for c in self.commands if c.passed),
            "commands_failed": sum(
                1 for c in self.commands if c.status is CommandStatus.FAILED
            ),
            "commands_blocked": sum(
                1 for c in self.commands if c.status is CommandStatus.BLOCKED
            ),
            "commands_skipped": sum(
                1 for c in self.commands if c.status is CommandStatus.SKIPPED
            ),
            "commands": [c.to_dict() for c in self.commands],
        }


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GovernanceDecision:
    allowed: bool
    reason: str
    safety_level: str | None = None
    classification: str | None = None


def authorize_command(command_name: str) -> GovernanceDecision:
    """Authorize a plan command against the Runner Command Registry.

    Allowed only if the command is cataloged, classified ``SafetyLevel.SAFE``,
    and does not require live Revit. Everything else is refused by default —
    unknown, guarded, high-risk, mutation, or live-Revit commands.
    """
    spec = cmdreg.get_command(command_name)
    if spec is None:
        return GovernanceDecision(
            allowed=False,
            reason=(
                f"Command '{command_name}' is not in the Runner Command Registry; "
                "denied by default."
            ),
        )
    safety = spec.safety_level.value
    classification = spec.classification.value
    if spec.requires_revit:
        return GovernanceDecision(
            False,
            f"Command '{command_name}' requires live Revit; refused by default.",
            safety,
            classification,
        )
    if spec.safety_level is not cmdreg.SafetyLevel.SAFE:
        return GovernanceDecision(
            False,
            (
                f"Command '{command_name}' is classified '{safety}' "
                f"(not 'safe'); refused by default."
            ),
            safety,
            classification,
        )
    return GovernanceDecision(True, "allowed", safety, classification)


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


def _environment_summary() -> dict:
    """Collect safe, non-secret environment metadata for the bundle."""
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "cwd": str(Path.cwd()),
        "path_separator": os.sep,
        "captured_at": _now_iso(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _substitute(value: str, variables: dict[str, str]) -> str:
    out = value
    for key, replacement in variables.items():
        out = out.replace("${" + key + "}", replacement)
    return out


class CliValidationRecorder:
    """Runs a validation plan of allowlisted CLI commands and writes a bundle."""

    def __init__(
        self,
        *,
        artifacts_root: str | Path | None = None,
        executor: CommandExecutor | None = None,
        repo_root: str | Path | None = None,
    ):
        self.artifacts_root = Path(
            artifacts_root if artifacts_root is not None else DEFAULT_ARTIFACTS_ROOT
        ).resolve()
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd()
        self.executor: CommandExecutor = executor or SubprocessCommandExecutor()

    # -- planning helpers --------------------------------------------------

    def resolve_argv(
        self, command: PlanCommand, *, run_dir: Path, extra_vars: dict[str, str]
    ) -> list[str]:
        """Build the argv (command name + substituted args) for a plan command."""
        variables = {
            "artifacts_root": str(self.artifacts_root),
            "run_dir": str(run_dir),
            "repo_root": str(self.repo_root),
            **extra_vars,
        }
        args = [_substitute(arg, variables) for arg in command.args]
        return [command.command, *args]

    def dry_run(
        self, plan: ValidationPlan, *, extra_vars: dict[str, str] | None = None
    ) -> dict:
        """Validate governance and resolve commands without executing anything."""
        extra = extra_vars or {}
        placeholder = self.artifacts_root / EVIDENCE_SUBDIR / "<run_id>"
        resolved = []
        for seq, command in enumerate(plan.commands, start=1):
            decision = authorize_command(command.command)
            resolved.append(
                {
                    "seq": seq,
                    "id": command.id,
                    "command": command.command,
                    "argv": self.resolve_argv(
                        command, run_dir=placeholder, extra_vars=extra
                    ),
                    "allowed": decision.allowed,
                    "governance_reason": decision.reason,
                    "safety_level": decision.safety_level,
                    "classification": decision.classification,
                }
            )
        return {
            "plan_id": plan.plan_id,
            "title": plan.title,
            "purpose": plan.purpose,
            "artifacts_root": str(self.artifacts_root),
            "all_allowed": all(r["allowed"] for r in resolved),
            "commands": resolved,
        }

    # -- execution ---------------------------------------------------------

    def record(
        self,
        plan: ValidationPlan,
        *,
        name: str | None = None,
        extra_vars: dict[str, str] | None = None,
    ) -> RecorderRunResult:
        """Execute the plan and write a durable evidence bundle."""
        extra = extra_vars or {}
        started = _now_iso()
        run_id = "clivr_" + datetime.now(timezone.utc).strftime(
            "%Y%m%d_%H%M%S_"
        ) + uuid4().hex[:6]
        evidence_base = self.artifacts_root / EVIDENCE_SUBDIR
        bundle_dir = evidence_base / run_id
        # Path safety: the bundle must resolve under the artifacts root.
        if not is_within_sandbox(bundle_dir, self.artifacts_root):
            raise PlanError(
                "Resolved bundle directory escapes the artifacts root: "
                f"{bundle_dir}"
            )
        commands_dir = bundle_dir / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)

        records: list[CommandRecord] = []
        stop = False
        for seq, command in enumerate(plan.commands, start=1):
            if stop:
                records.append(
                    CommandRecord(
                        seq=seq,
                        id=command.id,
                        command=command.command,
                        status=CommandStatus.SKIPPED,
                        governance_reason="Skipped: a prior command stopped the run.",
                    )
                )
                continue
            record = self._run_one(
                command,
                seq=seq,
                run_dir=bundle_dir,
                commands_dir=commands_dir,
                extra_vars=extra,
            )
            records.append(record)
            if not record.passed and not command.continue_on_failure:
                stop = True

        status = (
            RunStatus.PASSED
            if records and all(r.passed for r in records)
            else RunStatus.FAILED
        )
        result = RecorderRunResult(
            run_id=run_id,
            plan_id=plan.plan_id,
            name=name or plan.plan_id,
            status=status,
            started_at=started,
            finished_at=_now_iso(),
            bundle_dir=str(bundle_dir),
            commands=records,
        )
        self._write_bundle(bundle_dir, plan, result, name=name)
        return result

    def _run_one(
        self,
        command: PlanCommand,
        *,
        seq: int,
        run_dir: Path,
        commands_dir: Path,
        extra_vars: dict[str, str],
    ) -> CommandRecord:
        decision = authorize_command(command.command)
        if not decision.allowed:
            return CommandRecord(
                seq=seq,
                id=command.id,
                command=command.command,
                status=CommandStatus.BLOCKED,
                governance_reason=decision.reason,
                safety_level=decision.safety_level,
                classification=decision.classification,
            )

        argv = self.resolve_argv(command, run_dir=run_dir, extra_vars=extra_vars)
        execution = self.executor.execute(
            argv, cwd=str(self.repo_root), timeout_seconds=command.timeout_seconds
        )

        stem = f"{seq:02d}_{command.id}"
        stdout_path = commands_dir / f"{stem}.stdout.txt"
        stderr_path = commands_dir / f"{stem}.stderr.txt"
        stdout_path.write_text(execution.stdout, encoding="utf-8")
        stderr_path.write_text(execution.stderr, encoding="utf-8")

        assertions = self._evaluate_assertions(command, execution)
        all_passed = not execution.timed_out and all(a.passed for a in assertions)
        return CommandRecord(
            seq=seq,
            id=command.id,
            command=command.command,
            status=CommandStatus.PASSED if all_passed else CommandStatus.FAILED,
            argv=execution.argv,
            working_dir=str(self.repo_root),
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            duration_ms=execution.duration_ms,
            exit_code=execution.exit_code,
            timed_out=execution.timed_out,
            governance_reason=decision.reason,
            safety_level=decision.safety_level,
            classification=decision.classification,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            assertions=assertions,
        )

    def _evaluate_assertions(
        self, command: PlanCommand, execution: CommandExecution
    ) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        if execution.timed_out:
            results.append(
                AssertionResult(
                    "did_not_time_out",
                    False,
                    f"command timed out after {command.timeout_seconds}s",
                )
            )
        results.append(
            AssertionResult(
                "exit_code",
                execution.exit_code == command.expected_exit_code,
                f"expected {command.expected_exit_code}, got {execution.exit_code}",
            )
        )
        for needle in command.expect_stdout_contains:
            results.append(
                AssertionResult(
                    f"stdout_contains:{needle}",
                    needle in execution.stdout,
                    "" if needle in execution.stdout else "substring not found",
                )
            )
        for needle in command.expect_stderr_contains:
            results.append(
                AssertionResult(
                    f"stderr_contains:{needle}",
                    needle in execution.stderr,
                    "" if needle in execution.stderr else "substring not found",
                )
            )
        for rel in command.expect_artifact_exists:
            results.append(self._artifact_exists_assertion(rel))
        return results

    def _artifact_exists_assertion(self, rel: str) -> AssertionResult:
        """Check an expected artifact exists, rejecting traversal outside root."""
        candidate = Path(rel)
        target = candidate if candidate.is_absolute() else self.artifacts_root / candidate
        target = target.resolve()
        if not is_within_sandbox(target, self.artifacts_root):
            return AssertionResult(
                f"artifact_exists:{rel}",
                False,
                "path escapes the artifacts root; rejected",
            )
        return AssertionResult(
            f"artifact_exists:{rel}",
            target.exists(),
            "" if target.exists() else "artifact not found",
        )

    # -- bundle writing ----------------------------------------------------

    def _write_bundle(
        self,
        bundle_dir: Path,
        plan: ValidationPlan,
        result: RecorderRunResult,
        *,
        name: str | None,
    ) -> None:
        (bundle_dir / "plan_snapshot.json").write_text(
            json.dumps(plan.to_dict(), indent=2), encoding="utf-8"
        )
        (bundle_dir / "validation_run.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )
        (bundle_dir / "commands.json").write_text(
            json.dumps([c.to_dict() for c in result.commands], indent=2),
            encoding="utf-8",
        )
        (bundle_dir / "environment.json").write_text(
            json.dumps(_environment_summary(), indent=2), encoding="utf-8"
        )
        assertion_payload = [
            {
                "command_id": c.id,
                "command": c.command,
                "status": c.status.value,
                "assertions": [a.to_dict() for a in c.assertions],
            }
            for c in result.commands
        ]
        (bundle_dir / "assertion_results.json").write_text(
            json.dumps(assertion_payload, indent=2), encoding="utf-8"
        )
        (bundle_dir / "report.md").write_text(
            self._render_report(plan, result, name=name), encoding="utf-8"
        )
        self._write_manifest(bundle_dir)

    def _write_manifest(self, bundle_dir: Path) -> None:
        entries = []
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file() and path.name != "artifact_manifest.json":
                rel = path.relative_to(bundle_dir).as_posix()
                entries.append(
                    {
                        "path": rel,
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
        manifest = {
            "bundle_dir": str(bundle_dir),
            "generated_at": _now_iso(),
            "file_count": len(entries),
            "files": entries,
        }
        (bundle_dir / "artifact_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _render_report(
        plan: ValidationPlan, result: RecorderRunResult, *, name: str | None
    ) -> str:
        lines = [
            f"# CLI Validation Evidence — {name or plan.plan_id}",
            "",
            f"- **Plan:** {plan.plan_id} — {plan.title}",
            f"- **Purpose:** {plan.purpose}",
            f"- **Run id:** {result.run_id}",
            f"- **Status:** {result.status.value.upper()}",
            f"- **Started:** {result.started_at}",
            f"- **Finished:** {result.finished_at}",
            "",
            "## Commands",
            "",
            "| # | Command | Status | Exit | Duration (ms) | Assertions |",
            "| - | ------- | ------ | ---- | ------------- | ---------- |",
        ]
        for c in result.commands:
            passed = sum(1 for a in c.assertions if a.passed)
            total = len(c.assertions)
            exit_display = "-" if c.exit_code is None else str(c.exit_code)
            lines.append(
                f"| {c.seq} | `{c.command}` | {c.status.value} | {exit_display} | "
                f"{c.duration_ms} | {passed}/{total} |"
            )
        lines.append("")
        # Surface any failures explicitly so the report is self-contained.
        failures = [
            c
            for c in result.commands
            if c.status in (CommandStatus.FAILED, CommandStatus.BLOCKED)
        ]
        if failures:
            lines.append("## Failures / Blocked")
            lines.append("")
            for c in failures:
                lines.append(f"### {c.seq}. `{c.command}` ({c.status.value})")
                if c.governance_reason and c.status is CommandStatus.BLOCKED:
                    lines.append(f"- Governance: {c.governance_reason}")
                for a in c.assertions:
                    if not a.passed:
                        lines.append(f"- FAILED `{a.name}`: {a.detail}")
                if c.stderr_path:
                    lines.append(f"- See `{Path(c.stderr_path).name}` for stderr.")
                lines.append("")
        return "\n".join(lines)

