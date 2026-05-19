"""Summary report generation for model inventory runs."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def generate_summary(
    elements: list[dict],
    run_id: str,
    output_dir: Path,
    duration_ms: int = 0,
    source_model: str = "",
) -> Path:
    """Generate a Markdown summary report for an inventory run.

    Writes to <output_dir>/<run_id>/summary.md and returns the path.
    """
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.md"

    instances = [e for e in elements if not e.get("IsType", False)]
    types = [e for e in elements if e.get("IsType", False)]

    total_elements = len(instances)
    total_types = len(types)

    # Collect all parameters
    all_params: list[dict] = []
    for elem in elements:
        all_params.extend(elem.get("Parameters", []))

    total_params = len(all_params)

    # Category counts
    cat_counter: Counter = Counter()
    for elem in elements:
        cat_counter[elem.get("Category", "(No Category)")] += 1

    # Top parameter names by frequency
    param_name_counter: Counter = Counter()
    for p in all_params:
        param_name_counter[p.get("Name", "(unknown)")] += 1

    top_params = param_name_counter.most_common(20)

    # Elements missing level
    missing_level = sum(
        1 for e in instances if not e.get("LevelName")
    )

    # Read-only vs writable parameter counts
    read_only_count = sum(1 for p in all_params if p.get("IsReadOnly", False))
    writable_count = total_params - read_only_count

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Model Inventory Summary",
        "",
        f"**Run ID:** {run_id}  ",
        f"**Source Model:** {source_model or '(unknown)'}  ",
        f"**Timestamp:** {now_str}  ",
        f"**Duration:** {duration_ms}ms  ",
        "",
        "## Totals",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Element instances | {total_elements} |",
        f"| Element types | {total_types} |",
        f"| Total parameters | {total_params} |",
        f"| Read-only parameters | {read_only_count} |",
        f"| Writable parameters | {writable_count} |",
        f"| Instances missing level | {missing_level} |",
        "",
        "## Category Counts",
        "",
        "| Category | Count |",
        "|----------|-------|",
    ]

    for cat, count in cat_counter.most_common():
        lines.append(f"| {cat} | {count} |")

    lines.extend([
        "",
        "## Top Parameters by Frequency",
        "",
        "| Parameter Name | Occurrences |",
        "|---------------|-------------|",
    ])

    for pname, count in top_params:
        lines.append(f"| {pname} | {count} |")

    lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path
