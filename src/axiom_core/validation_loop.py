"""Axiom Validation Automation Loop v0.

A semi-autonomous PR / live-validation runner that automates everything
*around* the single remaining human step (the live Revit interaction):

    record context -> record git state -> (optional) pull branch
    -> run Python tests -> run ruff -> build/deploy Revit 2027
    -> capture deployed DLL timestamps -> print manual Revit steps
    -> [human performs Revit steps] -> scan evidence across user profiles
    -> validate evidence conditions -> classify -> write result_summary.

Design notes
------------
- **No arbitrary shell execution.** Every subprocess is a fixed argv list
  built from a small allowlist (``ALLOWED_COMMANDS`` / scenario config).
  User-supplied strings (branch names, scenario ids) are validated against
  conservative patterns and are never interpolated into a shell string.
- **Pure logic is separated from I/O** so the scanner and classifier can be
  unit-tested without Revit, git, or a live filesystem layout.
- This is the *validation throughput* tool from the Autonomous Verification
  Loop spec. The bounded-retry / promotion-scoring *discovery* machinery is a
  separate, later target and is intentionally out of scope for v0.

Failure taxonomy (classification values):
    needs_admin, deploy_failed, tests_failed, revit_manual_step_pending,
    evidence_missing, evidence_mismatch, pass
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Classification constants
# ---------------------------------------------------------------------------

CLASS_PASS = "pass"
CLASS_NEEDS_ADMIN = "needs_admin"
CLASS_DEPLOY_FAILED = "deploy_failed"
CLASS_TESTS_FAILED = "tests_failed"
CLASS_REVIT_MANUAL_STEP_PENDING = "revit_manual_step_pending"
CLASS_EVIDENCE_MISSING = "evidence_missing"
CLASS_EVIDENCE_MISMATCH = "evidence_mismatch"

ALL_CLASSIFICATIONS = (
    CLASS_NEEDS_ADMIN,
    CLASS_DEPLOY_FAILED,
    CLASS_TESTS_FAILED,
    CLASS_REVIT_MANUAL_STEP_PENDING,
    CLASS_EVIDENCE_MISSING,
    CLASS_EVIDENCE_MISMATCH,
    CLASS_PASS,
)

# Conservative validation patterns for user-supplied values.
_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_SAFE_SCENARIO_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Bounded-retry budget (Autonomous Verification Loop spec section 6). This is the
# default number of attempts the loop makes when waiting for evidence to
# appear; it is overridable via the CLI (``--max-attempts``) so larger testing
# concepts can be confirmed without changing code.
DEFAULT_MAX_ATTEMPTS = 5

# ---------------------------------------------------------------------------
# Allowlisted commands (fixed argv; never a shell string)
# ---------------------------------------------------------------------------

# Test commands run during the "pre" phase. Each entry is a fixed argv list.
TEST_COMMANDS: dict[str, list[str]] = {
    "test_set_parameter_value": ["poetry", "run", "pytest", "tests/test_set_parameter_value.py"],
    "test_local_runner": ["poetry", "run", "pytest", "tests/test_local_runner.py"],
    "ruff": ["poetry", "run", "ruff", "check", "."],
}


def deploy_command(revit_version: str, force_close_revit: bool = True) -> list[str]:
    """Build the fixed deploy argv for a Revit version. No shell string."""
    script = f"scripts/deploy-revit-{revit_version}.ps1"
    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script]
    if force_close_revit:
        cmd.append("-ForceCloseRevit")
    return cmd


# DLL artifacts a deploy is expected to refresh, by Revit version.
DEPLOYED_DLLS = [
    "Axiom.RevitAddin.dll",
    "Axiom.Core.dll",
    "Newtonsoft.Json.dll",
    "Axiom.RevitAddin.addin",
]


def revit_addins_dir(revit_version: str) -> str:
    """Standard all-users add-in deployment directory for a Revit version."""
    return rf"C:\Program Files\Autodesk\Revit\Addins\{revit_version}"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class EvidenceCondition:
    """One declarative evidence condition for a scenario."""

    name: str
    kind: str  # "file" or "field"
    description: str


# Conditions for the v0 scenario, in spec order. ``kind`` drives whether a
# failure is classified as evidence_missing (file) or evidence_mismatch (field).
_WALL_COMMENTS_CONDITIONS = [
    EvidenceCondition("latest_apply_run_exists", "file", "Latest apply run folder exists"),
    EvidenceCondition("result_summary_md_exists", "file", "result_summary.md exists"),
    EvidenceCondition("request_json_exists", "file", "request.json exists"),
    EvidenceCondition("changes_json_exists", "file", "changes.json exists"),
    EvidenceCondition("linked_preview_json_exists", "file", "linked_preview.json exists"),
    EvidenceCondition(
        "linked_preview_metadata_json_exists", "file", "linked_preview_metadata.json exists"
    ),
    EvidenceCondition("initiated_from_preview_approval", "field", "initiated_from = preview_approval"),
    EvidenceCondition("targeted_by_ids_true", "field", "targeted_by_ids = true"),
    EvidenceCondition("target_ids_match_true", "field", "target_ids_match = true"),
    EvidenceCondition("model_modified_true", "field", "model_modified = true"),
    EvidenceCondition("changed_element_count_ge_1", "field", "changed element count >= 1"),
    EvidenceCondition("no_failed_elements", "field", "no failed elements"),
]

_WALL_COMMENTS_MANUAL_STEPS = [
    'Open Revit {revit_version} with a disposable/sample model that contains at least one Wall.',
    'In the Axiom prompt dialog, run the PREVIEW:',
    '    Set Comments to Axiom test 001 for 1 Walls',
    'Confirm: the wall is selected/zoomed, the dialog shows old/new values, and the model is NOT modified.',
    'Click "Apply changes to 1 element(s)" in the preview dialog (apply-from-preview).',
    'Confirm: exactly the previewed wall\'s Comments parameter is updated to "Axiom test 001".',
    'Close Revit (or leave open) - evidence has already been written by the add-in.',
    'Return here and run the scan phase:',
    '    poetry run axiom validation-run --scenario {scenario} --phase scan --run-id {run_id}',
]

SCENARIOS: dict[str, dict] = {
    "set_parameter_preview_apply_wall_comments": {
        "id": "set_parameter_preview_apply_wall_comments",
        "title": "SetParameterValue preview -> apply (Wall Comments)",
        "evidence_subdir": "parameter_edit_runs",
        "apply_run_glob": "spv_*",
        "conditions": _WALL_COMMENTS_CONDITIONS,
        "manual_steps": _WALL_COMMENTS_MANUAL_STEPS,
        "preview_prompt": "Set Comments to Axiom test 001 for 1 Walls",
    },
}

# Convenience alias used in the spec's example command.
SCENARIO_ALIASES = {
    "set_parameter_preview_apply": "set_parameter_preview_apply_wall_comments",
}


def resolve_scenario(name: str) -> dict | None:
    """Resolve a scenario id (or alias) to its config dict, or None."""
    if not name or not _SAFE_SCENARIO_RE.match(name):
        return None
    key = SCENARIO_ALIASES.get(name, name)
    return SCENARIOS.get(key)


# ---------------------------------------------------------------------------
# Context / environment
# ---------------------------------------------------------------------------


def detect_is_admin() -> bool:
    """Best-effort elevation detection (Windows admin / POSIX root)."""
    try:
        if platform.system() == "Windows":
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


def record_context() -> dict:
    """Record current user / admin / platform context."""
    return {
        "user": os.environ.get("USERNAME", os.environ.get("USER", "")),
        "is_admin": detect_is_admin(),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "hostname": platform.node(),
        "cwd": os.getcwd(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------


def _run_git(args: list[str], repo_root: str) -> tuple[int, str]:
    """Run a fixed git argv in repo_root. Returns (exit_code, combined_output)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # pragma: no cover - defensive
        return -1, str(exc)


