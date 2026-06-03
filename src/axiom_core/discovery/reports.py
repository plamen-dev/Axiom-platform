"""Human-reviewable discovery outputs under artifacts/discovery_runs/<run_id>/.

Writes (all ASCII / PowerShell-safe):
  - categories.csv
  - parameters.csv               (incl. value contract columns)
  - candidate_capabilities.csv   (labeled instance/type + safely_settable)
  - discovery_evidence.jsonl
  - summary.json
  - summary.md
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .interpret import Interpretation


def _run_dir(output_dir: Path, run_id: str) -> Path:
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_categories_csv(interp: Interpretation, path: Path) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["adapter", "category_name", "built_in_category", "category_id",
             "element_count", "type_count"]
        )
        for cat in interp.categories:
            writer.writerow([
                cat.adapter, cat.category_name, cat.built_in_category,
                "" if cat.category_id is None else cat.category_id,
                cat.element_count, cat.type_count,
            ])
    return path


def write_parameters_csv(interp: Interpretation, path: Path) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "adapter", "category", "parameter_name", "parameter_kind",
            "storage_type", "read_only", "spec_type_id", "unit_type_id",
            "display_unit", "has_value", "sample_values",
            "expected_input_format", "safely_settable_by_axiom",
            "built_in_parameter_id",
        ])
        for p in interp.properties:
            writer.writerow([
                p.adapter, p.category, p.parameter_name, p.parameter_kind,
                p.storage_type, p.read_only, p.spec_type_id, p.unit_type_id,
                p.display_unit, p.has_value, "; ".join(p.sample_values),
                p.expected_input_format, p.safely_settable_by_axiom,
                p.built_in_parameter_id,
            ])
    return path


def write_candidates_csv(interp: Interpretation, path: Path) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "candidate_id", "capability", "adapter", "category",
            "parameter_name", "parameter_kind", "storage_type",
            "spec_type_id", "unit_type_id", "expected_input_format",
            "safely_settable_by_axiom", "status",
        ])
        for c in interp.candidates:
            writer.writerow([
                c.candidate_id, c.capability, c.adapter, c.category,
                c.parameter_name, c.parameter_kind, c.storage_type,
                c.spec_type_id, c.unit_type_id, c.expected_input_format,
                c.safely_settable_by_axiom, c.status,
            ])
    return path


def write_evidence_jsonl(interp: Interpretation, path: Path) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        for rec in interp.evidence:
            f.write(json.dumps(rec.to_dict(), default=str) + "\n")
    return path


def write_summary_json(
    interp: Interpretation, run_id: str, path: Path, simulate: bool
) -> Path:
    payload = {
        "run_id": run_id,
        "adapter": "revit",
        "mode": "simulate" if simulate else "live",
        "source_model": interp.source_model,
        "scan_mode": interp.scan_mode,
        "object_source": interp.object_source,
        "parameter_source": interp.parameter_source or None,
        "parameter_source_present": interp.parameter_source_present,
        "parameter_rows_total": interp.parameter_rows_total,
        "parameter_rows_joined": interp.parameter_rows_joined,
        "discovery_complete": interp.discovery_complete,
        "discovery_parameter_complete": interp.discovery_complete,
        "warnings": interp.warnings,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": interp.metrics.to_dict(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def write_summary_md(
    interp: Interpretation, run_id: str, path: Path, simulate: bool
) -> Path:
    m = interp.metrics
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Discovery Run Summary",
        "",
        f"**Run ID:** {run_id}  ",
        "**Adapter:** revit  ",
        f"**Mode:** {'simulate' if simulate else 'live'}  ",
        f"**Source Model:** {interp.source_model or '(unknown)'}  ",
        f"**Scan Mode:** {interp.scan_mode or '(unknown)'}  ",
        f"**Object Source:** {interp.object_source or '(unknown)'}  ",
        f"**Parameter Source:** {interp.parameter_source or 'MISSING / not provided'}  ",
        f"**Parameter Rows (joined/total):** "
        f"{interp.parameter_rows_joined if interp.parameter_rows_joined is not None else '-'}"
        f" / "
        f"{interp.parameter_rows_total if interp.parameter_rows_total is not None else '-'}"
        "  ",
        f"**Discovery Complete:** {'yes' if interp.discovery_complete else 'NO (category-only)'}  ",
        f"**Timestamp:** {now_str}  ",
        "",
    ]
    if interp.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in interp.warnings:
            lines.append(f"- **{w}**")
        lines.append("")
    lines += [
        "## Metrics",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Categories discovered | {m.categories_discovered} |",
        f"| Parameters discovered | {m.parameters_discovered} |",
        f"| Writable parameters | {m.writable_parameters} |",
        f"| Read-only parameters | {m.read_only_parameters} |",
        f"| Instance parameters | {m.instance_parameters} |",
        f"| Type parameters | {m.type_parameters} |",
        f"| Safely-settable parameters | {m.safely_settable_parameters} |",
        f"| Candidate capabilities generated | {m.candidate_capabilities_generated} |",
        "",
        "## Notes",
        "",
        "- Read-only discovery only. No model mutation. No candidate execution.",
        "- StorageType alone is not sufficient: Double parameters are only marked",
        "  safely_settable_by_axiom when semantic/unit metadata is present.",
        "- DiscoveryHarness interprets existing InventoryModel exports; it does not scan.",
        "",
        "## Outputs",
        "",
        "- categories.csv",
        "- parameters.csv",
        "- candidate_capabilities.csv",
        "- discovery_evidence.jsonl",
        "- summary.json",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def write_reports(
    interp: Interpretation,
    run_id: str,
    output_dir: Path,
    simulate: bool,
) -> dict[str, Path]:
    """Write all report artifacts; return a name -> path map."""
    run_dir = _run_dir(output_dir, run_id)
    return {
        "categories_csv": write_categories_csv(interp, run_dir / "categories.csv"),
        "parameters_csv": write_parameters_csv(interp, run_dir / "parameters.csv"),
        "candidates_csv": write_candidates_csv(
            interp, run_dir / "candidate_capabilities.csv"
        ),
        "evidence_jsonl": write_evidence_jsonl(
            interp, run_dir / "discovery_evidence.jsonl"
        ),
        "summary_json": write_summary_json(
            interp, run_id, run_dir / "summary.json", simulate
        ),
        "summary_md": write_summary_md(
            interp, run_id, run_dir / "summary.md", simulate
        ),
    }
