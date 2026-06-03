"""DiscoveryHarness v1 - orchestrates pure interpretation + optional persistence.

Layering (non-negotiable):

    Revit Model -> InventoryModel (raw facts/exports)
                -> DiscoveryHarness (interpreted facts)
                -> Registries + Evidence + Candidate Capabilities

The harness NEVER scans or extracts. It loads an already-produced InventoryModel
export, interprets it (``interpret_export``), optionally persists the interpreted
facts into the shared SQLite registries (PR #1 patterns), and writes the
human-reviewable report bundle. ``session_factory=None`` skips persistence so the
flow is fully testable without a database.

Two modes:
  - simulate: uses a small deterministic built-in export (off-Windows / CI)
  - live: reads the export InventoryModel produced (``inventory_export_path``)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import sessionmaker

from . import registries
from .interpret import Interpretation, interpret_export
from .reports import write_reports

DEFAULT_OUTPUT_DIR = "artifacts/discovery_runs"

# Deterministic built-in export for simulate mode. Mirrors the shape of an
# InventoryModel element-level export. Includes: a writable String (safe), a
# read-only String (no candidate), a Double WITHOUT unit metadata (candidate but
# NOT safely settable), a Double WITH unit metadata (safely settable), an Integer
# (safe), and a type-level parameter so instance vs type labeling is exercised.
SIMULATED_EXPORT: dict = {
    "document_title": "SimulatedModel.rvt",
    "scan_mode": "category_parameter_schema",
    "elements": [
        {
            "ElementId": 1001,
            "Category": "Walls",
            "BuiltInCategory": "OST_Walls",
            "CategoryId": -2000011,
            "IsType": False,
            "Parameters": [
                {
                    "Name": "Comments",
                    "StorageType": "String",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS",
                    "ValueString": "Exterior",
                },
                {
                    "Name": "Area",
                    "StorageType": "Double",
                    "IsReadOnly": True,
                    "BuiltInParameterId": "HOST_AREA_COMPUTED",
                    "ValueDouble": 12.5,
                },
                {
                    "Name": "Unconnected Height",
                    "StorageType": "Double",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "WALL_USER_HEIGHT_PARAM",
                    "ValueDouble": 3.0,
                    "SpecTypeId": "autodesk.spec.aec:length-2.0.0",
                    "UnitTypeId": "autodesk.unit.unit:millimeters-1.0.1",
                    "DisplayUnit": "mm",
                },
                {
                    "Name": "Mark",
                    "StorageType": "Integer",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "ALL_MODEL_MARK",
                    "ValueInt": 7,
                },
            ],
        },
        {
            "ElementId": 2001,
            "Category": "Walls",
            "BuiltInCategory": "OST_Walls",
            "CategoryId": -2000011,
            "IsType": True,
            "Parameters": [
                {
                    "Name": "Type Comments",
                    "StorageType": "String",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "ALL_MODEL_TYPE_COMMENTS",
                    "ValueString": "Generic - 200mm",
                },
                {
                    "Name": "Fire Rating",
                    "StorageType": "String",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "FIRE_RATING",
                    "ValueString": "2 HR",
                },
            ],
        },
        {
            "ElementId": 3001,
            "Category": "Doors",
            "BuiltInCategory": "OST_Doors",
            "CategoryId": -2000023,
            "IsType": False,
            "Parameters": [
                {
                    "Name": "Comments",
                    "StorageType": "String",
                    "IsReadOnly": False,
                    "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS",
                    "ValueString": "",
                },
            ],
        },
    ],
}


@dataclass
class DiscoveryRunResult:
    run_id: str
    mode: str
    output_dir: str
    metrics: dict
    artifacts: dict[str, str]
    persisted: dict[str, dict] = field(default_factory=dict)
    source_model: str = ""
    scan_mode: str = ""
    object_source: str = ""
    parameter_source: str = ""
    parameter_rows_total: Optional[int] = None
    parameter_rows_joined: Optional[int] = None
    discovery_complete: bool = True
    warnings: list[str] = field(default_factory=list)


def _default_run_id() -> str:
    return "drun_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


class DiscoveryInputError(ValueError):
    """Raised for unreadable / unsupported InventoryModel export inputs.

    Subclasses ValueError so the CLI surfaces it as a clean, human-readable
    error (exit 2) rather than a raw parser traceback.
    """


# Supported InventoryModel export inputs (element-level):
#   - <name>.json  : InventoryModel handoff export (a JSON object with an
#                    "elements" list), or a JSON array of element records
#   - elements.jsonl / revit_object_registry.jsonl : one element record per line
#
# NOT a discovery substrate (rejected with guidance):
#   - parameters.jsonl / parameter_schema.jsonl : parameter-SCHEMA rows, a
#     different shape (no per-element "Parameters"); point at elements.jsonl.
SUPPORTED_EXPORT_HINT = (
    "Supported InventoryModel exports: a handoff .json object (with an "
    "'elements' list) or an element-level .jsonl (e.g. elements.jsonl, one "
    "element record per line). parameters.jsonl / parameter_schema.jsonl are "
    "parameter-schema datasets, not element exports - point "
    "--inventory-export-path at elements.jsonl (or the handoff .json) instead."
)

# Keys that identify an element-level record.
_ELEMENT_KEYS = ("Parameters", "ElementId", "IsType")
# Keys that identify a parameter-SCHEMA record (the wrong shape for discovery).
_PARAM_SCHEMA_KEYS = ("ParameterName", "parameter_name", "IsInstanceParam")


def _parse_jsonl_records(p: Path) -> list[dict]:
    """Parse a JSONL file (one JSON object per line) into a list of dicts.

    Blank lines are skipped. A malformed line yields a clear, line-numbered
    error rather than a raw json exception.
    """
    records: list[dict] = []
    with open(p, encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DiscoveryInputError(
                    f"Invalid JSON on line {lineno} of {p.name}: {exc.msg}. "
                    "Expected one JSON object per line (JSONL)."
                ) from exc
            if not isinstance(obj, dict):
                raise DiscoveryInputError(
                    f"Line {lineno} of {p.name} is not a JSON object "
                    f"(got {type(obj).__name__}). {SUPPORTED_EXPORT_HINT}"
                )
            records.append(obj)
    return records


def _classify_records(records: list[dict], source_name: str) -> dict:
    """Wrap a list of element records into an export dict, or reject the shape."""
    sample = next((r for r in records if r), None)
    if sample is None:
        # Empty file: valid summary-style input (zero elements).
        return {"elements": []}
    if any(k in sample for k in _ELEMENT_KEYS) or "Category" in sample:
        return {"elements": records}
    if any(k in sample for k in _PARAM_SCHEMA_KEYS):
        raise DiscoveryInputError(
            f"{source_name} looks like a parameter-SCHEMA dataset, not an "
            f"element export. {SUPPORTED_EXPORT_HINT}"
        )
    raise DiscoveryInputError(
        f"Unrecognized record shape in {source_name}. {SUPPORTED_EXPORT_HINT}"
    )


# --- InventoryModel run-folder contract --------------------------------------
# A real InventoryModel run folder (artifacts/model_inventory_runs/<run_id>/)
# splits the data across files: elements live in elements.jsonl / elements.parquet
# (objects/categories) while per-element parameters live in parameters.parquet.
# elements.jsonl alone therefore yields categories but ZERO parameters, so a
# folder is read as a whole and the parameter table is joined back onto elements.
_FOLDER_ELEMENT_JSONL = "elements.jsonl"
_FOLDER_ELEMENT_PARQUET = "elements.parquet"
_FOLDER_PARAM_PARQUET = "parameters.parquet"
_FOLDER_RUN_METADATA = "run_metadata.json"


def _read_parquet_records(p: Path) -> list[dict]:
    """Read a Parquet file into a list of row dicts (lazy pyarrow import)."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - pyarrow is a hard dep
        raise DiscoveryInputError(
            f"Reading {p.name} requires pyarrow, which is not installed."
        ) from exc
    try:
        return pq.read_table(p).to_pylist()
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        raise DiscoveryInputError(
            f"Could not read Parquet file {p.name}: {exc}"
        ) from exc


