"""Layered storage for model inventory runs.

Writes inventory results to three formats:
  1. JSONL — raw append-only event log
  2. SQLite — queryable element/parameter tables
  3. Parquet — durable structured datasets (elements.parquet, parameters.parquet)
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import sessionmaker

# Provenance tag written onto every exported parameter row so downstream
# consumers (DiscoveryHarness) can record where a parameter came from.
PARAMETER_SOURCE = "revit_inventory_model"

# ── Parquet schemas ──────────────────────────────────────────────────

ELEMENT_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("source_model", pa.string()),
    ("element_id", pa.int64()),
    ("unique_id", pa.string()),
    ("category", pa.string()),
    ("built_in_category", pa.string()),
    ("class_name", pa.string()),
    ("name", pa.string()),
    ("family_name", pa.string()),
    ("type_name", pa.string()),
    ("level_name", pa.string()),
    ("level_id", pa.int64()),
    ("workset_name", pa.string()),
    ("is_type", pa.bool_()),
    ("parameter_count", pa.int32()),
])

# Per-element parameter export. element_id is the STABLE JOIN KEY back to
# elements.parquet / elements.jsonl (same run_id, int64). Identity + value
# contract + provenance fields are denormalized onto each row so DiscoveryHarness
# can populate ProductPropertyRegistry, candidate capabilities, and the value
# contract directly. See docs/architecture/inventorymodel-parameter-discovery-contract.md.
PARAMETER_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    # ── identity / join ──
    ("element_id", pa.int64()),          # STABLE JOIN KEY -> elements.element_id
    ("category", pa.string()),           # denormalized parent element category
    ("built_in_category", pa.string()),  # denormalized OST_* where available
    ("param_name", pa.string()),
    ("built_in_parameter_id", pa.string()),
    # ── ownership ──
    ("is_instance_param", pa.bool_()),
    ("is_type_param", pa.bool_()),
    # ── storage / access ──
    ("storage_type", pa.string()),       # String | Integer | Double | ElementId
    ("is_read_only", pa.bool_()),
    # ── value ──
    ("value_string", pa.string()),
    ("value_number", pa.float64()),
    ("value_integer", pa.int64()),
    ("value_element_id", pa.int64()),
    # ── value contract (semantic/unit metadata) ──
    ("spec_type_id", pa.string()),
    ("forge_type_id", pa.string()),
    ("unit_type_id", pa.string()),
    ("display_unit", pa.string()),
    ("format_options", pa.string()),
    ("parameter_group", pa.string()),
    # ── discovery metadata ──
    ("parameter_source", pa.string()),
    ("discovered_at", pa.string()),
])

PARAMETER_SCHEMA_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("source_model", pa.string()),
    ("scan_mode", pa.string()),
    ("category", pa.string()),
    ("class_name", pa.string()),
    ("parameter_name", pa.string()),
    ("storage_type", pa.string()),
    ("built_in_parameter_id", pa.string()),
    ("is_read_only", pa.bool_()),
    ("is_instance_param", pa.bool_()),
    ("is_type_param", pa.bool_()),
    ("observed_count", pa.int32()),
    ("observed_on_categories", pa.string()),
    ("observed_on_classes", pa.string()),
    ("data_type_id", pa.string()),
    ("data_type_label", pa.string()),
    ("group_type_id", pa.string()),
    ("group_type_label", pa.string()),
    ("is_measurable_spec", pa.bool_()),
    ("unit_type_id", pa.string()),
    ("unit_label", pa.string()),
    ("discipline_label", pa.string()),
])


def _element_to_flat(elem: dict, run_id: str = "", source_model: str = "") -> dict:
    """Flatten an element dict for the elements Parquet table."""
    return {
        "run_id": run_id,
        "source_model": source_model,
        "element_id": elem.get("ElementId", 0),
        "unique_id": elem.get("UniqueId", ""),
        "category": elem.get("Category", ""),
        "built_in_category": elem.get("BuiltInCategory", ""),
        "class_name": elem.get("ClassName", ""),
        "name": elem.get("Name", ""),
        "family_name": elem.get("FamilyName", ""),
        "type_name": elem.get("TypeName", ""),
        "level_name": elem.get("LevelName", ""),
        "level_id": elem.get("LevelId", 0),
        "workset_name": elem.get("WorksetName", ""),
        "is_type": elem.get("IsType", False),
        "parameter_count": len(elem.get("Parameters", [])),
    }


def _param_first(param: dict, *keys, default=None):
    """Return the first present, non-None value among ``keys`` in ``param``."""
    for k in keys:
        if k in param and param[k] is not None:
            return param[k]
    return default


def _coerce_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _param_to_flat(
    element_id: int,
    param: dict,
    run_id: str = "",
    is_instance_param: bool = True,
    category: str = "",
    built_in_category: str = "",
    discovered_at: str = "",
    parameter_source: str = PARAMETER_SOURCE,
) -> dict:
    """Flatten a parameter dict for the parameters Parquet table.

    ``element_id`` is the stable join key back to the elements export. Identity,
    value-contract and provenance fields are denormalized so DiscoveryHarness can
    consume the parameter row directly. Field names accept both the C# add-in's
    PascalCase keys and pre-flattened snake_case keys.
    """
    return {
        "run_id": run_id,
        # identity / join
        "element_id": element_id,
        "category": category,
        "built_in_category": built_in_category,
        "param_name": _param_first(param, "Name", "param_name", default=""),
        "built_in_parameter_id": _param_first(
            param, "BuiltInParameterId", "built_in_parameter_id", default=""),
        # ownership
        "is_instance_param": is_instance_param,
        "is_type_param": not is_instance_param,
        # storage / access
        "storage_type": _param_first(param, "StorageType", "storage_type", default=""),
        "is_read_only": bool(_param_first(
            param, "IsReadOnly", "is_read_only", default=False)),
        # value
        "value_string": _param_first(param, "ValueString", "value_string", default=""),
        "value_number": _param_first(param, "ValueDouble", "value_number"),
        "value_integer": _coerce_int(_param_first(param, "ValueInt", "value_integer")),
        "value_element_id": _coerce_int(_param_first(
            param, "ValueElementId", "value_element_id")),
        # value contract
        "spec_type_id": _param_first(
            param, "SpecTypeId", "DataTypeId", "spec_type_id", default=""),
        "forge_type_id": _param_first(
            param, "ForgeTypeId", "forge_type_id", default=""),
        "unit_type_id": _param_first(param, "UnitTypeId", "unit_type_id", default=""),
        "display_unit": _param_first(
            param, "DisplayUnit", "UnitLabel", "display_unit", default=""),
        "format_options": _param_first(
            param, "FormatOptions", "format_options", default=""),
        "parameter_group": _param_first(
            param, "ParameterGroup", "parameter_group", default=""),
        # discovery metadata
        "parameter_source": parameter_source,
        "discovered_at": discovered_at,
    }


def write_jsonl(elements: list[dict], path: Path) -> Path:
    """Write raw element data to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(json.dumps(elem, default=str) + "\n")
    return path


