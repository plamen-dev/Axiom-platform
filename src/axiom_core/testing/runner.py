"""Grid test harness runner — executes test cases and produces results."""

import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

from axiom_core.agents.execution_agent import ExecutionAgent
from axiom_core.agents.orchestrator_agent import OrchestratorAgent
from axiom_core.agents.telemetry_agent import TelemetryAgent
from axiom_core.pipe_client import PipeClient
from axiom_core.testing.models import GridTestCase, GridTestResult


def _git_info() -> tuple[str, str]:
    """Return (commit_hash, branch_name) from the current repo."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        commit = "unknown"

    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        branch = "unknown"

    return commit, branch


def run_single_case(
    case: GridTestCase,
    pipe_client: Optional[PipeClient] = None,
) -> GridTestResult:
    """Execute a single test case and return the result."""
    commit, branch = _git_info()
    now = datetime.now(timezone.utc).isoformat()

    if pipe_client is None:
        pipe_client = PipeClient()

    simulate = case.mode == "simulate"

    result = GridTestResult(
        test_id=case.test_id,
        prompt=case.prompt,
        mode=case.mode,
        git_commit=commit,
        git_branch=branch,
        timestamp=now,
        expected_success=case.expected_success,
        expected_created_count=case.expected_created_count,
        expected_capability=case.expected_capability,
        expected_parameters=case.expected_parameters,
        notes=case.notes,
        pipe_available=pipe_client.is_available(),
    )

    # Build agents for this run
    execution_agent = ExecutionAgent(pipe_client=pipe_client)
    telemetry_agent = TelemetryAgent()
    orchestrator = OrchestratorAgent(
        execution_agent=execution_agent,
        telemetry_agent=telemetry_agent,
    )

    start = time.monotonic()
    try:
        outcome = orchestrator.handle_prompt(case.prompt, simulate=simulate)
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        result.status = "ERROR"
        result.errors = [f"Unhandled exception: {type(exc).__name__}: {exc}"]
        result.duration_ms = elapsed
        result.passed = False
        result.failure_category = "exception"
        result.failure_detail = str(exc)
        return result

    elapsed = int((time.monotonic() - start) * 1000)
    result.duration_ms = elapsed

    # Extract resolution info
    resolved = outcome.get("resolved")
    if resolved is not None:
        result.resolved_capability = resolved.capability_name
        result.resolved_parameters = dict(resolved.params)
        result.assumptions = list(resolved.assumptions)

    result.status = outcome.get("status", "UNKNOWN")

    # Extract execution results
    results_list = outcome.get("results", [])
    for r in results_list:
        result.created_ids.extend(r.created_ids)
        result.warnings.extend(r.warnings)
        result.errors.extend(r.errors)
        result.duration_ms += r.duration_ms

    result.created_count = len(result.created_ids)

    # Determine pass/fail
    result.passed, result.failure_category, result.failure_detail = _evaluate_verdict(
        case, result
    )

    return result


def _evaluate_verdict(
    case: GridTestCase,
    result: GridTestResult,
) -> tuple[bool, str, str]:
    """Compare result against expectations and return (passed, category, detail)."""
    # Check for specific expected status (e.g. CLARIFICATION_NEEDED)
    if case.expected_status is not None:
        if result.status != case.expected_status:
            return (
                False,
                "wrong_status",
                f"Expected status {case.expected_status}, got {result.status}",
            )
        return True, "", ""

    # Check success/failure match
    actual_success = result.status == "SUCCESS"
    if case.expected_success and not actual_success:
        return (
            False,
            "unexpected_failure",
            f"Expected SUCCESS but got {result.status}: {result.errors}",
        )
    if not case.expected_success and actual_success:
        return (
            False,
            "unexpected_success",
            "Expected failure but got SUCCESS",
        )

    # If expected failure, we're done — it failed as expected
    if not case.expected_success:
        return True, "", ""

    # Check capability
    if case.expected_capability is not None:
        if result.resolved_capability != case.expected_capability:
            return (
                False,
                "wrong_capability",
                f"Expected {case.expected_capability}, got {result.resolved_capability}",
            )

    # Check created count
    if case.expected_created_count > 0:
        if result.created_count != case.expected_created_count:
            return (
                False,
                "wrong_count",
                f"Expected {case.expected_created_count} created, got {result.created_count}",
            )

    # Check key parameters (partial match — only check keys present in expected)
    for key, expected_val in case.expected_parameters.items():
        actual_val = result.resolved_parameters.get(key)
        if actual_val is None:
            continue
        if isinstance(expected_val, list):
            if not isinstance(actual_val, list) or actual_val != expected_val:
                return (
                    False,
                    "wrong_parameter",
                    f"Parameter {key}: expected {expected_val}, got {actual_val}",
                )
        elif isinstance(expected_val, float):
            if not isinstance(actual_val, (int, float)) or abs(actual_val - expected_val) > 0.01:
                return (
                    False,
                    "wrong_parameter",
                    f"Parameter {key}: expected {expected_val}, got {actual_val}",
                )
        elif isinstance(expected_val, int):
            if actual_val != expected_val:
                return (
                    False,
                    "wrong_parameter",
                    f"Parameter {key}: expected {expected_val}, got {actual_val}",
                )

    return True, "", ""


def run_test_suite(
    cases: list[GridTestCase],
    fail_fast: bool = False,
) -> list[GridTestResult]:
    """Run a list of test cases and return all results.

    Args:
        cases: Test cases to execute.
        fail_fast: If True, stop on the first failure.
    """
    pipe_client = PipeClient()
    results: list[GridTestResult] = []

    for case in cases:
        # Skip real-mode cases if pipe isn't available
        if case.mode == "real" and not pipe_client.is_available():
            result = GridTestResult(
                test_id=case.test_id,
                prompt=case.prompt,
                mode=case.mode,
                git_commit=_git_info()[0],
                git_branch=_git_info()[1],
                timestamp=datetime.now(timezone.utc).isoformat(),
                expected_success=case.expected_success,
                expected_created_count=case.expected_created_count,
                expected_capability=case.expected_capability,
                expected_parameters=case.expected_parameters,
                notes=case.notes,
                pipe_available=False,
                status="SKIPPED",
                passed=False,
                failure_category="skipped",
                failure_detail="Revit pipe not available — real mode requires Revit",
            )
            results.append(result)
            continue

        r = run_single_case(case, pipe_client=pipe_client)
        results.append(r)

        if fail_fast and not r.passed:
            break

    return results