def _normalize_element(rec: dict) -> dict:
    """Normalize an element record (PascalCase export or snake_case parquet).

    Returns a dict using the export naming the interpreter expects, preserving
    any already-embedded ``Parameters`` list.
    """
    def pick(*keys, default=None):
        for k in keys:
            if k in rec and rec[k] is not None:
                return rec[k]
        return default

    return {
        "ElementId": pick("ElementId", "element_id", default=None),
        "Category": pick("Category", "category", default=""),
        "BuiltInCategory": pick("BuiltInCategory", "built_in_category", default=""),
        "CategoryId": pick("CategoryId", "category_id", default=None),
        "IsType": bool(pick("IsType", "is_type", default=False)),
        "Parameters": list(pick("Parameters", "parameters", default=[]) or []),
    }


def _param_row_to_export(row: dict) -> dict:
    """Map a parameters.parquet row to the parameter dict the interpreter reads.

    parameters.parquet carries no unit/spec metadata, so a Double parameter
    correctly remains NOT safely_settable_by_axiom (value contract preserved).
    """
    return {
        "Name": row.get("param_name") or row.get("Name") or "",
        "StorageType": row.get("storage_type") or row.get("StorageType") or "",
        "IsReadOnly": bool(row.get("is_read_only", row.get("IsReadOnly", False))),
        "BuiltInParameterId": (
            row.get("built_in_parameter_id") or row.get("BuiltInParameterId") or ""
        ),
        "ValueString": row.get("value_string", row.get("ValueString")),
        "ValueDouble": row.get("value_number", row.get("ValueDouble")),
        "ValueInt": row.get("value_integer", row.get("ValueInt")),
        "ParameterGroup": row.get("parameter_group") or row.get("ParameterGroup") or "",
    }


