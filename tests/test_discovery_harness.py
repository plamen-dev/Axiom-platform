"""End-to-end tests for DiscoveryHarness v1 + the discovery-run CLI."""

import csv
import json

import pytest
from axiom_cli.main import cli
from axiom_core.database import create_db_engine, init_db, make_session_factory
from axiom_core.discovery.harness import (
    SIMULATED_EXPORT,
    DiscoveryInputError,
    load_inventory_export,
    run_discovery,
)
from axiom_core.models import ProductObjectRow
from click.testing import CliRunner


def _write_elements_jsonl(path):
    """Write SIMULATED_EXPORT elements as JSONL (mirrors elements.jsonl)."""
    with open(path, "w", encoding="utf-8") as f:
        for elem in SIMULATED_EXPORT["elements"]:
            f.write(json.dumps(elem) + "\n")
    return path


def test_run_discovery_simulate_writes_all_artifacts(tmp_path):
    result = run_discovery(
        run_id="e2e1", simulate=True, output_dir=str(tmp_path)
    )
    run_dir = tmp_path / "e2e1"
    for name in (
        "categories.csv",
        "parameters.csv",
        "candidate_capabilities.csv",
        "discovery_evidence.jsonl",
        "summary.json",
        "summary.md",
    ):
        assert (run_dir / name).exists(), f"missing {name}"

    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["run_id"] == "e2e1"
    assert summary["mode"] == "simulate"
    assert summary["metrics"]["categories_discovered"] == 2
    assert result.metrics["candidate_capabilities_generated"] >= 1


def test_run_discovery_persists_when_session_factory_given(tmp_path):
    engine = create_db_engine(str(tmp_path / "d.db"))
    init_db(engine)
    sf = make_session_factory(engine)
    result = run_discovery(
        run_id="e2e2", simulate=True, output_dir=str(tmp_path), session_factory=sf
    )
    assert result.persisted["categories"]["inserted"] == 2
    with sf() as session:
        assert session.query(ProductObjectRow).count() == 2


def test_run_discovery_from_export_file(tmp_path):
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(SIMULATED_EXPORT))
    result = run_discovery(
        run_id="e2e3",
        inventory_export_path=str(export_path),
        output_dir=str(tmp_path),
    )
    assert result.mode == "live"
    assert result.source_model == "SimulatedModel.rvt"


def test_live_without_export_raises():
    import pytest

    with pytest.raises(ValueError):
        run_discovery(run_id="x", simulate=False)


def test_cli_discovery_run_simulate(tmp_path):
    runner = CliRunner()
    out_dir = tmp_path / "runs"
    res = runner.invoke(
        cli,
        [
            "discovery-run",
            "--adapter", "revit",
            "--simulate",
            "--run-id", "cli1",
            "--output-dir", str(out_dir),
        ],
    )
    assert res.exit_code == 0, res.output
    assert (out_dir / "cli1" / "summary.json").exists()
    assert (out_dir / "cli1" / "candidate_capabilities.csv").exists()


def test_cli_discovery_run_persists_with_db(tmp_path):
    runner = CliRunner()
    out_dir = tmp_path / "runs"
    db_path = tmp_path / "cli.db"
    res = runner.invoke(
        cli,
        [
            "discovery-run",
            "--simulate",
            "--run-id", "cli2",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ],
    )
    assert res.exit_code == 0, res.output
    assert db_path.exists()


def test_cli_live_without_export_errors(tmp_path):
    runner = CliRunner()
    res = runner.invoke(cli, ["discovery-run", "--adapter", "revit"])
    assert res.exit_code == 2


def test_cli_unsupported_adapter_errors():
    runner = CliRunner()
    res = runner.invoke(cli, ["discovery-run", "--adapter", "rhino", "--simulate"])
    assert res.exit_code == 2


# --- JSONL / unsupported-format regression tests -------------------------------

def test_load_elements_jsonl_supported(tmp_path):
    """elements.jsonl (one element record per line) is a valid substrate."""
    p = _write_elements_jsonl(tmp_path / "elements.jsonl")
    export = load_inventory_export(p)
    assert export["elements"] == SIMULATED_EXPORT["elements"]