def record_git_state(repo_root: str) -> dict:
    """Capture current branch, latest commit, and dirty state."""
    _, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    _, commit = _run_git(["rev-parse", "HEAD"], repo_root)
    _, subject = _run_git(["log", "-1", "--pretty=%s"], repo_root)
    status_code, status = _run_git(["status", "--porcelain"], repo_root)
    return {
        "repo_root": str(repo_root),
        "branch": branch.strip(),
        "commit": commit.strip(),
        "commit_subject": subject.strip(),
        "dirty": bool(status.strip()) if status_code == 0 else None,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def pull_branch(repo_root: str, branch: str) -> dict:
    """Fetch + checkout + fast-forward pull a branch. Safe argv only.

    Branch names are validated against a conservative pattern. This never
    force-pushes or resets; a non-fast-forward pull simply fails and is
    reported.
    """
    if not branch or not _SAFE_BRANCH_RE.match(branch):
        return {"attempted": True, "ok": False, "error": f"unsafe branch name: {branch!r}"}

    steps = []
    for args in (["fetch", "origin"], ["checkout", branch], ["pull", "--ff-only"]):
        code, out = _run_git(args, repo_root)
        steps.append({"args": args, "exit_code": code, "output": out.strip()[-2000:]})
        if code != 0:
            return {"attempted": True, "ok": False, "branch": branch, "steps": steps}
    return {"attempted": True, "ok": True, "branch": branch, "steps": steps}


# ---------------------------------------------------------------------------
# Subprocess helpers (tests / deploy)
# ---------------------------------------------------------------------------


def _run_argv(argv: list[str], cwd: str, timeout: int) -> dict:
    """Run a fixed argv list and capture results. Never uses shell=True."""
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "command": argv,
            "exit_code": proc.returncode,
            "timed_out": False,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": argv,
            "exit_code": -1,
            "timed_out": True,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "command": argv,
            "exit_code": -1,
            "timed_out": False,
            "stdout": "",
            "stderr": str(exc),
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }


