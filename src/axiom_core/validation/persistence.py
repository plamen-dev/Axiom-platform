"""SQLite persistence for the Capability Validation Registry (PR #23).

Reuses the PR #1 persistence stack (``axiom_core.database`` + the shared
SQLAlchemy ``Base`` in ``axiom_core.models``). No new database or storage layer
is introduced. Persistence is optional: the registry is fully usable in-memory
without a database; this module only mirrors the declarative catalog into the
``validation_procedures`` table so future loops can query it via SQL.

This module persists *definitions only*. It never executes a validation.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import sessionmaker

from axiom_core.database import get_session
from axiom_core.models import ValidationProcedureRow

from .validation_registry import DEFAULT_REGISTRY, ValidationProcedure


def _row_from_procedure(proc: ValidationProcedure) -> dict:
    """Flatten a procedure into the column values for a ValidationProcedureRow."""
    return {
        "capability_name": proc.capability_name,
        "capability_type": proc.capability_type.value,
        "adapter": proc.adapter,
        "version": proc.version,
        "validation_procedure_id": proc.validation_procedure_id,
        "validation_name": proc.validation_name,
        "validation_description": proc.validation_description,
        "steps_json": json.dumps(list(proc.steps)),
        "required_inputs_json": json.dumps(list(proc.required_inputs)),
        "optional_inputs_json": json.dumps(list(proc.optional_inputs)),
        "environment_requirements_json": json.dumps(
            [e.value for e in proc.environment_requirements]),
        "evidence_json": json.dumps(proc.evidence.to_dict()),
        "pass_conditions_json": json.dumps([c.value for c in proc.pass_conditions]),
        "failure_conditions_json": json.dumps([c.value for c in proc.failure_conditions]),
        "retry_policy_json": json.dumps(proc.retry_policy.to_dict()),
        "promotion_eligibility_json": json.dumps(proc.promotion_eligibility.to_dict()),
        "notes": proc.notes,
    }


def upsert_procedures(
    session_factory: sessionmaker,
    procedures: list[ValidationProcedure],
) -> dict[str, int]:
    """Upsert validation definitions keyed by ``capability_name``.

    Returns counts of inserted/updated rows. Definitions only — nothing runs.
    """
    inserted = 0
    updated = 0
    with get_session(session_factory) as session:
        for proc in procedures:
            values = _row_from_procedure(proc)
            row = (
                session.query(ValidationProcedureRow)
                .filter_by(capability_name=proc.capability_name)
                .one_or_none()
            )
            if row is None:
                session.add(ValidationProcedureRow(**values))
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
    return {"inserted": inserted, "updated": updated}


def persist_default_registry(session_factory: sessionmaker) -> dict[str, int]:
    """Persist every procedure in the default registry. Returns insert/update counts."""
    return upsert_procedures(session_factory, DEFAULT_REGISTRY.list_procedures())


def load_procedure_names(session_factory: sessionmaker) -> list[str]:
    """Return the capability names currently persisted, sorted."""
    with get_session(session_factory) as session:
        rows = session.query(ValidationProcedureRow.capability_name).all()
    return sorted(name for (name,) in rows)
