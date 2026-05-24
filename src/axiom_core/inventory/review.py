"""Read-back utilities for inspecting inventory run artifacts.

Reads from Parquet files produced by persist_inventory() and returns
structured summaries suitable for CLI display or programmatic use.
"""

from __future__ import annotations

import json
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
    scan_mode: str = ""

    category_counts: dict[str, int] = field(default_factory=dict)
    top_param_names: list[tuple[str, int]] = field(default_factory=list)

    # Parameter schema specific
    parameter_definition_count: int = 0
    unique_parameter_names: int = 0
    top_param_definitions: list[tuple[str, int]] = field(default_factory=list)
    is_parameter_schema: bool = False

    # Enriched metadata (parameter schema)
    unique_data_types: int = 0
    unique_groups: int = 0
    measurable_count: int = 0
    unique_disciplines: int = 0
    top_data_type_labels: list[tuple[str, int]] = field(default_factory=list)
    top_group_labels: list[tuple[str, int]] = field(default_factory=list)
    top_disciplines: list[tuple[str, int]] = field(default_factory=list)


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

    # Load run metadata if available (written during inventory-import)
    meta_path = run_dir / "run_metadata.json"
    run_meta: dict = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8-sig") as mf:
            run_meta = json.load(mf)
        summary.run_id = run_meta.get("run_id", "")
        summary.source_model = run_meta.get("source_model", "")
        summary.scan_mode = run_meta.get("scan_mode", "")

    # Check if this is a parameter schema run
    ps_parquet = run_dir / "parameter_schema.parquet"
    if ps_parquet.exists():
        return _load_parameter_schema_summary(
            summary, run_dir, run_meta,
            category_filter=category_filter,
            param_name_filter=param_name_filter,
            writable_only=writable_only,
        )

    elem_path = run_dir / "elements.parquet"
    param_path = run_dir / "parameters.parquet"

    if not elem_path.exists() or not param_path.exists():
        # Even without parquet files, metadata may have counts
        if run_meta:
            summary.total_instances = run_meta.get("instance_count", 0)
            summary.total_types = run_meta.get("type_count", 0)
            summary.total_elements = summary.total_instances + summary.total_types
            summary.total_parameters = run_meta.get("parameter_count", 0)
            summary.category_counts = run_meta.get("category_counts", {})
        return summary

    # --- Elements ---
    elem_table = pq.read_table(str(elem_path))
    elem_df = {col: elem_table.column(col).to_pylist() for col in elem_table.schema.names}
    n_rows = elem_table.num_rows

    # Extract run_id / source_model from first row (don't override metadata)
    if n_rows > 0:
        parquet_run_id = (elem_df.get("run_id") or [""])[0] or ""
        parquet_source = (elem_df.get("source_model") or [""])[0] or ""
        if parquet_run_id:
            summary.run_id = parquet_run_id
        if parquet_source:
            summary.source_model = parquet_source

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

    # Category counts (from parquet elements; metadata category_counts used as fallback)
    cat_counter = Counter(e.get("category", "(No Category)") for e in elements)
    summary.category_counts = dict(cat_counter.most_common())

    # For summary-mode runs, elements list is empty — use metadata counts
    if summary.total_elements == 0 and run_meta:
        summary.total_instances = run_meta.get("instance_count", 0)
        summary.total_types = run_meta.get("type_count", 0)
        summary.total_elements = summary.total_instances + summary.total_types
        summary.category_counts = run_meta.get("category_counts", {})

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


def _load_parameter_schema_summary(
    summary: InventorySummary,
    run_dir: Path,
    run_meta: dict,
    *,
    category_filter: Optional[str] = None,
    param_name_filter: Optional[str] = None,
    writable_only: bool = False,
) -> InventorySummary:
    """Load summary from a parameter_schema.parquet run."""
    summary.is_parameter_schema = True
    if not summary.scan_mode:
        summary.scan_mode = run_meta.get("scan_mode", "category_parameter_schema")

    ps_path = run_dir / "parameter_schema.parquet"
    table = pq.read_table(str(ps_path))
    df = {col: table.column(col).to_pylist() for col in table.schema.names}
    n_rows = table.num_rows

    defs: list[dict] = []
    for i in range(n_rows):
        row = {col: df[col][i] for col in df}
        if not row.get("parameter_name"):
            continue
        defs.append(row)

    if category_filter:
        cf_lower = category_filter.lower()
        defs = [d for d in defs if cf_lower in (d.get("category") or "").lower()]

    if param_name_filter:
        pf_lower = param_name_filter.lower()
        defs = [d for d in defs if pf_lower in (d.get("parameter_name") or "").lower()]

    if writable_only:
        defs = [d for d in defs if not d.get("is_read_only", False)]

    summary.parameter_definition_count = len(defs)
    unique_names = {d.get("parameter_name", "") for d in defs}
    summary.unique_parameter_names = len(unique_names)
    summary.read_only_params = sum(1 for d in defs if d.get("is_read_only", False))
    summary.writable_params = len(defs) - summary.read_only_params
    summary.instance_params = sum(1 for d in defs if d.get("is_instance_param", False))
    summary.type_params = sum(1 for d in defs if d.get("is_type_param", False))
    summary.total_parameters = len(defs)

    # Category counts from parameter definitions
    cat_counter = Counter(d.get("category", "") for d in defs)
    summary.category_counts = dict(cat_counter.most_common())

    # Top parameter names by observed_count
    name_counts: dict[str, int] = {}
    for d in defs:
        pname = d.get("parameter_name", "")
        count = d.get("observed_count", 1) or 1
        name_counts[pname] = name_counts.get(pname, 0) + count
    summary.top_param_definitions = sorted(
        name_counts.items(), key=lambda x: -x[1],
    )[:20]
    summary.top_param_names = summary.top_param_definitions

    # Enriched metadata stats
    dt_labels = Counter(
        d.get("data_type_label", "") for d in defs
        if d.get("data_type_label")
    )
    summary.unique_data_types = len(dt_labels)
    summary.top_data_type_labels = dt_labels.most_common(10)

    grp_labels = Counter(
        d.get("group_type_label", "") for d in defs
        if d.get("group_type_label")
    )
    summary.unique_groups = len(grp_labels)
    summary.top_group_labels = grp_labels.most_common(10)

    summary.measurable_count = sum(
        1 for d in defs if d.get("is_measurable_spec", False)
    )

    disc_labels = Counter(
        d.get("discipline_label", "") for d in defs
        if d.get("discipline_label")
    )
    summary.unique_disciplines = len(disc_labels)
    summary.top_disciplines = disc_labels.most_common(10)

    # Use metadata for element counts if available
    summary.total_instances = run_meta.get("instance_count", 0)
    summary.total_types = run_meta.get("type_count", 0)
    summary.total_elements = summary.total_instances + summary.total_types

    return summary