_PYTEST_SUMMARY_RE = re.compile(r"(\d+ passed(?:, \d+ \w+)*)")


def parse_pytest_summary(stdout: str) -> str:
    """Extract a pytest summary line like '52 passed, 1 skipped'."""
    match = _PYTEST_SUMMARY_RE.search(stdout or "")
    return match.group(1) if match else ""


def run_tests(repo_root: str, timeout: int = 600) -> dict:
    """Run the allowlisted Python tests + ruff. Returns a structured result."""
    results = {}
    all_passed = True
    for name, argv in TEST_COMMANDS.items():
        res = _run_argv(argv, cwd=repo_root, timeout=timeout)
        passed = res["exit_code"] == 0 and not res["timed_out"]
        summary = parse_pytest_summary(res["stdout"]) if name != "ruff" else (
            "clean" if passed else "violations"
        )
        results[name] = {
            "command": res["command"],
            "exit_code": res["exit_code"],
            "timed_out": res["timed_out"],
            "passed": passed,
            "summary": summary,
            "stdout_tail": "\n".join(res["stdout"].splitlines()[-40:]),
            "stderr_tail": "\n".join(res["stderr"].splitlines()[-40:]),
        }
        all_passed = all_passed and passed
    return {"all_passed": all_passed, "results": results}


# Output signatures that indicate a deploy failed for lack of elevation.
_NEEDS_ADMIN_SIGNATURES = (
    "access to the path",
    "access is denied",
    "unauthorizedaccess",
    "is denied",
    "requested operation requires elevation",
)


def classify_deploy_output(exit_code: int, output: str) -> str:
    """Classify a deploy result: 'success' | 'needs_admin' | 'failed'."""
    if exit_code == 0:
        return "success"
    low = (output or "").lower()
    if any(sig in low for sig in _NEEDS_ADMIN_SIGNATURES):
        return "needs_admin"
    return "failed"


def run_deploy(repo_root: str, revit_version: str, timeout: int = 900) -> dict:
    """Build/deploy via the existing PowerShell deploy script (Windows only)."""
    if platform.system() != "Windows":
        return {
            "attempted": False,
            "status": "skipped",
            "reason": "not_windows",
            "command": deploy_command(revit_version),
        }
    argv = deploy_command(revit_version)
    res = _run_argv(argv, cwd=repo_root, timeout=timeout)
    combined = (res["stdout"] or "") + (res["stderr"] or "")
    status = "timed_out" if res["timed_out"] else classify_deploy_output(
        res["exit_code"], combined
    )
    return {
        "attempted": True,
        "status": status,
        "exit_code": res["exit_code"],
        "timed_out": res["timed_out"],
        "command": argv,
        "stdout_tail": "\n".join(res["stdout"].splitlines()[-60:]),
        "stderr_tail": "\n".join(res["stderr"].splitlines()[-60:]),
    }


def capture_dll_timestamps(revit_version: str) -> dict:
    """Capture LastWriteTime of deployed DLLs in the Revit add-ins folder."""
    target = revit_addins_dir(revit_version)
    if platform.system() != "Windows":
        return {"addins_dir": target, "applicable": False, "files": {}}
    files = {}
    for name in DEPLOYED_DLLS:
        p = Path(target) / name
        if p.exists():
            stat = p.stat()
            files[name] = {
                "exists": True,
                "last_write_time": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "size_bytes": stat.st_size,
            }
        else:
            files[name] = {"exists": False}
    return {"addins_dir": target, "applicable": True, "files": files}


# ---------------------------------------------------------------------------
# Evidence scanning
# ---------------------------------------------------------------------------


@dataclass
class EvidenceRun:
    """One discovered evidence run folder."""

    path: str
    name: str
    mtime: float
    has_changes_json: bool
    has_preview_json: bool


@dataclass
class EvidenceScan:
    """Result of scanning evidence directories across user profiles."""

    searched_dirs: list[str] = field(default_factory=list)
    runs: list[EvidenceRun] = field(default_factory=list)
    latest_run: EvidenceRun | None = None
    latest_apply_run: EvidenceRun | None = None


