"""SQLite persistence for the discovery registries (PR #20).

Reuses the PR #1 persistence stack (``axiom_core.database`` + the shared
SQLAlchemy ``Base`` in ``axiom_core.models``). No new database or storage layer
is introduced. Persistence is optional: when no ``session_factory`` is supplied
the harness still produces in-memory facts + file artifacts, which keeps the
interpreter unit-testable without a database.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import sessionmaker

from axiom_core.database import get_session
from axiom_core.models import (
    CandidateCapabilityRow,
    ProductObjectRow,
    ProductPropertyRow,
)

from .interpret import CandidateCapability, DiscoveredCategory, DiscoveredProperty


def upsert_categories(
    session_factory: sessionmaker,
    categories: list[DiscoveredCategory],
    run_id: str,
) -> dict[str, int]:
    """Upsert categories keyed by (adapter, category_name). Returns counts."""
    inserted = 0
    updated = 0
    with get_session(session_factory) as session:
        for cat in categories:
            row = (
                session.query(ProductObjectRow)
                .filter_by(adapter=cat.adapter, category_name=cat.category_name)
                .one_or_none()
            )
            if row is None:
                session.add(
                    ProductObjectRow(
                        adapter=cat.adapter,
                        category_name=cat.category_name,
                        built_in_category=cat.built_in_category,
                        category_id=cat.category_id,
                        element_count=cat.element_count,
                        type_count=cat.type_count,
                        last_run_id=run_id,
                    )
                )
                inserted += 1
            else:
                row.built_in_category = cat.built_in_category or row.built_in_category
                if cat.category_id is not None:
                    row.category_id = cat.category_id
                row.element_count = cat.element_count
                row.type_count = cat.type_count
                row.last_run_id = run_id
                updated += 1
    return {"inserted": inserted, "updated": updated}


def upsert_properties(
    session_factory: sessionmaker,
    properties: list[DiscoveredProperty],
    run_id: str,
) -> dict[str, int]:
    """Upsert properties keyed by (adapter, category, name, instance_parameter)."""
    inserted = 0
    updated = 0
    with get_session(session_factory) as session:
        for prop in properties:
            row = (
                session.query(ProductPropertyRow)
                .filter_by(
                    adapter=prop.adapter,
                    category=prop.category,
                    parameter_name=prop.parameter_name,
                    instance_parameter=prop.instance_parameter,
                )
                .one_or_none()
            )
            if row is None:
                session.add(
                    ProductPropertyRow(
                        adapter=prop.adapter,
                        category=prop.category,
                        parameter_name=prop.parameter_name,
                        storage_type=prop.storage_type,
                        read_only=prop.read_only,
                        instance_parameter=prop.instance_parameter,
                        built_in_parameter_id=prop.built_in_parameter_id,
                        spec_type_id=prop.spec_type_id,
                        unit_type_id=prop.unit_type_id,
                        display_unit=prop.display_unit,
                        format_options_json=prop.format_options,
                        has_value=prop.has_value,
                        sample_values_json=json.dumps(prop.sample_values),
                        expected_input_format=prop.expected_input_format,
                        safely_settable_by_axiom=prop.safely_settable_by_axiom,
                        last_run_id=run_id,
                    )
                )
                inserted += 1
            else:
                row.storage_type = prop.storage_type or row.storage_type
                row.read_only = prop.read_only
                row.built_in_parameter_id = (
                    prop.built_in_parameter_id or row.built_in_parameter_id
                )
                row.spec_type_id = prop.spec_type_id or row.spec_type_id
                row.unit_type_id = prop.unit_type_id or row.unit_type_id
                row.display_unit = prop.display_unit or row.display_unit
                row.format_options_json = prop.format_options or row.format_options_json
                row.has_value = prop.has_value or row.has_value
                row.sample_values_json = json.dumps(prop.sample_values)
                row.expected_input_format = prop.expected_input_format
                row.safely_settable_by_axiom = prop.safely_settable_by_axiom
                row.last_run_id = run_id
                updated += 1
    return {"inserted": inserted, "updated": updated}


def upsert_candidates(
    session_factory: sessionmaker,
    candidates: list[CandidateCapability],
    run_id: str,
) -> dict[str, int]:
    """Upsert candidate capabilities keyed by candidate_id. Never executed."""
    inserted = 0
    updated = 0
    with get_session(session_factory) as session:
        for cand in candidates:
            row = (
                session.query(CandidateCapabilityRow)
                .filter_by(candidate_id=cand.candidate_id)
                .one_or_none()
            )
            if row is None:
                session.add(
                    CandidateCapabilityRow(
                        candidate_id=cand.candidate_id,
                        capability=cand.capability,
                        adapter=cand.adapter,
                        category=cand.category,
                        parameter_name=cand.parameter_name,
                        storage_type=cand.storage_type,
                        instance_parameter=cand.instance_parameter,
                        spec_type_id=cand.spec_type_id,
                        unit_type_id=cand.unit_type_id,
                        expected_input_format=cand.expected_input_format,
                        safely_settable_by_axiom=cand.safely_settable_by_axiom,
                        status=cand.status,
                        source_run_id=run_id,
                    )
                )
                inserted += 1
            else:
                row.storage_type = cand.storage_type or row.storage_type
                row.spec_type_id = cand.spec_type_id or row.spec_type_id
                row.unit_type_id = cand.unit_type_id or row.unit_type_id
                row.expected_input_format = cand.expected_input_format
                row.safely_settable_by_axiom = cand.safely_settable_by_axiom
                row.status = cand.status
                row.source_run_id = run_id
                updated += 1
    return {"inserted": inserted, "updated": updated}


def persist_all(
    session_factory: Optional[sessionmaker],
    categories: list[DiscoveredCategory],
    properties: list[DiscoveredProperty],
    candidates: list[CandidateCapability],
    run_id: str,
) -> dict[str, dict[str, int]]:
    """Persist categories, properties, and candidates. No-op if no factory."""
    if session_factory is None:
        return {}
    return {
        "categories": upsert_categories(session_factory, categories, run_id),
        "properties": upsert_properties(session_factory, properties, run_id),
        "candidates": upsert_candidates(session_factory, candidates, run_id),
    }
