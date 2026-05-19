"""Persistent execution log for automated and interactive runs.

Dual persistence:
  1. JSONL file at logs/execution.jsonl (always available, no DB setup needed)
  2. SQLite prompt_executions table (when DB is initialized)

Each record captures the full context of a prompt run: parameters,
results, errors, warnings, telemetry events, and timing.

Designed for batch/automated runs where CLI output isn't watched live.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker


def _get_log_path() -> Path:
    """Return the execution log file path, creating the directory if needed."""
    log_dir = Path(os.environ.get("AXIOM_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "execution.jsonl"


def _aggregate_results(results: list[Any]) -> dict:
    """Aggregate created_ids, errors, warnings, and duration from results."""
    all_ids: list[str] = []
    all_errors: list[str] = []
    all_warnings: list[str] = []
    total_duration = 0

    for r in results:
        all_ids.extend(r.created_ids)
        all_errors.extend(r.errors)
        all_warnings.extend(r.warnings)
        total_duration += r.duration_ms

    return {
        "created_ids": all_ids,
        "created_count": len(all_ids),
        "errors": all_errors,
        "warnings": all_warnings,
        "duration_ms": total_duration,
    }


def log_execution(
    prompt: str,
    resolved: Any,
    results: list[Any],
    plan: Any,
    events: list[Any],
    mode: str,
    status: str,
    session_factory: Optional[sessionmaker] = None,
) -> Path:
    """Append a structured execution record to the log file and SQLite.

    Returns the log file path for display in the CLI.
    """
    log_path = _get_log_path()

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "mode": mode,
        "status": status,
        "capability": resolved.capability_name if resolved else None,
        "parameters": resolved.params if resolved else {},
        "assumptions": resolved.assumptions if resolved else [],
        "results": [
            {
                "status": r.status.value,
                "created_ids": r.created_ids,
                "duration_ms": r.duration_ms,
                "warnings": r.warnings,
                "errors": r.errors,
            }
            for r in results
        ],
        "plan_status": plan.status.value if plan else None,
        "telemetry": [e.to_dict() for e in events],
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

    # Persist to SQLite if session_factory is available
    if session_factory is not None:
        _persist_to_sqlite(
            session_factory=session_factory,
            prompt=prompt,
            resolved=resolved,
            results=results,
            mode=mode,
            status=status,
        )

    return log_path


def _persist_to_sqlite(
    session_factory: sessionmaker,
    prompt: str,
    resolved: Any,
    results: list[Any],
    mode: str,
    status: str,
) -> None:
    """Write prompt execution record to the SQLite prompt_executions table."""
    try:
        from axiom_core.database import get_session
        from axiom_core.models import PromptExecutionRow

        agg = _aggregate_results(results)

        row = PromptExecutionRow(
            prompt=prompt,
            mode=mode,
            capability=resolved.capability_name if resolved else None,
            status=status,
            created_count=agg["created_count"],
            duration_ms=agg["duration_ms"],
        )
        row.set_parameters(resolved.params if resolved else {})
        row.set_assumptions(resolved.assumptions if resolved else [])
        row.set_created_ids(agg["created_ids"])
        row.set_errors(agg["errors"])
        row.set_warnings(agg["warnings"])

        with get_session(session_factory) as session:
            session.add(row)
    except Exception:
        pass
