"""Tests for InventoryModel capability: resolver, mock, storage, summary, and discovery."""

import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
from axiom_core.capability_registry import get_default_registry
from axiom_core.inventory.report import generate_summary
from axiom_core.inventory.storage import (
    ELEMENT_PARQUET_SCHEMA,
    PARAMETER_PARQUET_SCHEMA,
    persist_inventory,
    write_elements_parquet,
    write_jsonl,
    write_parameters_parquet,
    write_to_sqlite,
)
from axiom_core.prompt_resolver import resolve_prompt

# ---------------------------------------------------------------------------
# Mock data fixtures
# ---------------------------------------------------------------------------

MOCK_ELEMENTS = [
    {
        "ElementId": 100001,
        "UniqueId": "mock-wall-001",
        "Category": "Walls",
        "ClassName": "Wall",
        "Name": "Basic Wall",
        "FamilyName": "Basic Wall",
        "TypeName": 'Generic - 8"',
        "LevelName": "Level 1",
        "LevelId": 300001,
        "WorksetName": "",
        "IsType": False,
        "Parameters": [
            {"Name": "Length", "StorageType": "Double", "ValueString": "20.0",
             "ValueDouble": 20.0, "ValueInt": None,
             "BuiltInParameterId": "CURVE_ELEM_LENGTH", "IsReadOnly": True,
             "ParameterGroup": "Constraints"},
            {"Name": "Comments", "StorageType": "String", "ValueString": "",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS", "IsReadOnly": False,
             "ParameterGroup": "Identity Data"},
        ],
    },
    {
        "ElementId": 100002,
        "UniqueId": "mock-door-001",
        "Category": "Doors",
        "ClassName": "FamilyInstance",
        "Name": "Single-Flush",
        "FamilyName": "Single-Flush",
        "TypeName": '36" x 84"',
        "LevelName": "Level 1",
        "LevelId": 300001,
        "WorksetName": "",
        "IsType": False,
        "Parameters": [
            {"Name": "Width", "StorageType": "Double", "ValueString": "3.0",
             "ValueDouble": 3.0, "ValueInt": None,
             "BuiltInParameterId": "DOOR_WIDTH", "IsReadOnly": True,
             "ParameterGroup": "Dimensions"},
        ],
    },
    {
        "ElementId": 100003,
        "UniqueId": "mock-level-001",
        "Category": "Levels",
        "ClassName": "Level",
        "Name": "Level 1",
        "FamilyName": "",
        "TypeName": "",
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "",
        "IsType": False,
        "Parameters": [
            {"Name": "Elevation", "StorageType": "Double", "ValueString": "0.0",
             "ValueDouble": 0.0, "ValueInt": None,
             "BuiltInParameterId": "LEVEL_ELEV", "IsReadOnly": False,
             "ParameterGroup": "Constraints"},
        ],
    },
    {
        "ElementId": 200001,
        "UniqueId": "mock-walltype-001",
        "Category": "Walls",
        "ClassName": "WallType",
        "Name": 'Generic - 8"',
        "FamilyName": "Basic Wall",
        "TypeName": 'Generic - 8"',
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "",
        "IsType": True,
        "Parameters": [
            {"Name": "Width", "StorageType": "Double", "ValueString": "0.667",
             "ValueDouble": 0.667, "ValueInt": None,
             "BuiltInParameterId": "WALL_ATTR_WIDTH_PARAM", "IsReadOnly": True,
             "ParameterGroup": "Construction"},
        ],
    },
]

EMPTY_ELEMENTS: list[dict] = []

