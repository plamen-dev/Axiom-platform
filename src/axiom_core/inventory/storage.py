"""Layered storage for model inventory runs.

Writes inventory results to three formats:
  1. JSONL — raw append-only event log
  2. SQLite — queryable element/parameter tables
  3. Parquet — durable structured datasets (elements.parquet, parameters.parquet)
"""

import json
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import sessionmaker

# ── Parquet schemas ──────────────────────────────────────────────────

ELEMENT_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("source_model", pa.string()),
    ("element_id", pa.int64()),
    ("unique_id", pa.string()),
    ("category", pa.string()),
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

PARAMETER_PARQUET_SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("element_id", pa.int64()),
    ("param_name", pa.string()),
    ("storage_type", pa.string()),
    ("value_string", pa.string()),
    ("value_number", pa.float64()),
    ("value_integer", pa.int64()),
    ("built_in_parameter_id", pa.string()),
    ("is_read_only", pa.bool_()),
    ("is_instance_param", pa.bool_()),
    ("parameter_group", pa.string()),
])


def _element_to_flat(elem: dict, run_id: str = "", source_model: str = "") -> dict:
    """Flatten an element dict for the elements Parquet table."""
    return {
        "run_id": run_id,
        "source_model": source_model,
        "element_id": elem.get("ElementId", 0),
        "unique_id": elem.get("UniqueId", ""),
        "category": elem.get("Category", ""),
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


def _param_to_flat(
    element_id: int,
    param: dict,
    run_id: str = "",
    is_instance_param: bool = True,
) -> dict:
    """Flatten a parameter dict for the parameters Parquet table."""
    return {
        "run_id": run_id,
        "element_id": element_id,
        "param_name": param.get("Name", ""),
        "storage_type": param.get("StorageType", ""),
        "value_string": param.get("ValueString", ""),
        "value_number": param.get("ValueDouble"),
        "value_integer": param.get("ValueInt"),
        "built_in_parameter_id": param.get("BuiltInParameterId", ""),
        "is_read_only": param.get("IsReadOnly", False),
        "is_instance_param": is_instance_param,
        "parameter_group": param.get("ParameterGroup", ""),
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


def write_parameters_parquet(
    elements: list[dict],
    path: Path,
    run_id: str = "",
) -> Path:
    """Write all element parameters to a Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for elem in elements:
        eid = elem.get("ElementId", 0)
        is_instance = not elem.get("IsType", False)
        for param in elem.get("Parameters", []):
            rows.append(_param_to_flat(eid, param, run_id=run_id, is_instance_param=is_instance))
    if not rows:
        rows = [dict.fromkeys(PARAMETER_PARQUET_SCHEMA.names)]
    arrays = {}
    for field in PARAMETER_PARQUET_SCHEMA:
        values = [row.get(field.name) for row in rows]
        arrays[field.name] = values
    table = pa.table(arrays, schema=PARAMETER_PARQUET_SCHEMA)
    pq.write_table(table, str(path))
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

    paths: dict[str, Path] = {}
    paths["jsonl"] = write_jsonl(elements, run_dir / "elements.jsonl")
    paths["elements_parquet"] = write_elements_parquet(
        elements, run_dir / "elements.parquet",
        run_id=run_id, source_model=source_model,
    )
    paths["parameters_parquet"] = write_parameters_parquet(
        elements, run_dir / "parameters.parquet",
        run_id=run_id,
    )

    write_to_sqlite(elements, run_id, session_factory, source_model=source_model)

    return paths