def write_elements_parquet(
    elements: list[dict],
    path: Path,
    run_id: str = "",
    source_model: str = "",
) -> Path:
    """Write elements to a Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_element_to_flat(e, run_id=run_id, source_model=source_model) for e in elements]
    if not rows:
        rows = [dict.fromkeys(ELEMENT_PARQUET_SCHEMA.names)]
    arrays = {}
    for field in ELEMENT_PARQUET_SCHEMA:
        values = [row.get(field.name) for row in rows]
        arrays[field.name] = values
    table = pa.table(arrays, schema=ELEMENT_PARQUET_SCHEMA)
    pq.write_table(table, str(path))
    return path


def collect_parameter_rows(
    elements: list[dict],
    run_id: str = "",
    discovered_at: str = "",
) -> list[dict]:
    """Flatten every element's parameters into join-ready parameter rows.

    Each row carries the stable join key (``element_id``), the denormalized
    parent category, ownership (instance/type), the value contract metadata and
    provenance. Shared by the Parquet / CSV / JSONL parameter writers so all
    three exports stay identical.
    """
    if not discovered_at:
        discovered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    for elem in elements:
        eid = elem.get("ElementId", 0)
        is_instance = not elem.get("IsType", False)
        category = elem.get("Category", "")
        built_in_category = elem.get("BuiltInCategory", "")
        for param in elem.get("Parameters", []) or []:
            rows.append(_param_to_flat(
                eid, param,
                run_id=run_id,
                is_instance_param=is_instance,
                category=category,
                built_in_category=built_in_category,
                discovered_at=discovered_at,
            ))
    return rows


def write_parameters_parquet(
    elements: list[dict],
    path: Path,
    run_id: str = "",
    discovered_at: str = "",
) -> Path:
    """Write all element parameters to a Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = collect_parameter_rows(elements, run_id=run_id, discovered_at=discovered_at)
    if not rows:
        rows = [dict.fromkeys(PARAMETER_PARQUET_SCHEMA.names)]
    arrays = {}
    for field in PARAMETER_PARQUET_SCHEMA:
        values = [row.get(field.name) for row in rows]
        arrays[field.name] = values
    table = pa.table(arrays, schema=PARAMETER_PARQUET_SCHEMA)
    pq.write_table(table, str(path))
    return path