def test_run_discovery_with_elements_jsonl(tmp_path):
    """Full discovery run against an elements.jsonl input produces artifacts."""
    p = _write_elements_jsonl(tmp_path / "elements.jsonl")
    result = run_discovery(
        run_id="jsonl1",
        inventory_export_path=str(p),
        output_dir=str(tmp_path / "runs"),
    )
    assert result.metrics["categories_discovered"] >= 1
    assert result.metrics["parameters_discovered"] >= 1


def test_load_json_array_of_elements_supported(tmp_path):
    """A plain JSON array of element records is accepted."""
    p = tmp_path / "elements_array.json"
    p.write_text(json.dumps(SIMULATED_EXPORT["elements"]), encoding="utf-8")
    export = load_inventory_export(p)
    assert export["elements"] == SIMULATED_EXPORT["elements"]


def test_parameters_jsonl_rejected_with_clear_error(tmp_path):
    """parameters.jsonl (parameter-schema rows) is rejected with guidance."""
    p = tmp_path / "parameters.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ParameterName": "Comments", "StorageType": "String",
                             "IsInstanceParam": True}) + "\n")
        f.write(json.dumps({"ParameterName": "Area", "StorageType": "Double",
                            "IsInstanceParam": True}) + "\n")
    with pytest.raises(DiscoveryInputError) as exc:
        load_inventory_export(p)
    msg = str(exc.value)
    assert "parameter-SCHEMA" in msg
    assert "elements.jsonl" in msg


def test_jsonl_content_with_json_extension_clear_error(tmp_path):
    """The exact reported failure: JSONL content but parsed as a single JSON doc.

    Must yield a human-readable error, not a raw 'Extra data: line 2 column 1'.
    """
    p = tmp_path / "elements.json"  # wrong extension, JSONL content
    _write_elements_jsonl(p)
    with pytest.raises(DiscoveryInputError) as exc:
        load_inventory_export(p)
    msg = str(exc.value)
    assert "JSONL" in msg
    assert "Extra data" not in msg or "looks like JSONL" in msg


def test_malformed_jsonl_line_numbered_error(tmp_path):
    """A malformed JSONL line yields a clear, line-numbered error."""
    p = tmp_path / "elements.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ElementId": 1, "Category": "Walls"}) + "\n")
        f.write("{not valid json}\n")
    with pytest.raises(DiscoveryInputError) as exc:
        load_inventory_export(p)
    assert "line 2" in str(exc.value)


def test_cli_discovery_run_with_jsonl_export(tmp_path):
    """CLI accepts an elements.jsonl export end-to-end (exit 0)."""
    p = _write_elements_jsonl(tmp_path / "elements.jsonl")
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discovery-run", "--adapter", "revit",
            "--inventory-export-path", str(p),
            "--run-id", "clijsonl",
            "--output-dir", str(tmp_path / "runs"),
        ],
    )
    assert res.exit_code == 0, res.output


def test_cli_discovery_run_parameters_jsonl_rejected(tmp_path):
    """CLI rejects parameters.jsonl with a clean, human-readable error (exit 2)."""
    p = tmp_path / "parameters.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ParameterName": "Comments",
                            "IsInstanceParam": True}) + "\n")
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discovery-run", "--adapter", "revit",
            "--inventory-export-path", str(p),
            "--output-dir", str(tmp_path / "runs"),
        ],
    )
    assert res.exit_code == 2
    assert "parameter-SCHEMA" in res.output or "elements.jsonl" in res.output
    assert "Traceback" not in res.output


# --- InventoryModel run-folder contract regression tests ----------------------

def _make_run_folder(folder, *, with_params=True, with_metadata=True,
                     elements_as_parquet=False):
    """Build a realistic InventoryModel run folder using the real writers."""
    from axiom_core.inventory import storage
    folder.mkdir(parents=True, exist_ok=True)
    elements = [
        {"ElementId": 1001, "Category": "Walls", "BuiltInCategory": "OST_Walls",
         "CategoryId": -2000011, "IsType": False, "Parameters": [
             {"Name": "Comments", "StorageType": "String", "IsReadOnly": False,
              "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS",
              "ValueString": "Exterior"},
             {"Name": "Area", "StorageType": "Double", "IsReadOnly": True,
              "BuiltInParameterId": "HOST_AREA_COMPUTED", "ValueDouble": 12.5},
         ]},
        {"ElementId": 2001, "Category": "Walls", "BuiltInCategory": "OST_Walls",
         "CategoryId": -2000011, "IsType": True, "Parameters": [
             {"Name": "Fire Rating", "StorageType": "String", "IsReadOnly": False,
              "BuiltInParameterId": "FIRE_RATING", "ValueString": "2HR"},
         ]},
    ]
    if with_params:
        storage.write_parameters_parquet(
            elements, folder / "parameters.parquet", run_id="inv_test")
    # elements file carries NO embedded parameters (the real object-registry shape)
    els_no_params = [{k: v for k, v in e.items() if k != "Parameters"}
                     for e in elements]
    if elements_as_parquet:
        storage.write_elements_parquet(
            els_no_params, folder / "elements.parquet", run_id="inv_test")
    else:
        storage.write_jsonl(els_no_params, folder / "elements.jsonl")
    if with_metadata:
        (folder / "run_metadata.json").write_text(
            json.dumps({"run_id": "inv_test", "source_model": "Snowdon.rvt",
                        "chunk_by": "discipline"}), encoding="utf-8")
    return folder