def _id_variants(eid: object) -> list[object]:
    """Comparable representations of an element id (handles int/str mismatch)."""
    if eid is None:
        return []
    variants: list[object] = [eid, str(eid)]
    try:
        variants.append(int(eid))
    except (TypeError, ValueError):
        pass
    return variants


def _attach_parameters(
    elements: list[dict], param_rows: list[dict]
) -> tuple[int, int]:
    """Join parameter rows onto their elements (by element id), in place.

    Returns (rows_total, rows_joined). Matching tolerates int/str id mismatch.
    """
    by_id: dict[object, dict] = {}
    for elem in elements:
        eid = elem.get("ElementId")
        if eid is None:
            continue
        elem["Parameters"] = []  # parquet is the authoritative parameter source
        for key in _id_variants(eid):
            by_id[key] = elem
    joined = 0
    for row in param_rows:
        eid = row.get("element_id", row.get("ElementId"))
        elem = None
        for key in _id_variants(eid):
            elem = by_id.get(key)
            if elem is not None:
                break
        if elem is not None:
            elem["Parameters"].append(_param_row_to_export(row))
            joined += 1
    return len(param_rows), joined


def _load_run_folder(folder: Path) -> dict:
    """Load an InventoryModel run folder, joining objects + parameters.

    Auto-detects elements.jsonl / elements.parquet (objects/categories),
    parameters.parquet (parameters/properties), and run_metadata.json
    (provenance). Read-only; never triggers a scan.
    """
    elements_jsonl = folder / _FOLDER_ELEMENT_JSONL
    elements_parquet = folder / _FOLDER_ELEMENT_PARQUET
    param_parquet = folder / _FOLDER_PARAM_PARQUET

    if elements_jsonl.exists():
        raw_elements = _parse_jsonl_records(elements_jsonl)
        object_source = _FOLDER_ELEMENT_JSONL
    elif elements_parquet.exists():
        raw_elements = _read_parquet_records(elements_parquet)
        object_source = _FOLDER_ELEMENT_PARQUET
    else:
        raise DiscoveryInputError(
            f"No element export found in {folder.name} (expected "
            f"{_FOLDER_ELEMENT_JSONL} or {_FOLDER_ELEMENT_PARQUET}). "
            f"{SUPPORTED_EXPORT_HINT}"
        )

    elements = [_normalize_element(r) for r in raw_elements]

    parameter_source = ""
    rows_total: int | None = None
    rows_joined: int | None = None
    if param_parquet.exists():
        param_rows = _read_parquet_records(param_parquet)
        rows_total, rows_joined = _attach_parameters(elements, param_rows)
        parameter_source = _FOLDER_PARAM_PARQUET
        # If the join produced nothing but the table has rows, the chosen object
        # source may not share element ids with parameters.parquet. Retry the
        # join against elements.parquet (same writer -> guaranteed id match).
        if (
            rows_total > 0
            and rows_joined == 0
            and elements_parquet.exists()
            and object_source != _FOLDER_ELEMENT_PARQUET
        ):
            alt = [_normalize_element(r) for r in _read_parquet_records(elements_parquet)]
            alt_total, alt_joined = _attach_parameters(alt, param_rows)
            if alt_joined > 0:
                elements = alt
                object_source = _FOLDER_ELEMENT_PARQUET
                rows_total, rows_joined = alt_total, alt_joined
    elif any(e.get("Parameters") for e in elements):
        # elements.jsonl carried embedded parameters (older handoff shape).
        parameter_source = f"{object_source} (embedded)"

    document_title, scan_mode = "", ""
    meta_path = folder / _FOLDER_RUN_METADATA
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8-sig") as f:
                meta = json.load(f)
            if isinstance(meta, dict):
                document_title = (
                    meta.get("source_model") or meta.get("document_title") or ""
                )
                scan_mode = meta.get("scan_mode") or meta.get("chunk_by") or ""
        except (json.JSONDecodeError, OSError):
            pass  # provenance is best-effort; never fail the run on it

    return {
        "elements": elements,
        "document_title": document_title,
        "scan_mode": scan_mode,
        "object_source": object_source,
        "parameter_source": parameter_source,
        "parameter_rows_total": rows_total,
        "parameter_rows_joined": rows_joined,
    }


