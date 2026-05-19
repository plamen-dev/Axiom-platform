"""Layered storage for grid test harness runs.

Writes results to three formats:
  1. JSONL — raw append-only event log
  2. SQLite — queryable local execution history (prompt_executions table)
  3. Parquet — durable structured datasets for regression analysis
"""

import json
from pathlib import Path
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import sessionmaker

from axiom_core.testing.models import GridTestResult

# ── Parquet schema ───────────────────────────────────────────────────
_PARQUET_SCHEMA = pa.schema([
    ("test_id", pa.string()),
    ("prompt", pa.string()),
    ("mode", pa.string()),
    ("git_commit", pa.string()),
    ("git_branch", pa.string()),
    ("timestamp", pa.string()),
    ("resolved_capability", pa.string()),
    ("resolved_parameters", pa.string()),  # JSON string
    ("assumptions", pa.string()),  # JSON string
    ("pipe_available", pa.bool_()),
    ("status", pa.string()),
    ("created_count", pa.int32()),
    ("created_ids", pa.string()),  # JSON string
    ("warnings", pa.string()),  # JSON string
    ("errors", pa.string()),  # JSON string
    ("duration_ms", pa.int32()),
    ("expected_success", pa.bool_()),
    ("expected_created_count", pa.int32()),
    ("expected_capability", pa.string()),
    ("expected_parameters", pa.string()),  # JSON string
    ("passed", pa.bool_()),
    ("failure_category", pa.string()),
    ("failure_detail", pa.string()),
    ("notes", pa.string()),
])


def _result_to_dict(r: GridTestResult) -> dict:
    """Convert a GridTestResult to a flat dict for serialization."""
    return {
        "test_id": r.test_id,
        "prompt": r.prompt,
        "mode": r.mode,
        "git_commit": r.git_commit,
        "git_branch": r.git_branch,
        "timestamp": r.timestamp,
        "resolved_capability": r.resolved_capability or "",
        "resolved_parameters": json.dumps(r.resolved_parameters, default=str),
        "assumptions": json.dumps(r.assumptions),
        "pipe_available": r.pipe_available,
        "status": r.status,
        "created_count": r.created_count,
        "created_ids": json.dumps(r.created_ids),
        "warnings": json.dumps(r.warnings),
        "errors": json.dumps(r.errors),
        "duration_ms": r.duration_ms,
        "expected_success": r.expected_success,
        "expected_created_count": r.expected_created_count,
        "expected_capability": r.expected_capability or "",
        "expected_parameters": json.dumps(r.expected_parameters, default=str),
        "passed": r.passed,
        "failure_category": r.failure_category,
        "failure_detail": r.failure_detail,
        "notes": r.notes,
    }


def write_jsonl(results: list[GridTestResult], path: Path) -> Path:
    """Append results to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(_result_to_dict(r), default=str) + "\n")
    return path


def write_parquet(results: list[GridTestResult], path: Path) -> Path:
    """Write results to a Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [_result_to_dict(r) for r in results]
    arrays = {}
    for field in _PARQUET_SCHEMA:
        col_name = field.name
        values = [row[col_name] for row in rows]
        arrays[col_name] = values

    table = pa.table(arrays, schema=_PARQUET_SCHEMA)
    pq.write_table(table, str(path))
    return path


def read_parquet(path: Path) -> list[dict]:
    """Read a Parquet file and return list of row dicts."""
    if not path.exists():
        return []
    table = pq.read_table(str(path))
    return table.to_pydict()


def write_to_sqlite(
    results: list[GridTestResult],
    session_factory: Optional[sessionmaker] = None,
) -> None:
    """Persist test results to the SQLite prompt_executions table."""
    if session_factory is None:
        return

    try:
        from axiom_core.database import get_session
        from axiom_core.models import PromptExecutionRow

        with get_session(session_factory) as session:
            for r in results:
                row = PromptExecutionRow(
                    prompt=r.prompt,
                    mode=f"test_{r.mode}",
                    capability=r.resolved_capability,
                    status=r.status,
                    created_count=r.created_count,
                    duration_ms=r.duration_ms,
                )
                row.set_parameters(r.resolved_parameters)
                row.set_assumptions(r.assumptions)
                row.set_created_ids(r.created_ids)
                row.set_errors(r.errors)
                row.set_warnings(r.warnings)
                session.add(row)
    except Exception:
        pass


def persist_results(
    results: list[GridTestResult],
    output_dir: Path,
    run_id: str,
    session_factory: Optional[sessionmaker] = None,
) -> dict[str, Path]:
    """Write results to all three storage layers.

    Returns dict of {format: path} for the files written.
    """
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    paths["jsonl"] = write_jsonl(results, run_dir / "results.jsonl")
    paths["parquet"] = write_parquet(results, run_dir / "results.parquet")

    write_to_sqlite(results, session_factory)

    return paths