def default_evidence_dirs(scenario: dict) -> list[str]:
    """Build the default per-profile evidence directories for a scenario.

    On Windows, scans all user profiles to avoid LOCALAPPDATA confusion
    between e.g. an admin deploy account and the interactive user::

        C:\\Users\\*\\AppData\\Local\\Axiom\\<evidence_subdir>
    """
    subdir = scenario["evidence_subdir"]
    if platform.system() == "Windows":
        users_root = Path(os.environ.get("SystemDrive", "C:") + "\\Users")
        dirs = []
        if users_root.exists():
            for profile in users_root.iterdir():
                cand = profile / "AppData" / "Local" / "Axiom" / subdir
                if cand.exists():
                    dirs.append(str(cand))
        return dirs
    # Non-Windows fallback: local-app-data style path under HOME.
    cand = Path.home() / ".local" / "share" / "Axiom" / subdir
    return [str(cand)] if cand.exists() else []


def scan_evidence(evidence_dirs: list[str], run_glob: str = "spv_*") -> EvidenceScan:
    """Scan evidence directories for run folders; find latest + latest apply.

    ``evidence_dirs`` are directories that directly contain run folders
    (e.g. ``.../Axiom/parameter_edit_runs``). A run is an *apply* run when it
    contains ``changes.json``. "Latest" is by directory mtime, with the folder
    name (timestamped ``spv_YYYYmmdd_HHMMSS``) as a stable tiebreaker.
    """
    scan = EvidenceScan(searched_dirs=list(evidence_dirs))
    for d in evidence_dirs:
        base = Path(d)
        if not base.exists():
            continue
        for run_dir in base.glob(run_glob):
            if not run_dir.is_dir():
                continue
            try:
                mtime = run_dir.stat().st_mtime
            except OSError:
                continue
            scan.runs.append(
                EvidenceRun(
                    path=str(run_dir),
                    name=run_dir.name,
                    mtime=mtime,
                    has_changes_json=(run_dir / "changes.json").exists(),
                    has_preview_json=(run_dir / "preview.json").exists(),
                )
            )

    if scan.runs:
        scan.runs.sort(key=lambda r: (r.mtime, r.name))
        scan.latest_run = scan.runs[-1]
        apply_runs = [r for r in scan.runs if r.has_changes_json]
        if apply_runs:
            scan.latest_apply_run = apply_runs[-1]
    return scan


def scan_evidence_with_retry(
    evidence_dirs: list[str],
    run_glob: str = "spv_*",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    wait_seconds: float = 2.0,
    sleep_fn=None,
) -> tuple[EvidenceScan, int]:
    """Scan for evidence, retrying up to ``max_attempts`` times.

    Useful because the Revit add-in writes evidence asynchronously after the
    human performs the live step. Returns ``(scan, attempts_made)``. Retries
    stop as soon as an apply run is found. ``max_attempts`` is the bounded
    retry budget (spec section 6) and is overridable for larger testing concepts.
    ``sleep_fn`` is injectable so tests can avoid real waits.
    """
    if max_attempts < 1:
        max_attempts = 1
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    scan = EvidenceScan(searched_dirs=list(evidence_dirs))
    attempts = 0
    for attempts in range(1, max_attempts + 1):
        scan = scan_evidence(evidence_dirs, run_glob=run_glob)
        if scan.latest_apply_run is not None:
            break
        if attempts < max_attempts and wait_seconds > 0:
            sleeper(wait_seconds)
    return scan, attempts


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    if isinstance(value, (int, float)):
        return value != 0
    return False


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


@dataclass
class ConditionResult:
    """Outcome of evaluating a single evidence condition."""

    name: str
    kind: str
    passed: bool
    detail: str = ""


def _count_changed_and_failed(changes: dict) -> tuple[int, int]:
    """Return (changed_success_count, failed_count) from a changes.json dict."""
    elements = changes.get("elements")
    if isinstance(elements, list):
        success = sum(
            1 for e in elements if isinstance(e, dict)
            and str(e.get("status", "")).lower() == "success"
        )
        failed = sum(
            1 for e in elements if isinstance(e, dict)
            and str(e.get("status", "")).lower() == "failed"
        )
        return success, failed
    # Fall back to summary counts if elements absent.
    success = int(changes.get("success_count", 0) or 0)
    failed = int(changes.get("failed_count", 0) or 0)
    return success, failed