GRIDS_AND_LEVELS_ELEMENTS = [
    {
        "ElementId": 300001,
        "UniqueId": "mock-grid-001",
        "Category": "Grids",
        "ClassName": "Grid",
        "Name": "1",
        "FamilyName": "",
        "TypeName": "",
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "Workset1",
        "IsType": False,
        "Parameters": [
            {"Name": "Name", "StorageType": "String", "ValueString": "1",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "DATUM_TEXT", "IsReadOnly": False,
             "ParameterGroup": "Identity Data"},
        ],
    },
    {
        "ElementId": 300002,
        "UniqueId": "mock-grid-002",
        "Category": "Grids",
        "ClassName": "Grid",
        "Name": "2",
        "FamilyName": "",
        "TypeName": "",
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "Workset1",
        "IsType": False,
        "Parameters": [
            {"Name": "Name", "StorageType": "String", "ValueString": "2",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "DATUM_TEXT", "IsReadOnly": False,
             "ParameterGroup": "Identity Data"},
        ],
    },
    {
        "ElementId": 300003,
        "UniqueId": "mock-level-010",
        "Category": "Levels",
        "ClassName": "Level",
        "Name": "Level 1",
        "FamilyName": "",
        "TypeName": "",
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "Workset1",
        "IsType": False,
        "Parameters": [
            {"Name": "Elevation", "StorageType": "Double", "ValueString": "0.0",
             "ValueDouble": 0.0, "ValueInt": None,
             "BuiltInParameterId": "LEVEL_ELEV", "IsReadOnly": False,
             "ParameterGroup": "Constraints"},
        ],
    },
]

FAMILIES_AND_TYPES_ELEMENTS = [
    {
        "ElementId": 400001,
        "UniqueId": "mock-window-001",
        "Category": "Windows",
        "ClassName": "FamilyInstance",
        "Name": "Fixed 24x48",
        "FamilyName": "Fixed",
        "TypeName": "24\" x 48\"",
        "LevelName": "Level 1",
        "LevelId": 300001,
        "WorksetName": "",
        "IsType": False,
        "Parameters": [
            {"Name": "Width", "StorageType": "Double", "ValueString": "2.0",
             "ValueDouble": 2.0, "ValueInt": None,
             "BuiltInParameterId": "WINDOW_WIDTH", "IsReadOnly": True,
             "ParameterGroup": "Dimensions"},
            {"Name": "Height", "StorageType": "Double", "ValueString": "4.0",
             "ValueDouble": 4.0, "ValueInt": None,
             "BuiltInParameterId": "WINDOW_HEIGHT", "IsReadOnly": True,
             "ParameterGroup": "Dimensions"},
            {"Name": "Mark", "StorageType": "String", "ValueString": "W1",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "ALL_MODEL_MARK", "IsReadOnly": False,
             "ParameterGroup": "Identity Data"},
        ],
    },
    {
        "ElementId": 500001,
        "UniqueId": "mock-windowtype-001",
        "Category": "Windows",
        "ClassName": "FamilySymbol",
        "Name": "24\" x 48\"",
        "FamilyName": "Fixed",
        "TypeName": "24\" x 48\"",
        "LevelName": "",
        "LevelId": 0,
        "WorksetName": "",
        "IsType": True,
        "Parameters": [
            {"Name": "Width", "StorageType": "Double", "ValueString": "2.0",
             "ValueDouble": 2.0, "ValueInt": None,
             "BuiltInParameterId": "WINDOW_WIDTH", "IsReadOnly": True,
             "ParameterGroup": "Dimensions"},
            {"Name": "Default Sill Height", "StorageType": "Double",
             "ValueString": "3.0", "ValueDouble": 3.0, "ValueInt": None,
             "BuiltInParameterId": "WINDOW_DEFAULT_SILL_HEIGHT", "IsReadOnly": False,
             "ParameterGroup": "Constraints"},
        ],
    },
]

