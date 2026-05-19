"""Read-back utilities for inspecting inventory run artifacts.

Reads from Parquet files produced by persist_inventory() and returns
structured summaries suitable for CLI display or programmatic use.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq


@dataclass
class InventorySummary:
    """Aggregated summary of an inventory run."""

    run_id: str = ""
    source_model: str = ""
    run_dir: str = ""

    total_elements: int = 0
    total_types: int = 0
    total_instances: int = 0
    total_parameters: int = 0

    read_only_params: int = 0
    writable_params: int = 0
    instance_params: int = 0
    type_params: int = 0

    missing_level_count: int = 0

    category_counts: dict[str, int] = field(default_factory=dict)
    top_param_names: list[tuple[str, int]] = field(default_factory=list)


def find_latest_run(base_dir: Path) -> Optional[Path]:
    """Find the most recent inventory run directory by name sort."""
    if not base_dir.exists():
        return None
    dirs = sorted(
        [d for d in base_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


def load_summary(
    run_dir: Path,
    *,
    category_filter: Optional[str] = None,
    param_name_filter: Optional[str] = None,
    writable_only: bool = False,
) -> InventorySummary:
    """Load and summarize an inventory run from its Parquet artifacts.

    Filters are applied on the in-memory tables after reading:
      - category_filter: case-insensitive substring match on element category
      - param_name_filter: case-insensitive substring match on param_name
      - writable_only: only include writable parameters (is_read_only=False)
    """
    summary = InventorySummary(run_dir=str(run_dir))

    elem_path = run_dir / "elements.parquet"
    param_path = run_dir / "parameters.parquet"

    if not elem_path.exists() or not param_path.exists():
        return summary

    # --- Elements ---
    elem_table = pq.read_table(str(elem_path))
    elem_df = {col: elem_table.column(col).to_pylist() for col in elem_table.schema.names}
    n_rows = elem_table.num_rows

    # Extract run_id / source_model from first row
    if n_rows > 0:
        summary.run_id = (elem_df.get("run_id") or [""])[0] or ""
        summary.source_model = (elem_df.get("source_model") or [""])[0] or ""

    # Build per-element data for filtering (skip placeholder rows)
    elements: list[dict] = []
    for i in range(n_rows):
        row = {col: elem_df[col][i] for col in elem_df}
        if row.get("element_id") is None and row.get("unique_id") is None:
            continue
        elements.append(row)

    # Apply category filter
    if category_filter:
        cf_lower = category_filter.lower()
        elements = [e for e in elements if cf_lower in (e.get("category") or "").lower()]

    # Compute element stats
    element_ids = {e["element_id"] for e in elements}
    summary.total_instances = sum(1 for e in elements if not e.get("is_type", False))
    summary.total_types = sum(1 for e in elements if e.get("is_type", False))
    summary.total_elements = len(elements)

    # Category counts
    cat_counter = Counter(e.get("category", "(No Category)") for e in elements)
    summary.category_counts = dict(cat_counter.most_common())

    # Missing level (instances only)
    summary.missing_level_count = sum(
        1 for e in elements
        if not e.get("is_type", False) and not e.get("level_name")
    )

    # --- Parameters ---
    param_table = pq.read_table(str(param_path))
    param_df = {col: param_table.column(col).to_pylist() for col in param_table.schema.names}
    p_rows = param_table.num_rows

    params: list[dict] = []
    for i in range(p_rows):
        row = {col: param_df[col][i] for col in param_df}
        if row.get("element_id") is None and row.get("param_name") is None:
            continue
        params.append(row)

    # Filter params to matching elements (if category filter applied)
    if category_filter:
        params = [p for p in params if p.get("element_id") in element_ids]

    # Filter by parameter name
    if param_name_filter:
        pf_lower = param_name_filter.lower()
        params = [p for p in params if pf_lower in (p.get("param_name") or "").lower()]

    # Filter writable only
    if writable_only:
        params = [p for p in params if not p.get("is_read_only", False)]

    # Compute parameter stats
    summary.total_parameters = len(params)
    summary.read_only_params = sum(1 for p in params if p.get("is_read_only", False))
    summary.writable_params = summary.total_parameters - summary.read_only_params
    summary.instance_params = sum(1 for p in params if p.get("is_instance_param", True))
    summary.type_params = summary.total_parameters - summary.instance_params

    # Top parameter names
    name_counter = Counter(p.get("param_name", "") for p in params)
    summary.top_param_names = name_counter.most_common(20)

    return summary