def evaluate_wall_comments_conditions(run_dir: str | None) -> list[ConditionResult]:
    """Evaluate the v0 scenario's evidence conditions for an apply run folder.

    Returns one ConditionResult per declared condition. A missing run folder
    fails every condition (file conditions first), which the classifier maps
    to ``evidence_missing``.
    """
    conditions = _WALL_COMMENTS_CONDITIONS
    if not run_dir:
        return [ConditionResult(c.name, c.kind, False, "no apply run found") for c in conditions]

    base = Path(run_dir)
    results: list[ConditionResult] = []

    # File-existence conditions.
    file_map = {
        "latest_apply_run_exists": "changes.json",  # apply run is defined by changes.json
        "result_summary_md_exists": "result_summary.md",
        "request_json_exists": "request.json",
        "changes_json_exists": "changes.json",
        "linked_preview_json_exists": "linked_preview.json",
        "linked_preview_metadata_json_exists": "linked_preview_metadata.json",
    }

    changes = _load_json(base / "changes.json") or {}
    request = _load_json(base / "request.json") or {}
    meta = _load_json(base / "linked_preview_metadata.json") or {}

    for cond in conditions:
        if cond.kind == "file":
            rel = file_map[cond.name]
            if cond.name == "latest_apply_run_exists":
                ok = base.exists() and (base / "changes.json").exists()
                detail = "apply run present" if ok else "no apply run folder"
            else:
                ok = (base / rel).exists()
                detail = "present" if ok else f"missing {rel}"
            results.append(ConditionResult(cond.name, "file", ok, detail))
            continue

        # Field conditions.
        if cond.name == "initiated_from_preview_approval":
            val = changes.get("initiated_from") or request.get("initiated_from") \
                or meta.get("initiated_from")
            ok = str(val).lower() == "preview_approval"
            results.append(ConditionResult(cond.name, "field", ok, f"initiated_from={val!r}"))
        elif cond.name == "targeted_by_ids_true":
            val = changes.get("targeted_by_ids", request.get("targeted_by_ids"))
            ok = _truthy(val)
            results.append(ConditionResult(cond.name, "field", ok, f"targeted_by_ids={val!r}"))
        elif cond.name == "target_ids_match_true":
            val = meta.get("target_ids_match")
            ok = _truthy(val)
            results.append(ConditionResult(cond.name, "field", ok, f"target_ids_match={val!r}"))
        elif cond.name == "model_modified_true":
            val = changes.get("model_modified")
            ok = _truthy(val)
            results.append(ConditionResult(cond.name, "field", ok, f"model_modified={val!r}"))
        elif cond.name == "changed_element_count_ge_1":
            success, _ = _count_changed_and_failed(changes)
            ok = success >= 1
            results.append(ConditionResult(cond.name, "field", ok, f"changed={success}"))
        elif cond.name == "no_failed_elements":
            _, failed = _count_changed_and_failed(changes)
            ok = failed == 0
            results.append(ConditionResult(cond.name, "field", ok, f"failed={failed}"))
        else:  # pragma: no cover - guard for unknown condition
            results.append(ConditionResult(cond.name, cond.kind, False, "unknown condition"))

    return results


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """Final pass/fail classification for a validation run."""

    classification: str
    reason: str
    failed_conditions: list[str] = field(default_factory=list)


def classify_run(
    *,
    is_admin: bool,
    tests_ran: bool,
    tests_passed: bool | None,
    deploy_attempted: bool,
    deploy_status: str,
    evidence_found: bool,
    manual_step_pending: bool,
    condition_results: list[ConditionResult],
) -> ClassificationResult:
    """Classify a run into the failure taxonomy.

    Precedence (first match wins):
        tests_failed -> needs_admin -> deploy_failed
        -> revit_manual_step_pending -> evidence_missing
        -> evidence_mismatch -> pass
    """
    if tests_ran and tests_passed is False:
        return ClassificationResult(CLASS_TESTS_FAILED, "One or more allowlisted tests failed.")

    if deploy_attempted:
        if deploy_status == "needs_admin":
            return ClassificationResult(
                CLASS_NEEDS_ADMIN,
                "Deploy requires elevation; relaunch deploy from an admin shell.",
            )
        if deploy_status in ("failed", "timed_out"):
            return ClassificationResult(
                CLASS_DEPLOY_FAILED, f"Deploy did not succeed (status={deploy_status})."
            )

    if manual_step_pending and not evidence_found:
        return ClassificationResult(
            CLASS_REVIT_MANUAL_STEP_PENDING,
            "Awaiting the live Revit step; run the scan phase after performing it.",
        )

    if not evidence_found:
        return ClassificationResult(
            CLASS_EVIDENCE_MISSING, "No apply evidence run was found across searched profiles."
        )

    file_failures = [c.name for c in condition_results if c.kind == "file" and not c.passed]
    if file_failures:
        return ClassificationResult(
            CLASS_EVIDENCE_MISSING,
            "Required evidence artifacts are missing.",
            failed_conditions=file_failures,
        )

    field_failures = [c.name for c in condition_results if c.kind == "field" and not c.passed]
    if field_failures:
        return ClassificationResult(
            CLASS_EVIDENCE_MISMATCH,
            "Evidence artifacts exist but do not satisfy expected conditions.",
            failed_conditions=field_failures,
        )

    return ClassificationResult(CLASS_PASS, "All evidence conditions satisfied.")


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def render_manual_steps(scenario: dict, revit_version: str, run_id: str) -> str:
    """Render the scenario's manual Revit steps as markdown."""
    lines = [
        f"# Manual Revit Steps - {scenario['title']}",
        "",
        f"- **Scenario:** {scenario['id']}",
        f"- **Revit version:** {revit_version}",
        f"- **Run ID:** {run_id}",
        "",
        "Perform these steps in Revit (the one human step in the loop):",
        "",
    ]
    for i, step in enumerate(scenario["manual_steps"], start=1):
        text = step.format(revit_version=revit_version, scenario=scenario["id"], run_id=run_id)
        lines.append(f"{i}. {text}")
    lines.append("")
    return "\n".join(lines)