DUPLICATE_PARAM_ELEMENTS = [
    {
        "ElementId": 600001,
        "UniqueId": "mock-dup-001",
        "Category": "Walls",
        "ClassName": "Wall",
        "Name": "Wall with dup params",
        "FamilyName": "Basic Wall",
        "TypeName": "Generic - 6\"",
        "LevelName": "Level 1",
        "LevelId": 300001,
        "WorksetName": "",
        "IsType": False,
        "Parameters": [
            {"Name": "Comments", "StorageType": "String", "ValueString": "note A",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS", "IsReadOnly": False,
             "ParameterGroup": "Identity Data"},
            {"Name": "Comments", "StorageType": "String", "ValueString": "note B",
             "ValueDouble": None, "ValueInt": None,
             "BuiltInParameterId": "CUSTOM_COMMENTS", "IsReadOnly": False,
             "ParameterGroup": "Other"},
        ],
    },
]


def _make_large_inventory(count: int = 100) -> list[dict]:
    """Generate a large-ish mock inventory for stress testing."""
    elements = []
    for i in range(count):
        elements.append({
            "ElementId": 900000 + i,
            "UniqueId": f"mock-large-{i:04d}",
            "Category": ["Walls", "Doors", "Windows", "Floors", "Roofs"][i % 5],
            "ClassName": "FamilyInstance",
            "Name": f"Element_{i}",
            "FamilyName": f"Family_{i % 10}",
            "TypeName": f"Type_{i % 20}",
            "LevelName": f"Level {(i % 3) + 1}" if i % 4 != 0 else "",
            "LevelId": 300000 + (i % 3) + 1 if i % 4 != 0 else 0,
            "WorksetName": f"Workset{(i % 2) + 1}" if i % 5 == 0 else "",
            "IsType": i >= count - 10,
            "Parameters": [
                {"Name": f"Param_{j}", "StorageType": "Double",
                 "ValueString": str(float(j)), "ValueDouble": float(j),
                 "ValueInt": None, "BuiltInParameterId": f"PARAM_{j}",
                 "IsReadOnly": j % 2 == 0, "ParameterGroup": "Dimensions"}
                for j in range(3)
            ],
        })
    return elements


# ---------------------------------------------------------------------------
# Prompt resolver tests
# ---------------------------------------------------------------------------

class TestInventoryPromptResolver:
    def test_run_inventory_model(self):
        result = resolve_prompt("Run InventoryModel")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.status == "resolved"
        assert result.params == {}

    def test_inventory_model_lowercase(self):
        result = resolve_prompt("inventory model")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_list_all_model_elements(self):
        result = resolve_prompt("List all model elements")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_scan_model_parameters(self):
        result = resolve_prompt("Scan model parameters")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_extract_model_parameters(self):
        result = resolve_prompt("Extract model parameters")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_model_inventory(self):
        result = resolve_prompt("model inventory")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_extract_all_parameters(self):
        result = resolve_prompt("Extract all parameters")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_show_writable_parameters(self):
        result = resolve_prompt("Show writable parameters")
        assert result is not None
        assert result.capability_name == "InventoryModel"

    def test_unrelated_prompt_not_inventory(self):
        result = resolve_prompt("Place diffusers in every room")
        assert result is None

    def test_grid_prompt_not_inventory(self):
        result = resolve_prompt("Create 5 gridlines spaced 10 ft apart")
        assert result is not None
        assert result.capability_name == "CreateGrids"

    def test_level_prompt_not_inventory(self):
        result = resolve_prompt("Create 3 levels spaced 12 ft apart")
        assert result is not None
        assert result.capability_name == "CreateLevels"

    def test_overly_specific_prompt_fails_gracefully(self):
        result = resolve_prompt("Show me all structural columns on level 3")
        assert result is None


# ---------------------------------------------------------------------------
# Mock execution tests
# ---------------------------------------------------------------------------