def load_inventory_export(path: str | Path) -> dict:
    """Load an InventoryModel export. Read-only; never triggers a scan.

    Accepts:
      - an InventoryModel run FOLDER (auto-detects elements.jsonl/elements.parquet
        + parameters.parquet + run_metadata.json),
      - the handoff JSON object, a JSON array of element records, or an
        element-level JSONL file (elements.jsonl).

    Unsupported shapes (e.g. parameters.jsonl) are rejected with a clear,
    human-readable error.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Inventory export not found: {p}")

    if p.is_dir():
        return _load_run_folder(p)

    suffix = p.suffix.lower()

    if suffix == ".jsonl":
        export = _classify_records(_parse_jsonl_records(p), p.name)
        export.setdefault("object_source", p.name)
        return export

    # .json (or unknown extension): try a single JSON document first.
    with open(p, encoding="utf-8-sig") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # A common mistake: pointing at a .jsonl file (or JSONL content) that
        # only parses line-by-line. Detect and give actionable guidance.
        nonblank = [ln for ln in raw.splitlines() if ln.strip()]
        if len(nonblank) > 1:
            raise DiscoveryInputError(
                f"{p.name} is not a single JSON document (parse error: "
                f"{exc.msg} at line {exc.lineno}). It looks like JSONL (one "
                f"JSON object per line). {SUPPORTED_EXPORT_HINT}"
            ) from exc
        raise DiscoveryInputError(
            f"Could not parse {p.name} as JSON: {exc.msg} at line {exc.lineno}. "
            f"{SUPPORTED_EXPORT_HINT}"
        ) from exc

    if isinstance(data, dict):
        data.setdefault("object_source", p.name)
        return data
    if isinstance(data, list):
        export = _classify_records(data, p.name)
        export.setdefault("object_source", p.name)
        return export
    raise DiscoveryInputError(
        f"{p.name} must be a JSON object or array, got {type(data).__name__}. "
        f"{SUPPORTED_EXPORT_HINT}"
    )


def run_discovery(
    *,
    run_id: Optional[str] = None,
    simulate: bool = False,
    inventory_export_path: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    session_factory: Optional[sessionmaker] = None,
) -> DiscoveryRunResult:
    """Interpret an InventoryModel export into registries/evidence/reports.

    - simulate=True with no path uses the built-in deterministic export.
    - live mode requires ``inventory_export_path`` (InventoryModel's output).
    - persistence is optional (session_factory=None -> file artifacts only).
    """
    run_id = run_id or _default_run_id()

    # An explicit export path always wins and means the data came from a real
    # InventoryModel export, so provenance is "live" even if simulate was also
    # set. Deriving the mode from the actual source (not just the flag) keeps
    # summary.json / summary.md / evidence honest.
    if inventory_export_path:
        export = load_inventory_export(inventory_export_path)
        is_simulated = False
    elif simulate:
        export = SIMULATED_EXPORT
        is_simulated = True
    else:
        raise ValueError(
            "live discovery requires --inventory-export-path "
            "(InventoryModel must produce the export first); use --simulate for "
            "the built-in deterministic export."
        )

    interp: Interpretation = interpret_export(export, run_id)

    persisted = registries.persist_all(
        session_factory,
        interp.categories,
        interp.properties,
        interp.candidates,
        run_id,
    )

    artifacts = write_reports(
        interp, run_id, Path(output_dir), simulate=is_simulated
    )

    return DiscoveryRunResult(
        run_id=run_id,
        mode="simulate" if is_simulated else "live",
        output_dir=str(Path(output_dir) / run_id),
        metrics=interp.metrics.to_dict(),
        artifacts={k: str(v) for k, v in artifacts.items()},
        persisted=persisted or {},
        source_model=interp.source_model,
        scan_mode=interp.scan_mode,
        object_source=interp.object_source,
        parameter_source=interp.parameter_source,
        parameter_rows_total=interp.parameter_rows_total,
        parameter_rows_joined=interp.parameter_rows_joined,
        discovery_complete=interp.discovery_complete,
        warnings=interp.warnings,
    )