def render_human_action_required(
    classification: ClassificationResult, scenario: dict, revit_version: str, run_id: str
) -> str:
    """Render a human-review packet for non-pass, non-pending classifications."""
    remedies = {
        CLASS_NEEDS_ADMIN: "Re-run only the deploy from an elevated/admin shell, then re-run the scan phase.",
        CLASS_DEPLOY_FAILED: "Inspect deploy_result.json. Common cause: Revit running (DLL lock) - close Revit and redeploy with -ForceCloseRevit.",
        CLASS_TESTS_FAILED: "Inspect test_results.json; fix failing tests before live validation.",
        CLASS_REVIT_MANUAL_STEP_PENDING: "Perform the manual Revit steps (manual_revit_steps.md), then run the scan phase.",
        CLASS_EVIDENCE_MISSING: "Confirm the add-in wrote evidence; check all user profiles. Re-run preview->apply if needed.",
        CLASS_EVIDENCE_MISMATCH: "Evidence exists but conditions failed (see pass_fail.json). Re-run preview->apply and verify target IDs match.",
    }
    lines = [
        f"# Human Action Required - {scenario['title']}",
        "",
        f"- **Run ID:** {run_id}",
        f"- **Classification:** {classification.classification}",
        f"- **Reason:** {classification.reason}",
        f"- **Revit version:** {revit_version}",
        "",
    ]
    if classification.failed_conditions:
        lines.append("## Failed conditions")
        lines.append("")
        for name in classification.failed_conditions:
            lines.append(f"- {name}")
        lines.append("")
    lines.append("## Recommended action")
    lines.append("")
    lines.append(remedies.get(classification.classification, "Review the run artifacts."))
    lines.append("")
    return "\n".join(lines)