class TestInventoryMockExecution:
    def test_mock_returns_success(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        assert result.status.value == "SUCCESS"
        assert result.output_data["mock"] is True
        assert result.output_data["element_count"] > 0
        assert len(result.output_data["elements"]) > 0

    def test_mock_element_schema(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        elem = result.output_data["elements"][0]
        required_keys = [
            "ElementId", "UniqueId", "Category", "ClassName",
            "Name", "IsType", "Parameters", "FamilyName",
            "TypeName", "LevelName", "LevelId", "WorksetName",
        ]
        for key in required_keys:
            assert key in elem, f"Missing key: {key}"

    def test_mock_parameter_schema(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        elem = result.output_data["elements"][0]
        param = elem["Parameters"][0]
        required_keys = [
            "Name", "StorageType", "ValueString", "IsReadOnly",
            "BuiltInParameterId", "ParameterGroup",
        ]
        for key in required_keys:
            assert key in param, f"Missing param key: {key}"

    def test_mock_has_types_and_instances(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        elements = result.output_data["elements"]
        has_type = any(e["IsType"] for e in elements)
        has_instance = any(not e["IsType"] for e in elements)
        assert has_type
        assert has_instance

    def test_mock_source_model(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        assert "source_model" in result.output_data
        assert result.output_data["source_model"] != ""

    def test_mock_read_only_and_writable_params(self):
        from uuid import uuid4

        from axiom_core.pipe_client import PipeClient

        client = PipeClient()
        result = client.execute_tool(
            tool_name="InventoryModel",
            args={},
            simulate=True,
            step_id=uuid4(),
        )
        all_params = []
        for elem in result.output_data["elements"]:
            all_params.extend(elem["Parameters"])

        read_only = [p for p in all_params if p["IsReadOnly"]]
        writable = [p for p in all_params if not p["IsReadOnly"]]
        assert len(read_only) > 0
        assert len(writable) > 0


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestInventoryRegistry:
    def test_inventory_model_registered(self):
        registry = get_default_registry()
        meta = registry.get("InventoryModel")
        assert meta is not None
        assert meta.status == "validated"
        assert meta.supports_simulate is True
        assert meta.requires_revit_document is True

    def test_inventory_model_in_names(self):
        registry = get_default_registry()
        assert "InventoryModel" in registry.list_names()


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

class TestInventoryStorage:
    def test_write_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            result = write_jsonl(MOCK_ELEMENTS, path)
            assert result.exists()
            lines = result.read_text().strip().split("\n")
            assert len(lines) == len(MOCK_ELEMENTS)
            first = json.loads(lines[0])
            assert first["ElementId"] == 100001

    def test_write_elements_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "elements.parquet"
            result = write_elements_parquet(
                MOCK_ELEMENTS, path, run_id="test_run", source_model="Test Model",
            )
            assert result.exists()
            table = pq.read_table(str(result))
            assert table.num_rows == len(MOCK_ELEMENTS)
            assert "element_id" in table.schema.names
            assert "run_id" in table.schema.names
            assert "source_model" in table.schema.names
            assert "level_id" in table.schema.names
            assert "category" in table.schema.names
            assert "is_type" in table.schema.names

    def test_write_elements_parquet_run_id_populated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "elements.parquet"
            write_elements_parquet(
                MOCK_ELEMENTS, path, run_id="run_123", source_model="Sample.rvt",
            )
            table = pq.read_table(str(path))
            run_ids = table.column("run_id").to_pylist()
            assert all(r == "run_123" for r in run_ids)
            models = table.column("source_model").to_pylist()
            assert all(m == "Sample.rvt" for m in models)

    def test_write_parameters_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "parameters.parquet"
            result = write_parameters_parquet(MOCK_ELEMENTS, path, run_id="test_run")
            assert result.exists()
            table = pq.read_table(str(result))
            total_params = sum(len(e.get("Parameters", [])) for e in MOCK_ELEMENTS)
            assert table.num_rows == total_params
            assert "param_name" in table.schema.names
            assert "storage_type" in table.schema.names
            assert "is_read_only" in table.schema.names
            assert "is_instance_param" in table.schema.names
            assert "parameter_group" in table.schema.names
            assert "value_number" in table.schema.names
            assert "value_integer" in table.schema.names
            assert "run_id" in table.schema.names

    def test_parameters_parquet_instance_vs_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "parameters.parquet"
            write_parameters_parquet(MOCK_ELEMENTS, path, run_id="test_run")
            table = pq.read_table(str(path))
            is_instance = table.column("is_instance_param").to_pylist()
            # Last element (WallType) is IsType=True → is_instance_param=False
            # Its params should be is_instance_param=False
            assert False in is_instance
            assert True in is_instance

    def test_persist_inventory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(
                MOCK_ELEMENTS,
                Path(tmpdir),
                "test_run",
                source_model="Test Project.rvt",
            )
            assert "jsonl" in paths
            assert "elements_parquet" in paths
            assert "parameters_parquet" in paths
            assert paths["jsonl"].exists()
            assert paths["elements_parquet"].exists()
            assert paths["parameters_parquet"].exists()

    def test_empty_elements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(
                EMPTY_ELEMENTS,
                Path(tmpdir),
                "empty_run",
            )
            assert paths["jsonl"].exists()
            assert paths["elements_parquet"].exists()
            assert paths["parameters_parquet"].exists()
            # JSONL should be empty
            assert paths["jsonl"].read_text().strip() == ""

    def test_empty_elements_parquet_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "elements.parquet"
            write_elements_parquet(EMPTY_ELEMENTS, path, run_id="empty")
            table = pq.read_table(str(path))
            # Should have schema even when empty
            for field in ELEMENT_PARQUET_SCHEMA:
                assert field.name in table.schema.names

    def test_empty_parameters_parquet_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "parameters.parquet"
            write_parameters_parquet(EMPTY_ELEMENTS, path, run_id="empty")
            table = pq.read_table(str(path))
            for field in PARAMETER_PARQUET_SCHEMA:
                assert field.name in table.schema.names

    def test_grids_and_levels_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(
                GRIDS_AND_LEVELS_ELEMENTS,
                Path(tmpdir),
                "grids_levels_run",
            )
            table = pq.read_table(str(paths["elements_parquet"]))
            assert table.num_rows == 3
            categories = table.column("category").to_pylist()
            assert "Grids" in categories
            assert "Levels" in categories

    def test_families_and_types_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(
                FAMILIES_AND_TYPES_ELEMENTS,
                Path(tmpdir),
                "families_run",
            )
            table = pq.read_table(str(paths["elements_parquet"]))
            assert table.num_rows == 2
            is_types = table.column("is_type").to_pylist()
            assert True in is_types
            assert False in is_types
            family_names = table.column("family_name").to_pylist()
            assert "Fixed" in family_names

    def test_duplicate_param_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(
                DUPLICATE_PARAM_ELEMENTS,
                Path(tmpdir),
                "dup_run",
            )
            table = pq.read_table(str(paths["parameters_parquet"]))
            names = table.column("param_name").to_pylist()
            assert names.count("Comments") == 2

    def test_large_inventory(self):
        large = _make_large_inventory(200)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = persist_inventory(large, Path(tmpdir), "large_run")
            table = pq.read_table(str(paths["elements_parquet"]))
            assert table.num_rows == 200
            ptable = pq.read_table(str(paths["parameters_parquet"]))
            assert ptable.num_rows == 200 * 3

    def test_missing_level_elements(self):
        elems = [
            {
                "ElementId": 700001,
                "UniqueId": "mock-nolevel-001",
                "Category": "Furniture",
                "ClassName": "FamilyInstance",
                "Name": "Desk",
                "FamilyName": "Office Desk",
                "TypeName": "Standard",
                "LevelName": "",
                "LevelId": 0,
                "WorksetName": "",
                "IsType": False,
                "Parameters": [],
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "elements.parquet"
            write_elements_parquet(elems, path, run_id="nolevel")
            table = pq.read_table(str(path))
            assert table.column("level_name").to_pylist() == [""]
            assert table.column("level_id").to_pylist() == [0]

    def test_sqlite_round_trip(self):
        from axiom_core.models import Base
        from sqlalchemy import create_engine, text

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import sessionmaker as sm

        sf = sm(bind=engine)
        write_to_sqlite(
            MOCK_ELEMENTS, "sqlite_run", session_factory=sf, source_model="Test.rvt",
        )
        with engine.connect() as conn:
            # Query all params for a specific element
            rows = conn.execute(
                text("SELECT * FROM inventory_parameters WHERE element_id = 100001")
            ).fetchall()
            assert len(rows) == 2

            # Query all elements with a given parameter name
            rows = conn.execute(
                text("SELECT DISTINCT element_id FROM inventory_parameters WHERE param_name = 'Width'")
            ).fetchall()
            # Door has Width, WallType has Width
            assert len(rows) == 2

            # Instance vs type params
            rows = conn.execute(
                text("SELECT * FROM inventory_parameters WHERE is_instance_param = 0")
            ).fetchall()
            # WallType params (Width, Function) → not instance
            assert len(rows) == 1  # only 1 type element in MOCK_ELEMENTS

            # Run comparison: check run_id consistency
            rows = conn.execute(
                text("SELECT DISTINCT run_id FROM inventory_elements")
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "sqlite_run"

            # Source model recorded
            rows = conn.execute(
                text("SELECT DISTINCT source_model FROM inventory_elements")
            ).fetchall()
            assert rows[0][0] == "Test.rvt"


# ---------------------------------------------------------------------------
# Summary report tests
# ---------------------------------------------------------------------------

class TestInventorySummary:
    def test_summary_generated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
                duration_ms=150,
                source_model="Sample.rvt",
            )
            assert path.exists()
            content = path.read_text()
            assert "Model Inventory Summary" in content
            assert "test_run" in content
            assert "Sample.rvt" in content

    def test_summary_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
            )
            content = path.read_text()
            # 3 instances (wall, door, level), 1 type (walltype)
            assert "| Element instances | 3 |" in content
            assert "| Element types | 1 |" in content

    def test_summary_category_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
            )
            content = path.read_text()
            assert "Walls" in content
            assert "Doors" in content
            assert "Levels" in content

    def test_summary_read_only_vs_writable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
            )
            content = path.read_text()
            assert "Read-only parameters" in content
            assert "Writable parameters" in content

    def test_summary_missing_level(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
            )
            content = path.read_text()
            # Level element has no LevelName
            assert "Instances missing level" in content

    def test_summary_empty_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                EMPTY_ELEMENTS,
                "empty_run",
                Path(tmpdir),
            )
            content = path.read_text()
            assert "| Element instances | 0 |" in content
            assert "| Element types | 0 |" in content
            assert "| Total parameters | 0 |" in content

    def test_summary_source_model_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_summary(
                MOCK_ELEMENTS,
                "test_run",
                Path(tmpdir),
            )
            content = path.read_text()
            assert "(unknown)" in content


# ---------------------------------------------------------------------------
# Parquet schema completeness tests
# ---------------------------------------------------------------------------

class TestParquetSchemas:
    def test_element_schema_has_required_fields(self):
        expected = [
            "run_id", "source_model", "element_id", "unique_id",
            "category", "class_name", "name", "family_name", "type_name",
            "level_name", "level_id", "workset_name", "is_type", "parameter_count",
        ]
        actual = [f.name for f in ELEMENT_PARQUET_SCHEMA]
        for field in expected:
            assert field in actual, f"Missing element schema field: {field}"

    def test_parameter_schema_has_required_fields(self):
        expected = [
            "run_id", "element_id", "param_name", "storage_type",
            "value_string", "value_number", "value_integer",
            "built_in_parameter_id", "is_read_only",
            "is_instance_param", "parameter_group",
        ]
        actual = [f.name for f in PARAMETER_PARQUET_SCHEMA]
        for field in expected:
            assert field in actual, f"Missing parameter schema field: {field}"


# ---------------------------------------------------------------------------
# Review / summary read-back tests
# ---------------------------------------------------------------------------

class TestInventoryReview:
    """Tests for inventory review utilities that read from Parquet artifacts."""

    def _create_run(self, tmpdir: str, elements: list[dict],
                    run_id: str = "test_run",
                    source_model: str = "Test.rvt") -> Path:
        """Helper: persist inventory to a temp run dir and return base path."""
        base = Path(tmpdir)
        persist_inventory(
            elements, base, run_id, source_model=source_model,
        )
        return base

    def test_load_summary_basic(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run")
            assert s.run_id == "test_run"
            assert s.source_model == "Test.rvt"
            assert s.total_instances == 3  # wall, door, level
            assert s.total_types == 1  # walltype
            assert s.total_elements == 4
            assert s.total_parameters > 0
            assert s.read_only_params > 0
            assert s.writable_params > 0

    def test_load_summary_instance_vs_type_params(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run")
            assert s.instance_params > 0
            assert s.type_params > 0
            assert s.instance_params + s.type_params == s.total_parameters

    def test_load_summary_category_counts(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run")
            assert "Walls" in s.category_counts
            assert "Doors" in s.category_counts
            assert "Levels" in s.category_counts

    def test_load_summary_top_param_names(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run")
            param_names = [name for name, _ in s.top_param_names]
            assert "Width" in param_names  # appears on door + walltype
            assert "Length" in param_names

    def test_load_summary_missing_level(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run")
            # Level element itself has no LevelName
            assert s.missing_level_count >= 1

    def test_filter_by_category(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run", category_filter="Walls")
            # Only wall instance + wall type
            assert s.total_elements == 2
            assert all("Walls" in cat for cat in s.category_counts)

    def test_filter_by_param_name(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run", param_name_filter="Width")
            # Width appears on door (instance) and walltype (type)
            assert s.total_parameters == 2
            assert all(name == "Width" for name, _ in s.top_param_names)

    def test_filter_writable_only(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            s = load_summary(base / "test_run", writable_only=True)
            assert s.read_only_params == 0
            assert s.writable_params == s.total_parameters
            assert s.total_parameters > 0

    def test_find_latest_run(self):
        from axiom_core.inventory.review import find_latest_run

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Create two runs
            persist_inventory(MOCK_ELEMENTS, base, "inv_20260101_100000")
            persist_inventory(MOCK_ELEMENTS, base, "inv_20260102_100000")
            latest = find_latest_run(base)
            assert latest is not None
            assert latest.name == "inv_20260102_100000"

    def test_find_latest_run_empty(self):
        from axiom_core.inventory.review import find_latest_run

        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_latest_run(Path(tmpdir))
            assert result is None

    def test_find_latest_run_nonexistent(self):
        from axiom_core.inventory.review import find_latest_run

        result = find_latest_run(Path("/nonexistent/path"))
        assert result is None

    def test_load_summary_empty_run(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, EMPTY_ELEMENTS, run_id="empty")
            s = load_summary(base / "empty")
            assert s.total_elements == 0
            assert s.total_parameters == 0

    def test_load_summary_large_inventory(self):
        from axiom_core.inventory.review import load_summary

        large = _make_large_inventory(100)
        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, large, run_id="large")
            s = load_summary(base / "large")
            assert s.total_elements == 100
            assert s.total_parameters == 300  # 100 elements * 3 params each

    def test_combined_filters(self):
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            base = self._create_run(tmpdir, MOCK_ELEMENTS)
            # Walls + writable only
            s = load_summary(
                base / "test_run",
                category_filter="Walls",
                writable_only=True,
            )
            # Wall instance has Comments (writable), WallType has Function (writable)
            assert s.total_parameters > 0
            assert s.read_only_params == 0
