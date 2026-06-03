"""Tests for discovery registry persistence (reuses PR #1 SQLite patterns)."""

from axiom_core.database import create_db_engine, init_db, make_session_factory
from axiom_core.discovery import registries
from axiom_core.discovery.harness import SIMULATED_EXPORT
from axiom_core.discovery.interpret import interpret_export
from axiom_core.models import (
    CandidateCapabilityRow,
    ProductObjectRow,
    ProductPropertyRow,
)


def _session_factory(tmp_path):
    engine = create_db_engine(str(tmp_path / "discovery.db"))
    init_db(engine)
    return make_session_factory(engine)


def test_persist_all_inserts_rows(tmp_path):
    sf = _session_factory(tmp_path)
    interp = interpret_export(SIMULATED_EXPORT, run_id="r1")
    result = registries.persist_all(
        sf, interp.categories, interp.properties, interp.candidates, "r1"
    )
    assert result["categories"]["inserted"] == len(interp.categories)
    assert result["properties"]["inserted"] == len(interp.properties)
    assert result["candidates"]["inserted"] == len(interp.candidates)

    with sf() as session:
        assert session.query(ProductObjectRow).count() == len(interp.categories)
        assert session.query(ProductPropertyRow).count() == len(interp.properties)
        assert session.query(CandidateCapabilityRow).count() == len(interp.candidates)


def test_same_named_instance_and_type_params_are_separate_rows(tmp_path):
    sf = _session_factory(tmp_path)
    elements = [
        {
            "Category": "Walls",
            "IsType": False,
            "Parameters": [{"Name": "Comments", "StorageType": "String"}],
        },
        {
            "Category": "Walls",
            "IsType": True,
            "Parameters": [{"Name": "Comments", "StorageType": "String"}],
        },
    ]
    interp = interpret_export({"elements": elements}, run_id="r2")
    registries.persist_all(
        sf, interp.categories, interp.properties, interp.candidates, "r2"
    )
    with sf() as session:
        rows = session.query(ProductPropertyRow).filter_by(
            category="Walls", parameter_name="Comments"
        ).all()
        assert len(rows) == 2
        assert {r.instance_parameter for r in rows} == {True, False}


def test_rerun_upserts_not_duplicates(tmp_path):
    sf = _session_factory(tmp_path)
    interp = interpret_export(SIMULATED_EXPORT, run_id="r3")
    registries.persist_all(
        sf, interp.categories, interp.properties, interp.candidates, "r3"
    )
    second = registries.persist_all(
        sf, interp.categories, interp.properties, interp.candidates, "r4"
    )
    assert second["categories"]["inserted"] == 0
    assert second["categories"]["updated"] == len(interp.categories)
    with sf() as session:
        assert session.query(ProductObjectRow).count() == len(interp.categories)


def test_value_contract_persisted(tmp_path):
    sf = _session_factory(tmp_path)
    interp = interpret_export(SIMULATED_EXPORT, run_id="r5")
    registries.persist_all(
        sf, interp.categories, interp.properties, interp.candidates, "r5"
    )
    with sf() as session:
        height = session.query(ProductPropertyRow).filter_by(
            parameter_name="Unconnected Height"
        ).one()
        assert height.safely_settable_by_axiom is True
        assert height.unit_type_id
        assert height.display_unit == "mm"


def test_persist_all_noop_without_session_factory():
    interp = interpret_export(SIMULATED_EXPORT, run_id="r6")
    result = registries.persist_all(
        None, interp.categories, interp.properties, interp.candidates, "r6"
    )
    assert result == {}
