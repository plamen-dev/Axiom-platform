"""Summary report generation and regression comparison for grid test runs."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from axiom_core.testing.models import GridTestResult
from axiom_core.testing.storage import read_parquet


def generate_summary(
    results: list[GridTestResult],
    run_id: str,
    output_dir: Path,
    previous_parquet: Optional[Path] = None,
) -> Path:
    """Generate a concise markdown summary report.

    Args:
        results: Current run results.
        run_id: Identifier for this run.
        output_dir: Base output directory (run_id subdirectory used).
        previous_parquet: Path to a previous run's results.parquet for regression comparison.

    Returns:
        Path to the generated summary.md file.
    """
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.md"

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and r.failure_category != "skipped")
    skipped = sum(1 for r in results if r.failure_category == "skipped")
    expected_failures = sum(
        1 for r in results if r.passed and not r.expected_success
    )
    unexpected_failures = sum(
        1 for r in results
        if not r.passed and r.expected_success and r.failure_category != "skipped"
    )

    # Failure category breakdown
    failure_cats = Counter(
        r.failure_category for r in results
        if not r.passed and r.failure_category and r.failure_category != "skipped"
    )

    git_commit = results[0].git_commit if results else "unknown"
    git_branch = results[0].git_branch if results else "unknown"
    timestamp = results[0].timestamp if results else datetime.now(timezone.utc).isoformat()

    lines = [
        f"# Grid Test Run: {run_id}",
        "",
        f"**Timestamp:** {timestamp}",
        f"**Git:** `{git_branch}` @ `{git_commit}`",
        "**Mode filter:** mixed (simulate + real)",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total tests | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Skipped | {skipped} |",
        f"| Expected failures (passed) | {expected_failures} |",
        f"| Unexpected failures | {unexpected_failures} |",
        "",
    ]

    if failure_cats:
        lines.extend([
            "## Top Failure Categories",
            "",
            "| Category | Count |",
            "|----------|-------|",
        ])
        for cat, count in failure_cats.most_common():
            lines.append(f"| {cat} | {count} |")
        lines.append("")

    # Detailed failures
    failed_results = [
        r for r in results if not r.passed and r.failure_category != "skipped"
    ]
    if failed_results:
        lines.extend([
            "## Failed Tests",
            "",
        ])
        for r in failed_results:
            lines.append(f"### `{r.test_id}`")
            lines.append(f"- **Prompt:** `{r.prompt[:80]}{'...' if len(r.prompt) > 80 else ''}`")
            lines.append(f"- **Category:** {r.failure_category}")
            lines.append(f"- **Detail:** {r.failure_detail}")
            if r.errors:
                lines.append(f"- **Errors:** {r.errors}")
            lines.append("")

    # Skipped tests
    skipped_results = [r for r in results if r.failure_category == "skipped"]
    if skipped_results:
        lines.extend([
            "## Skipped Tests",
            "",
        ])
        for r in skipped_results:
            lines.append(f"- `{r.test_id}`: {r.failure_detail}")
        lines.append("")

    # Regression comparison
    if previous_parquet is not None and previous_parquet.exists():
        regression_lines = _compare_runs(results, previous_parquet)
        lines.extend(regression_lines)

    # Recommendations
    recommendations = _generate_recommendations(results, failure_cats)
    if recommendations:
        lines.extend([
            "## Recommended Next Fixes",
            "",
        ])
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return summary_path


def _compare_runs(
    current_results: list[GridTestResult],
    previous_parquet: Path,
) -> list[str]:
    """Compare current results to a previous Parquet run."""
    prev_data = read_parquet(previous_parquet)
    if not prev_data or "test_id" not in prev_data:
        return []

    prev_by_id: dict[str, dict] = {}
    test_ids = prev_data.get("test_id", [])
    for i, tid in enumerate(test_ids):
        prev_by_id[tid] = {
            key: vals[i] for key, vals in prev_data.items()
        }

    lines = [
        "## Regression Comparison",
        "",
        f"Compared against: `{previous_parquet.name}`",
        "",
    ]

    newly_passing: list[str] = []
    newly_failing: list[str] = []
    unchanged_failures: list[str] = []
    count_changes: list[str] = []

    for r in current_results:
        prev = prev_by_id.get(r.test_id)
        if prev is None:
            continue

        prev_passed = prev.get("passed", False)

        if r.passed and not prev_passed:
            newly_passing.append(r.test_id)
        elif not r.passed and prev_passed:
            newly_failing.append(r.test_id)
        elif not r.passed and not prev_passed:
            unchanged_failures.append(r.test_id)

        prev_count = prev.get("created_count", 0)
        if r.created_count != prev_count:
            count_changes.append(
                f"`{r.test_id}`: {prev_count} -> {r.created_count}"
            )

    if newly_passing:
        lines.append(f"**Newly passing ({len(newly_passing)}):** "
                      + ", ".join(f"`{t}`" for t in newly_passing))
        lines.append("")
    if newly_failing:
        lines.append(f"**Newly failing ({len(newly_failing)}):** "
                      + ", ".join(f"`{t}`" for t in newly_failing))
        lines.append("")
    if unchanged_failures:
        lines.append(f"**Still failing ({len(unchanged_failures)}):** "
                      + ", ".join(f"`{t}`" for t in unchanged_failures))
        lines.append("")
    if count_changes:
        lines.append("**Created count changes:**")
        for chg in count_changes:
            lines.append(f"- {chg}")
        lines.append("")

    if not (newly_passing or newly_failing or unchanged_failures or count_changes):
        lines.append("No regressions or improvements detected.")
        lines.append("")

    return lines


def _generate_recommendations(
    results: list[GridTestResult],
    failure_cats: Counter,
) -> list[str]:
    """Generate actionable recommendations from failure patterns."""
    recs: list[str] = []

    if failure_cats.get("wrong_parameter"):
        recs.append(
            "Parameter resolution mismatches detected — review prompt_resolver.py "
            "extraction logic for affected test cases."
        )
    if failure_cats.get("wrong_count"):
        recs.append(
            "Created count mismatches — check GridCreationService offset calculations "
            "and mock execution in pipe_client.py."
        )
    if failure_cats.get("unexpected_failure"):
        recs.append(
            "Unexpected failures — inspect error messages for validation or pipe issues."
        )
    if failure_cats.get("unexpected_success"):
        recs.append(
            "Tests expected to fail are now succeeding — update test case expectations "
            "or verify the behavior change is intentional."
        )
    if failure_cats.get("wrong_capability"):
        recs.append(
            "Wrong capability resolved — check _is_grid_prompt() and resolver keyword matching."
        )
    if failure_cats.get("exception"):
        recs.append(
            "Unhandled exceptions during test execution — check stack traces in error details."
        )

    all_passed = all(r.passed for r in results if r.failure_category != "skipped")
    if all_passed and not recs:
        recs.append("All tests passing. Consider adding more edge cases or stress tests.")

    return recs


def find_latest_previous_run(output_dir: Path, current_run_id: str) -> Optional[Path]:
    """Find the most recent previous Parquet file for regression comparison."""
    if not output_dir.exists():
        return None

    candidates: list[Path] = []
    for run_dir in output_dir.iterdir():
        if not run_dir.is_dir():
            continue
        if run_dir.name == current_run_id:
            continue
        parquet = run_dir / "results.parquet"
        if parquet.exists():
            candidates.append(parquet)

    if not candidates:
        return None

    # Sort by modification time, most recent first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