def write_parameters_jsonl(
    elements: list[dict],
    path: Path,
    run_id: str = "",
    discovered_at: str = "",
) -> Path:
    """Write all element parameters to a JSONL file (one row per parameter)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = collect_parameter_rows(elements, run_id=run_id, discovered_at=discovered_at)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    return path


def write_parameters_csv(
    elements: list[dict],
    path: Path,
    run_id: str = "",
    discovered_at: str = "",
) -> Path:
    """Write all element parameters to a CSV file (one row per parameter)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = collect_parameter_rows(elements, run_id=run_id, discovered_at=discovered_at)
    columns = list(PARAMETER_PARQUET_SCHEMA.names)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return path


def write_to_sqlite(
    elements: list[dict],
    run_id: str,
    session_factory: Optional[sessionmaker] = None,
    source_model: str = "",
) -> None:
    """Persist inventory data to SQLite tables."""
    if session_factory is None:
        return
    try:
        from axiom_core.database import get_session
        from axiom_core.models import InventoryElementRow, InventoryParameterRow

        with get_session(session_factory) as session:
            for elem in elements:
                is_type = elem.get("IsType", False)
                elem_row = InventoryElementRow(
                    run_id=run_id,
                    source_model=source_model,
                    element_id=elem.get("ElementId", 0),
                    unique_id=elem.get("UniqueId", ""),
                    category=elem.get("Category", ""),
                    class_name=elem.get("ClassName", ""),
                    name=elem.get("Name", ""),
                    family_name=elem.get("FamilyName", ""),
                    type_name=elem.get("TypeName", ""),
                    level_name=elem.get("LevelName", ""),
                    level_id=elem.get("LevelId", 0),
                    workset_name=elem.get("WorksetName", ""),
                    is_type=is_type,
                )
                session.add(elem_row)

                for param in elem.get("Parameters", []):
                    param_row = InventoryParameterRow(
                        run_id=run_id,
                        element_id=elem.get("ElementId", 0),
                        param_name=param.get("Name", ""),
                        storage_type=param.get("StorageType", ""),
                        value_string=param.get("ValueString", ""),
                        value_number=param.get("ValueDouble"),
                        value_integer=param.get("ValueInt"),
                        built_in_parameter_id=param.get("BuiltInParameterId", ""),
                        is_read_only=param.get("IsReadOnly", False),
                        is_instance_param=not is_type,
                        parameter_group=param.get("ParameterGroup", ""),
                    )
                    session.add(param_row)
    except Exception:
        pass