def test_run_folder_joins_parameters_from_parquet(tmp_path):
    """A run folder joins parameters.parquet onto elements -> full discovery."""
    folder = _make_run_folder(tmp_path / "inv_run")
    result = run_discovery(
        run_id="folder1",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    m = result.metrics
    assert m["categories_discovered"] == 1
    assert m["parameters_discovered"] == 3  # Comments(inst), Area(inst), FireRating(type)
    assert m["candidate_capabilities_generated"] >= 1
    assert result.parameter_source == "parameters.parquet"
    assert result.discovery_complete is True
    assert result.source_model == "Snowdon.rvt"  # provenance from run_metadata.json


def test_run_folder_elements_parquet_objects(tmp_path):
    """Objects can come from elements.parquet when elements.jsonl is absent."""
    folder = _make_run_folder(tmp_path / "inv_run", elements_as_parquet=True)
    result = run_discovery(
        run_id="folder2",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.object_source == "elements.parquet"
    assert result.metrics["parameters_discovered"] == 3


def test_run_folder_elements_only_is_incomplete(tmp_path):
    """elements only (no parameters.parquet) = category-only, NOT complete."""
    folder = _make_run_folder(
        tmp_path / "inv_run", with_params=False, with_metadata=False)
    result = run_discovery(
        run_id="folder3",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.metrics["categories_discovered"] == 1
    assert result.metrics["parameters_discovered"] == 0
    assert result.discovery_complete is False
    assert result.parameter_source == ""
    assert result.warnings and "missing" in result.warnings[0].lower()
    summary = (tmp_path / "out" / "folder3" / "summary.md").read_text()
    assert "MISSING / not provided" in summary
    sj = json.loads((tmp_path / "out" / "folder3" / "summary.json").read_text())
    assert sj["discovery_complete"] is False
    assert sj["parameter_source"] is None


def test_run_folder_without_elements_errors(tmp_path):
    folder = tmp_path / "empty_run"
    folder.mkdir()
    (folder / "run_metadata.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DiscoveryInputError) as exc:
        load_inventory_export(folder)
    assert "elements" in str(exc.value).lower()


def test_run_folder_populates_registries(tmp_path):
    """Acceptance: a run folder populates all three registries."""
    folder = _make_run_folder(tmp_path / "inv_run")
    from axiom_core.models import (
        CandidateCapabilityRow,
        ProductObjectRow,
        ProductPropertyRow,
    )
    engine = create_db_engine(str(tmp_path / "disc.db"))
    init_db(engine)
    sf = make_session_factory(engine)
    run_discovery(
        run_id="folder4",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
        session_factory=sf,
    )
    with sf() as s:
        assert s.query(ProductObjectRow).count() >= 1
        assert s.query(ProductPropertyRow).count() >= 1
        assert s.query(CandidateCapabilityRow).count() >= 1


def test_cli_discovery_run_with_run_folder(tmp_path):
    folder = _make_run_folder(tmp_path / "inv_run")
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discovery-run", "--adapter", "revit",
            "--inventory-export-path", str(folder),
            "--run-id", "clifolder",
            "--output-dir", str(tmp_path / "out"),
            "--db-path", str(tmp_path / "disc.db"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert (tmp_path / "disc.db").exists()


def test_cli_run_folder_elements_only_warns(tmp_path):
    folder = _make_run_folder(
        tmp_path / "inv_run", with_params=False, with_metadata=False)
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "discovery-run", "--adapter", "revit",
            "--inventory-export-path", str(folder),
            "--run-id", "cliwarn",
            "--output-dir", str(tmp_path / "out"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "discovery complete: no" in res.output.lower()


# --- detected-but-empty / unusable parameter source regression tests ----------

def _write_empty_parameters_parquet(path):
    """Write a parameters.parquet with the real schema but ZERO rows."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from axiom_core.inventory.storage import PARAMETER_PARQUET_SCHEMA
    pq.write_table(pa.Table.from_pylist([], schema=PARAMETER_PARQUET_SCHEMA), path)
    return path


def test_run_folder_empty_parameters_parquet_is_incomplete(tmp_path):
    """parameters.parquet detected but EMPTY -> not complete, clear reason."""
    from axiom_core.inventory import storage
    folder = tmp_path / "inv_run"
    folder.mkdir()
    storage.write_jsonl(
        [{"ElementId": 1, "Category": "Walls", "IsType": False}],
        folder / "elements.jsonl",
    )
    _write_empty_parameters_parquet(folder / "parameters.parquet")

    result = run_discovery(
        run_id="empty_params",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.metrics["parameters_discovered"] == 0
    assert result.discovery_complete is False
    assert result.parameter_rows_total == 0
    assert result.parameter_rows_joined == 0
    assert result.warnings and "no usable parameter rows" in result.warnings[0].lower()
    sj = json.loads((tmp_path / "out" / "empty_params" / "summary.json").read_text())
    assert sj["discovery_complete"] is False
    assert sj["discovery_parameter_complete"] is False
    assert sj["parameter_rows_total"] == 0


def test_run_folder_param_id_mismatch_is_incomplete(tmp_path):
    """parameters.parquet has rows but none match elements -> incomplete."""
    from axiom_core.inventory import storage
    folder = tmp_path / "inv_run"
    folder.mkdir()
    # elements.jsonl ids do NOT match the parameter rows; no elements.parquet.
    storage.write_jsonl(
        [{"ElementId": 9991, "Category": "Walls", "IsType": False}],
        folder / "elements.jsonl",
    )
    storage.write_parameters_parquet(
        [{"ElementId": 1001, "Category": "Walls", "IsType": False, "Parameters": [
            {"Name": "Comments", "StorageType": "String", "IsReadOnly": False},
        ]}],
        folder / "parameters.parquet",
        run_id="x",
    )
    result = run_discovery(
        run_id="mismatch",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.metrics["parameters_discovered"] == 0
    assert result.discovery_complete is False
    assert result.parameter_rows_total >= 1
    assert result.parameter_rows_joined == 0
    assert "join key mismatch" in result.warnings[0].lower()


def test_run_folder_recovers_join_via_elements_parquet(tmp_path):
    """jsonl ids mismatch but elements.parquet shares ids with parameters."""
    from axiom_core.inventory import storage
    folder = tmp_path / "inv_run"
    folder.mkdir()
    matching = [{"ElementId": 1001, "Category": "Walls", "IsType": False,
                 "Parameters": [
                     {"Name": "Comments", "StorageType": "String",
                      "IsReadOnly": False, "ValueString": "Exterior"},
                 ]}]
    # elements.jsonl carries mismatched ids; elements.parquet matches params.
    storage.write_jsonl(
        [{"ElementId": 9991, "Category": "X", "IsType": False}],
        folder / "elements.jsonl",
    )
    storage.write_elements_parquet(matching, folder / "elements.parquet", run_id="x")
    storage.write_parameters_parquet(matching, folder / "parameters.parquet", run_id="x")

    result = run_discovery(
        run_id="recover",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.object_source == "elements.parquet"
    assert result.metrics["parameters_discovered"] >= 1
    assert result.discovery_complete is True
    assert result.parameter_rows_joined >= 1


def test_attach_parameters_tolerates_str_int_id_mismatch():
    from axiom_core.discovery.harness import _attach_parameters
    elements = [{"ElementId": 1001, "Category": "Walls", "IsType": False}]
    # parameter row carries the id as a STRING
    rows = [{"element_id": "1001", "param_name": "Comments",
             "storage_type": "String", "is_read_only": False}]
    total, joined = _attach_parameters(elements, rows)
    assert (total, joined) == (1, 1)
    assert elements[0]["Parameters"][0]["Name"] == "Comments"


# --- PR #21: enriched parameter export reaches complete discovery -------------

_ENRICHED_ELEMENTS = [
    {
        "ElementId": 4001, "Category": "Walls", "BuiltInCategory": "OST_Walls",
        "CategoryId": -2000011, "IsType": False, "Parameters": [
            {"Name": "Comments", "StorageType": "String", "IsReadOnly": False,
             "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS",
             "ValueString": "Exterior"},
            # writable Double WITH unit metadata -> safely settable
            {"Name": "Unconnected Height", "StorageType": "Double",
             "IsReadOnly": False, "BuiltInParameterId": "WALL_USER_HEIGHT_PARAM",
             "ValueDouble": 3.0, "ValueString": "3000 mm",
             "SpecTypeId": "autodesk.spec.aec:length-2.0.0",
             "UnitTypeId": "autodesk.unit.unit:millimeters-1.0.1",
             "DisplayUnit": "millimeters"},
            # writable Double WITHOUT unit metadata -> NOT safely settable
            {"Name": "Mystery Number", "StorageType": "Double",
             "IsReadOnly": False, "BuiltInParameterId": "SOME_DOUBLE",
             "ValueDouble": 1.0},
        ],
    },
    {
        "ElementId": 4002, "Category": "Walls", "BuiltInCategory": "OST_Walls",
        "CategoryId": -2000011, "IsType": True, "Parameters": [
            {"Name": "Fire Rating", "StorageType": "String", "IsReadOnly": False,
             "BuiltInParameterId": "FIRE_RATING", "ValueString": "2HR"},
        ],
    },
]


def _make_enriched_run_folder(folder):
    """Build a run folder whose parameters.parquet carries the value contract."""
    from axiom_core.inventory import storage
    folder.mkdir(parents=True, exist_ok=True)
    storage.write_parameters_parquet(
        _ENRICHED_ELEMENTS, folder / "parameters.parquet", run_id="inv_enr")
    els_no_params = [{k: v for k, v in e.items() if k != "Parameters"}
                     for e in _ENRICHED_ELEMENTS]
    storage.write_jsonl(els_no_params, folder / "elements.jsonl")
    return folder


def test_run_folder_enriched_export_reaches_complete_discovery(tmp_path):
    """Enriched parameters.parquet -> parameters + candidates + complete=YES."""
    folder = _make_enriched_run_folder(tmp_path / "inv_enr")
    result = run_discovery(
        run_id="enr_e2e",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    m = result.metrics
    assert m["categories_discovered"] > 0
    assert m["parameters_discovered"] > 0
    assert m["candidate_capabilities_generated"] > 0
    assert result.discovery_complete is True
    assert result.parameter_rows_joined == result.parameter_rows_total > 0
    # Value contract: the unit-bearing Double is safely settable; the bare one
    # is not, so at least one but not all parameters are safely settable.
    assert m["safely_settable_parameters"] >= 1


def test_run_folder_enriched_double_unit_contract(tmp_path):
    """A writable Double is safely settable only with unit metadata."""
    folder = _make_enriched_run_folder(tmp_path / "inv_enr2")
    run_discovery(
        run_id="enr_e2e2",
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out2"),
    )
    rows = list(csv.DictReader(
        (tmp_path / "out2" / "enr_e2e2" / "parameters.csv").read_text().splitlines()
    ))
    by_name = {r["parameter_name"]: r for r in rows}
    assert by_name["Unconnected Height"]["safely_settable_by_axiom"] == "True"
    assert by_name["Mystery Number"]["safely_settable_by_axiom"] == "False"
    assert by_name["Unconnected Height"]["unit_type_id"]


def test_run_discovery_path_wins_mode_is_live_even_if_simulate_set(tmp_path):
    """Explicit export path = real data => mode 'live' even if simulate=True."""
    from axiom_core.inventory import storage
    folder = tmp_path / "inv_run"
    folder.mkdir()
    storage.write_jsonl(
        [{"ElementId": 1, "Category": "Walls", "IsType": False}],
        folder / "elements.jsonl",
    )
    result = run_discovery(
        run_id="prov",
        simulate=True,  # conflicting flag; path must win
        inventory_export_path=str(folder),
        output_dir=str(tmp_path / "out"),
    )
    assert result.mode == "live"
    sj = json.loads((tmp_path / "out" / "prov" / "summary.json").read_text())
    assert sj["mode"] == "live"
