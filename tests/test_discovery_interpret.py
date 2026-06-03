"""Unit tests for the pure discovery interpreter (no I/O, no DB)."""

from axiom_core.discovery.harness import SIMULATED_EXPORT
from axiom_core.discovery.interpret import (
    SUPPORTED_STORAGE_TYPES,
    generate_candidates,
    interpret_categories,
    interpret_export,
    interpret_properties,
)


def _props_by_key(props):
    return {(p.category, p.parameter_name, p.parameter_kind): p for p in props}


def test_interpret_categories_counts_instances_and_types():
    cats = interpret_categories(SIMULATED_EXPORT["elements"])
    by_name = {c.category_name: c for c in cats}
    assert set(by_name) == {"Walls", "Doors"}
    walls = by_name["Walls"]
    # one instance element + one type element
    assert walls.element_count == 1
    assert walls.type_count == 1
    assert walls.built_in_category == "OST_Walls"
    assert walls.category_id == -2000011
    doors = by_name["Doors"]
    assert doors.element_count == 1
    assert doors.type_count == 0


def test_instance_vs_type_recorded_separately():
    props = interpret_properties(SIMULATED_EXPORT["elements"])
    keys = _props_by_key(props)
    # instance-level Comments on Walls (from instance element)
    assert ("Walls", "Comments", "instance") in keys
    # type-level Type Comments on Walls (from type element)
    assert ("Walls", "Type Comments", "type") in keys
    assert keys[("Walls", "Type Comments", "type")].instance_parameter is False
    assert keys[("Walls", "Comments", "instance")].instance_parameter is True


def test_double_without_units_is_not_safely_settable():
    props = interpret_properties(SIMULATED_EXPORT["elements"])
    keys = _props_by_key(props)
    # Area is read-only Double -> not settable
    area = keys[("Walls", "Area", "instance")]
    assert area.storage_type == "Double"
    assert area.read_only is True
    assert area.safely_settable_by_axiom is False


def test_double_with_units_is_safely_settable():
    props = interpret_properties(SIMULATED_EXPORT["elements"])
    keys = _props_by_key(props)
    height = keys[("Walls", "Unconnected Height", "instance")]
    assert height.storage_type == "Double"
    assert height.read_only is False
    assert height.unit_type_id
    assert height.display_unit == "mm"
    assert height.safely_settable_by_axiom is True
    assert "mm" in height.expected_input_format


def test_writable_string_is_safely_settable():
    props = interpret_properties(SIMULATED_EXPORT["elements"])
    keys = _props_by_key(props)
    comments = keys[("Walls", "Comments", "instance")]
    assert comments.safely_settable_by_axiom is True
    assert comments.expected_input_format == "text"
    assert comments.has_value is True
    assert comments.sample_values == ["Exterior"]


def test_candidates_for_both_instance_and_type_writable_supported():
    props = interpret_properties(SIMULATED_EXPORT["elements"])
    cands = generate_candidates(props)
    kinds = {(c.category, c.parameter_name, c.parameter_kind) for c in cands}
    # instance String candidate
    assert ("Walls", "Comments", "instance") in kinds
    # type String candidate (labeled type)
    assert ("Walls", "Type Comments", "type") in kinds
    # no candidate for read-only Area
    assert ("Walls", "Area", "instance") not in kinds
    for c in cands:
        assert c.capability == "SetParameterValue"
        assert c.storage_type in SUPPORTED_STORAGE_TYPES


def test_candidate_carries_safety_flag_for_double_without_units():
    # A writable Double without units would be a candidate but not safe.
    elements = [
        {
            "Category": "Walls",
            "IsType": False,
            "Parameters": [
                {
                    "Name": "Mystery Length",
                    "StorageType": "Double",
                    "IsReadOnly": False,
                },
            ],
        }
    ]
    props = interpret_properties(elements)
    cands = generate_candidates(props)
    assert len(cands) == 1
    assert cands[0].safely_settable_by_axiom is False


def test_compute_metrics():
    interp = interpret_export(SIMULATED_EXPORT, run_id="t1")
    m = interp.metrics
    assert m.categories_discovered == 2
    assert m.instance_parameters + m.type_parameters == m.parameters_discovered
    assert m.writable_parameters + m.read_only_parameters == m.parameters_discovered
    assert m.candidate_capabilities_generated == len(interp.candidates)
    assert m.safely_settable_parameters >= 1


def test_summary_only_export_yields_zero_properties():
    export = {"document_title": "M.rvt", "scan_mode": "summary", "elements": []}
    interp = interpret_export(export, run_id="t2")
    assert interp.metrics.categories_discovered == 0
    assert interp.metrics.parameters_discovered == 0
    assert interp.candidates == []


def test_evidence_records_generated_per_event():
    interp = interpret_export(SIMULATED_EXPORT, run_id="t3")
    types = {e.discovery_type for e in interp.evidence}
    assert {"category", "parameter", "candidate"}.issubset(types)
    for e in interp.evidence:
        assert e.run_id == "t3"
        assert e.timestamp