def write_parameter_schema_jsonl(
    param_defs: list[dict], path: Path,
) -> Path:
    """Write parameter schema definitions to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in param_defs:
            f.write(json.dumps(p, default=str) + "\n")
    return path


def write_parameter_schema_parquet(
    param_defs: list[dict],
    path: Path,
    run_id: str = "",
    source_model: str = "",
    scan_mode: str = "category_parameter_schema",
) -> Path:
    """Write parameter schema definitions to a Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for p in param_defs:
        cat_list = p.get("ObservedOnCategories", [])
        cls_list = p.get("ObservedOnClasses", [])
        cat_str = ", ".join(cat_list) if isinstance(cat_list, list) else str(cat_list)
        cls_str = ", ".join(cls_list) if isinstance(cls_list, list) else str(cls_list)
        rows.append({
            "run_id": run_id,
            "source_model": source_model,
            "scan_mode": scan_mode,
            "category": cat_str,
            "class_name": cls_str,
            "parameter_name": p.get("ParameterName", ""),
            "storage_type": p.get("StorageType", ""),
            "built_in_parameter_id": p.get("BuiltInParameterId", ""),
            "is_read_only": p.get("IsReadOnly", False),
            "is_instance_param": p.get("IsInstanceParam", False),
            "is_type_param": p.get("IsTypeParam", False),
            "observed_count": p.get("ObservedCount", 0),
            "observed_on_categories": cat_str,
            "observed_on_classes": cls_str,
            "data_type_id": p.get("DataTypeId", ""),
            "data_type_label": p.get("DataTypeLabel", ""),
            "group_type_id": p.get("GroupTypeId", ""),
            "group_type_label": p.get("GroupTypeLabel", ""),
            "is_measurable_spec": p.get("IsMeasurableSpec", False),
            "unit_type_id": p.get("UnitTypeId", ""),
            "unit_label": p.get("UnitLabel", ""),
            "discipline_label": p.get("DisciplineLabel", ""),
        })
    if not rows:
        rows = [dict.fromkeys(PARAMETER_SCHEMA_PARQUET_SCHEMA.names)]
    arrays = {}
    for field in PARAMETER_SCHEMA_PARQUET_SCHEMA:
        values = [row.get(field.name) for row in rows]
        arrays[field.name] = values
    table = pa.table(arrays, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
    pq.write_table(table, str(path))
    return path


def persist_parameter_schema(
    param_defs: list[dict],
    output_dir: Path,
    run_id: str,
    source_model: str = "",
    scan_mode: str = "category_parameter_schema",
) -> dict[str, Path]:
    """Persist parameter schema definitions to JSONL, Parquet, and summary."""
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    paths["jsonl"] = write_parameter_schema_jsonl(
        param_defs, run_dir / "parameter_schema.jsonl",
    )
    paths["parquet"] = write_parameter_schema_parquet(
        param_defs, run_dir / "parameter_schema.parquet",
        run_id=run_id, source_model=source_model, scan_mode=scan_mode,
    )
    return paths


OBJECT_REGISTRY_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("source_model", pa.string()),
    ("element_id", pa.int64()),
    ("category", pa.string()),
    ("class_name", pa.string()),
    ("name", pa.string()),
    ("family_name", pa.string()),
    ("type_name", pa.string()),
    ("level_name", pa.string()),
    ("is_type", pa.bool_()),
])


def persist_object_registry(
    elements: list[dict],
    output_dir: Path,
    run_id: str,
    source_model: str = "",
) -> dict[str, Path]:
    """Persist object schema elements as an object registry candidate."""
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    # JSONL
    jsonl_path = run_dir / "revit_object_registry.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(json.dumps(elem, default=str) + "\n")
    paths["jsonl"] = jsonl_path

    # Parquet
    parquet_path = run_dir / "revit_object_registry.parquet"
    rows: list[dict] = []
    for elem in elements:
        rows.append({
            "run_id": run_id,
            "source_model": source_model,
            "element_id": elem.get("ElementId", 0),
            "category": elem.get("Category", ""),
            "class_name": elem.get("ClassName", ""),
            "name": elem.get("Name", ""),
            "family_name": elem.get("FamilyName", ""),
            "type_name": elem.get("TypeName", ""),
            "level_name": elem.get("LevelName", ""),
            "is_type": elem.get("IsType", False),
        })
    if not rows:
        rows = [dict.fromkeys(OBJECT_REGISTRY_PARQUET_SCHEMA.names)]
    arrays = {}
    for fld in OBJECT_REGISTRY_PARQUET_SCHEMA:
        arrays[fld.name] = [r.get(fld.name) for r in rows]
    table = pa.table(arrays, schema=OBJECT_REGISTRY_PARQUET_SCHEMA)
    pq.write_table(table, str(parquet_path))
    paths["parquet"] = parquet_path

    return paths


def persist_inventory(
    elements: list[dict],
    output_dir: Path,
    run_id: str,
    session_factory: Optional[sessionmaker] = None,
    source_model: str = "",
) -> dict[str, Path]:
    """Write inventory to all three storage layers.

    Returns dict of {format: path} for the files written.
    """
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    discovered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    paths: dict[str, Path] = {}
    paths["jsonl"] = write_jsonl(elements, run_dir / "elements.jsonl")
    paths["elements_parquet"] = write_elements_parquet(
        elements, run_dir / "elements.parquet",
        run_id=run_id, source_model=source_model,
    )
    paths["parameters_parquet"] = write_parameters_parquet(
        elements, run_dir / "parameters.parquet",
        run_id=run_id, discovered_at=discovered_at,
    )
    paths["parameters_csv"] = write_parameters_csv(
        elements, run_dir / "parameters.csv",
        run_id=run_id, discovered_at=discovered_at,
    )
    paths["parameters_jsonl"] = write_parameters_jsonl(
        elements, run_dir / "parameters.jsonl",
        run_id=run_id, discovered_at=discovered_at,
    )

    write_to_sqlite(elements, run_id, session_factory, source_model=source_model)

    return paths