def render_result_summary(
    *,
    run_id: str,
    scenario: dict,
    revit_version: str,
    phase: str,
    context: dict,
    git_state: dict,
    test_results: dict | None,
    deploy_result: dict | None,
    dll_timestamps: dict | None,
    scan: EvidenceScan | None,
    condition_results: list[ConditionResult],
    classification: ClassificationResult,
) -> str:
    """Render the human-readable result_summary.md."""
    lines = [
        f"# Validation Run Summary - {scenario['title']}",
        "",
        f"- **Run ID:** {run_id}",
        f"- **Scenario:** {scenario['id']}",
        f"- **Phase:** {phase}",
        f"- **Revit version:** {revit_version}",
        f"- **Classification:** {classification.classification}",
        f"- **Reason:** {classification.reason}",
        f"- **User:** {context.get('user', '')} (admin={context.get('is_admin')})",
        f"- **Platform:** {context.get('platform', '')}",
        f"- **Branch:** {git_state.get('branch', '')}",
        f"- **Commit:** {git_state.get('commit', '')[:12]} {git_state.get('commit_subject', '')}",
        f"- **Timestamp:** {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    if test_results is not None:
        lines.append("## Tests")
        lines.append("")
        lines.append(f"- **All passed:** {test_results.get('all_passed')}")
        for name, r in test_results.get("results", {}).items():
            lines.append(f"  - `{name}`: {r.get('summary')} (exit {r.get('exit_code')})")
        lines.append("")

    if deploy_result is not None:
        lines.append("## Deploy")
        lines.append("")
        lines.append(f"- **Status:** {deploy_result.get('status')}")
        if deploy_result.get("reason"):
            lines.append(f"- **Reason:** {deploy_result.get('reason')}")
        lines.append("")

    if dll_timestamps is not None:
        lines.append("## Deployed DLL timestamps")
        lines.append("")
        if not dll_timestamps.get("applicable", True):
            lines.append(f"- (not applicable on this platform) target: `{dll_timestamps.get('addins_dir')}`")
        else:
            for name, info in dll_timestamps.get("files", {}).items():
                if info.get("exists"):
                    lines.append(f"- `{name}`: {info.get('last_write_time')}")
                else:
                    lines.append(f"- `{name}`: (missing)")
        lines.append("")

    if scan is not None:
        lines.append("## Evidence scan")
        lines.append("")
        lines.append(f"- **Searched dirs:** {len(scan.searched_dirs)}")
        lines.append(f"- **Runs found:** {len(scan.runs)}")
        latest_apply = scan.latest_apply_run.path if scan.latest_apply_run else "(none)"
        lines.append(f"- **Latest apply run:** {latest_apply}")
        lines.append("")

    if condition_results:
        lines.append("## Evidence conditions")
        lines.append("")
        lines.append("| Condition | Kind | Result | Detail |")
        lines.append("|-----------|------|--------|--------|")
        for c in condition_results:
            lines.append(f"| {c.name} | {c.kind} | {'PASS' if c.passed else 'FAIL'} | {c.detail} |")
        lines.append("")

    return "\n".join(lines)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _condition_to_dict(c: ConditionResult) -> dict:
    return {"name": c.name, "kind": c.kind, "passed": c.passed, "detail": c.detail}


def _scan_to_dict(scan: EvidenceScan) -> dict:
    return {
        "searched_dirs": scan.searched_dirs,
        "runs": [
            {
                "path": r.path,
                "name": r.name,
                "mtime": r.mtime,
                "has_changes_json": r.has_changes_json,
                "has_preview_json": r.has_preview_json,
            }
            for r in scan.runs
        ],
        "latest_run": scan.latest_run.path if scan.latest_run else None,
        "latest_apply_run": scan.latest_apply_run.path if scan.latest_apply_run else None,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class ValidationRunResult:
    """Top-level result of a validation-loop run."""

    run_id: str = ""
    scenario_id: str = ""
    phase: str = ""
    revit_version: str = ""
    classification: str = ""
    reason: str = ""
    artifact_dir: str = ""
    human_action_required: bool = False


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("vrun_%Y%m%d_%H%M%S")


def run_validation(
    *,
    scenario_name: str,
    branch: str | None = None,
    revit_version: str = "2027",
    phase: str = "all",
    do_pull: bool = False,
    do_tests: bool = True,
    do_deploy: bool = False,
    evidence_dirs: list[str] | None = None,
    repo_root: str = ".",
    output_dir: str = "artifacts/validation_runs",
    run_id: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    attempt_wait_seconds: float = 2.0,
    sleep_fn=None,
) -> ValidationRunResult:
    """Run the validation loop and write a full artifact bundle.

    Phases:
        - ``pre``:  context/git/(pull)/tests/deploy/dll-timestamps + manual steps.
                    Stops for the human Revit step (revit_manual_step_pending)
                    unless evidence already exists.
        - ``scan``: scan evidence + evaluate conditions + classify (resume a
                    pre run via ``run_id``).
        - ``all``:  pre work followed immediately by scan/classify (use when
                    the live Revit step has already been performed).
    """
    scenario = resolve_scenario(scenario_name)
    if scenario is None:
        known = sorted(set(SCENARIOS) | set(SCENARIO_ALIASES))
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. Known: {', '.join(known)}"
        )

    if phase not in ("pre", "scan", "all"):
        raise ValueError(f"Unknown phase '{phase}'. Use pre | scan | all.")

    if max_attempts < 1:
        max_attempts = 1

    run_id = run_id or _new_run_id()
    artifact_dir = Path(output_dir) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # request.json - the validation request itself.
    request = {
        "run_id": run_id,
        "scenario": scenario["id"],
        "scenario_requested": scenario_name,
        "branch": branch,
        "revit_version": revit_version,
        "phase": phase,
        "do_pull": do_pull,
        "do_tests": do_tests,
        "do_deploy": do_deploy,
        "repo_root": str(repo_root),
        "max_attempts": max_attempts,
        "attempt_wait_seconds": attempt_wait_seconds,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(artifact_dir / "request.json", request)

    # Always record context + git state.
    context = record_context()
    _write_json(artifact_dir / "environment.json", context)

    if do_pull and branch and phase in ("pre", "all"):
        request["pull_result"] = pull_branch(repo_root, branch)
        _write_json(artifact_dir / "request.json", request)
    git_state = record_git_state(repo_root)
    _write_json(artifact_dir / "git_state.json", git_state)

    # Pre-phase work: tests, deploy, dll timestamps, manual steps.
    test_results: dict | None = None
    deploy_result: dict | None = None
    dll_timestamps: dict | None = None

    if phase in ("pre", "all"):
        if do_tests:
            test_results = run_tests(repo_root)
        else:
            test_results = {"all_passed": None, "skipped": True, "results": {}}
        _write_json(artifact_dir / "test_results.json", test_results)

        if do_deploy:
            deploy_result = run_deploy(repo_root, revit_version)
        else:
            deploy_result = {"attempted": False, "status": "skipped", "reason": "not_requested"}
        _write_json(artifact_dir / "deploy_result.json", deploy_result)

        dll_timestamps = capture_dll_timestamps(revit_version)
        _write_json(artifact_dir / "deployed_dll_timestamps.json", dll_timestamps)

        (artifact_dir / "manual_revit_steps.md").write_text(
            render_manual_steps(scenario, revit_version, run_id), encoding="utf-8"
        )

    # Evidence scan (always attempted; defines pass/fail in scan/all phases).
    # In scan/all phases we apply the bounded retry budget because the add-in
    # writes evidence asynchronously after the human Revit step. In the pre
    # phase we take a single snapshot (the human step has not happened yet).
    dirs = evidence_dirs if evidence_dirs is not None else default_evidence_dirs(scenario)
    if phase == "pre":
        scan = scan_evidence(dirs, run_glob=scenario["apply_run_glob"])
        attempts_made = 1
    else:
        scan, attempts_made = scan_evidence_with_retry(
            dirs,
            run_glob=scenario["apply_run_glob"],
            max_attempts=max_attempts,
            wait_seconds=attempt_wait_seconds,
            sleep_fn=sleep_fn,
        )
    scan_dict = _scan_to_dict(scan)
    scan_dict["max_attempts"] = max_attempts
    scan_dict["attempts_made"] = attempts_made
    _write_json(artifact_dir / "evidence_scan.json", scan_dict)

    latest_apply = scan.latest_apply_run.path if scan.latest_apply_run else None
    condition_results = evaluate_wall_comments_conditions(latest_apply)

    # In the pre phase we are explicitly waiting for the human Revit step,
    # unless evidence already exists (idempotent re-run).
    manual_step_pending = phase == "pre" and scan.latest_apply_run is None

    deploy_attempted = bool(deploy_result and deploy_result.get("attempted"))
    deploy_status = deploy_result.get("status", "skipped") if deploy_result else "skipped"
    tests_ran = bool(test_results and not test_results.get("skipped"))
    tests_passed = test_results.get("all_passed") if test_results else None

    classification = classify_run(
        is_admin=bool(context.get("is_admin")),
        tests_ran=tests_ran,
        tests_passed=tests_passed,
        deploy_attempted=deploy_attempted,
        deploy_status=deploy_status,
        evidence_found=scan.latest_apply_run is not None,
        manual_step_pending=manual_step_pending,
        condition_results=condition_results,
    )

    _write_json(
        artifact_dir / "pass_fail.json",
        {
            "classification": classification.classification,
            "reason": classification.reason,
            "failed_conditions": classification.failed_conditions,
            "conditions": [_condition_to_dict(c) for c in condition_results],
            "evidence_found": scan.latest_apply_run is not None,
            "latest_apply_run": latest_apply,
            "max_attempts": max_attempts,
            "attempts_made": attempts_made,
        },
    )

    (artifact_dir / "result_summary.md").write_text(
        render_result_summary(
            run_id=run_id,
            scenario=scenario,
            revit_version=revit_version,
            phase=phase,
            context=context,
            git_state=git_state,
            test_results=test_results,
            deploy_result=deploy_result,
            dll_timestamps=dll_timestamps,
            scan=scan,
            condition_results=condition_results,
            classification=classification,
        ),
        encoding="utf-8",
    )

    human_action = classification.classification != CLASS_PASS
    if human_action:
        (artifact_dir / "human_action_required.md").write_text(
            render_human_action_required(classification, scenario, revit_version, run_id),
            encoding="utf-8",
        )

    return ValidationRunResult(
        run_id=run_id,
        scenario_id=scenario["id"],
        phase=phase,
        revit_version=revit_version,
        classification=classification.classification,
        reason=classification.reason,
        artifact_dir=str(artifact_dir),
        human_action_required=human_action,
    )
