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
        assert result.params.get("SummaryOnly") is True
        assert result.params.get("ScanMode") == "summary"

    def test_inventory_model_lowercase(self):
        result = resolve_prompt("inventory model")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.params.get("SummaryOnly") is True

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

    # --- Staged inventory prompts ---

    def test_full_inventory_blocked(self):
        """Full inventory scan is disabled — must return clarification_needed."""
        result = resolve_prompt("Run full InventoryModel")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.status == "clarification_needed"
        assert "disabled" in result.clarification_message.lower()
        assert result.params == {}

    def test_inventory_sample(self):
        result = resolve_prompt("Run InventoryModel sample")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.params.get("SummaryOnly") is False
        assert result.params.get("MaxElements") == 100
        assert result.params.get("ScanMode") == "sample"

    def test_inventory_category_walls(self):
        result = resolve_prompt("Run InventoryModel for Walls")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.params.get("SummaryOnly") is False
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("ScanMode") == "category"

    def test_inventory_category_doors(self):
        result = resolve_prompt("Inventory doors")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.params.get("CategoryFilter") == ["Doors"]
        assert result.params.get("ScanMode") == "category"

    def test_inventory_parameters_for_category(self):
        result = resolve_prompt("Inventory parameters for windows")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.params.get("CategoryFilter") == ["Windows"]

    def test_default_is_summary_safe(self):
        """Default 'Run InventoryModel' should be summary-only (no parameter dump)."""
        result = resolve_prompt("Run InventoryModel")
        assert result.params.get("SummaryOnly") is True
        assert result.params.get("IncludeParameters") is False
        assert result.params.get("ScanMode") == "summary"

    def test_full_inventory_keyword_blocked(self):
        """'full inventory' keyword is also blocked."""
        result = resolve_prompt("full inventory")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.status == "clarification_needed"
        assert "disabled" in result.clarification_message.lower()

    def test_full_scan_keyword_blocked(self):
        """'full scan' keyword is also blocked."""
        result = resolve_prompt("Run full scan InventoryModel")
        assert result is not None
        assert result.status == "clarification_needed"

    def test_complete_inventory_blocked(self):
        """'complete inventory' keyword is also blocked."""
        result = resolve_prompt("Run complete inventory")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "disabled" in result.clarification_message.lower()

    def test_safe_modes_still_work(self):
        """Summary, sample, and category modes must remain functional."""
        summary = resolve_prompt("Run InventoryModel")
        assert summary.status == "resolved"
        assert summary.params.get("ScanMode") == "summary"

        sample = resolve_prompt("Run InventoryModel sample")
        assert sample.status == "resolved"
        assert sample.params.get("ScanMode") == "sample"

        category = resolve_prompt("Run InventoryModel for Walls")
        assert category.status == "resolved"
        assert category.params.get("ScanMode") == "category"

    # --- Inventory plan prompt ---

    def test_inventory_plan_prompt(self):
        """'inventory plan' resolves to InventoryPlan with guidance."""
        result = resolve_prompt("Create an inventory plan")
        assert result is not None
        assert result.capability_name == "InventoryPlan"
        assert result.status == "clarification_needed"
        assert "axiom inventory-plan" in result.clarification_message

    def test_extraction_plan_prompt(self):
        """'extraction plan' also resolves to InventoryPlan."""
        result = resolve_prompt("Build an extraction plan for my model")
        assert result is not None
        assert result.capability_name == "InventoryPlan"
        assert result.status == "clarification_needed"

    # --- Level-based inventory prompts ---

    def test_inventory_on_level(self):
        """'Run InventoryModel on Level 1' resolves to level scan."""
        result = resolve_prompt("Run InventoryModel on Level 1")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "level"
        assert result.params.get("LevelFilter") == ["1"]
        assert result.params.get("SummaryOnly") is False

    def test_inventory_for_level_ground(self):
        """'Run InventoryModel for Level Ground' resolves to level scan."""
        result = resolve_prompt("Run InventoryModel for Level Ground")
        assert result is not None
        assert result.params.get("ScanMode") == "level"
        assert result.params.get("LevelFilter") == ["Ground"]

    # --- Category + level inventory prompts ---

    def test_inventory_category_on_level(self):
        """'Run InventoryModel for Walls on Level 1' resolves to category+level."""
        result = resolve_prompt("Run InventoryModel for Walls on Level 1")
        assert result is not None
        assert result.capability_name == "InventoryModel"
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_level"
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("LevelFilter") == ["1"]

    def test_inventory_doors_level_2(self):
        """Category+level combined scan for Doors on Level 2."""
        result = resolve_prompt("Inventory doors on Level 2")
        assert result is not None
        assert result.params.get("ScanMode") == "category_level"
        assert result.params.get("CategoryFilter") == ["Doors"]
        assert result.params.get("LevelFilter") == ["2"]

    # --- Batch size (continuation extraction) ---

    def test_inventory_category_with_max(self):
        """'Run InventoryModel for Walls max 500' sets batch size."""
        result = resolve_prompt("Run InventoryModel for Walls max 500")
        assert result is not None
        assert result.params.get("ScanMode") == "category"
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("BatchSize") == 500

    def test_inventory_level_with_limit(self):
        """'Run InventoryModel on Level 1 limit 1000' sets batch size."""
        result = resolve_prompt("Run InventoryModel on Level 1 limit 1000")
        assert result is not None
        assert result.params.get("ScanMode") == "level"
        assert result.params.get("BatchSize") == 1000

    def test_inventory_category_level_with_max(self):
        """Category+level+max combined sets batch size."""
        result = resolve_prompt("Run InventoryModel for Walls on Level 1 max 200")
        assert result is not None
        assert result.params.get("ScanMode") == "category_level"
        assert result.params.get("BatchSize") == 200

    # --- Full scan blocked with enhanced guidance ---

    def test_full_scan_message_contains_workflow(self):
        """Blocked message includes step-by-step safe workflow."""
        result = resolve_prompt("Run full InventoryModel")
        msg = result.clarification_message
        assert "summary" in msg.lower()
        assert "inventory-plan" in msg
        assert "category scan" in msg.lower() or "category" in msg.lower()
        assert "level" in msg.lower()
        assert "Do not run unbounded" in msg

    # --- No unbounded path ---

    def test_no_prompt_executes_unbounded(self):
        """Verify that no inventory prompt path resolves to full scan mode."""
        prompts = [
            "Run InventoryModel",
            "Run InventoryModel sample",
            "Run InventoryModel for Walls",
            "Inventory doors",
            "Run InventoryModel on Level 1",
            "Run InventoryModel for Walls on Level 1",
            "Run InventoryModel for Walls max 500",
            "inventory plan",
            "Run InventoryModel schema",
            "Run InventoryModel sample values",
            "Run InventoryModel for Walls schema",
            "Run InventoryModel for Walls sample values",
            "Run InventoryModel batch 100",
        ]
        for prompt_text in prompts:
            result = resolve_prompt(prompt_text)
            assert result is not None, f"Prompt '{prompt_text}' returned None"
            scan_mode = result.params.get("ScanMode", "")
            assert scan_mode != "full", (
                f"Prompt '{prompt_text}' resolved to ScanMode='full' — "
                "unbounded full extraction must never execute"
            )

    def test_planner_output_gives_safe_commands(self):
        """Planner output expected_prompt fields suggest safe commands only."""
        from axiom_core.inventory.extraction_planner import build_extraction_plan

        plan = build_extraction_plan(
            {"Walls": 5000, "Doors": 200, "Pipes": 15000},
            run_id="safe_cmd_test",
        )
        for job in plan.jobs:
            assert job.expected_prompt, f"Job {job.plan_id} has no expected_prompt"
            lower = job.expected_prompt.lower()
            assert "full" not in lower, (
                f"Job {job.plan_id} suggests 'full' in expected_prompt: "
                f"{job.expected_prompt}"
            )

    def test_summary_feeds_planner(self):
        """Summary-mode JSON with category_counts can feed the planner."""
        from axiom_core.inventory.extraction_planner import build_extraction_plan

        summary_data = {
            "document_title": "Test Model",
            "instance_count": 10000,
            "type_count": 500,
            "category_counts": {
                "Walls": 3000,
                "Doors": 800,
                "Windows": 600,
                "Pipes": 4000,
                "Ducts": 1500,
            },
            "elements": [],
        }
        plan = build_extraction_plan(
            summary_data["category_counts"],
            run_id="summary_feed_test",
            source_model=summary_data["document_title"],
            total_instance_count=summary_data["instance_count"],
        )
        assert len(plan.jobs) > 0
        total_planned = sum(j.estimated_element_count for j in plan.jobs)
        assert total_planned == 9900  # 3000+800+600+4000+1500
        assert plan.source_model == "Test Model"


# ---------------------------------------------------------------------------
# Batched/continuation extraction tests
# ---------------------------------------------------------------------------

class TestBatchedExtraction:
    """Tests for paginated/continuation inventory extraction."""

    def test_batch_keyword_sets_batch_size(self):
        """'batch 10000' sets BatchSize param for continuation extraction."""
        result = resolve_prompt("Run InventoryModel for Walls batch 10000")
        assert result is not None
        assert result.params.get("BatchSize") == 10000
        assert result.params.get("ScanMode") == "category"
        assert "Batched extraction: 10000 elements per batch" in result.assumptions

    def test_limit_keyword_sets_batch_size(self):
        """'limit 5000' sets BatchSize for continuation (not hard cap)."""
        result = resolve_prompt("Run InventoryModel for Walls limit 5000")
        assert result is not None
        assert result.params.get("BatchSize") == 5000
        assert "MaxElements" not in result.params

    def test_max_keyword_sets_batch_size(self):
        """'max 3000' sets BatchSize for continuation."""
        result = resolve_prompt("Run InventoryModel for Doors max 3000")
        assert result is not None
        assert result.params.get("BatchSize") == 3000
        assert result.params.get("CategoryFilter") == ["Doors"]

    def test_batch_with_level_filter(self):
        """Batch size works with level filter."""
        result = resolve_prompt("Run InventoryModel on Level 1 batch 10000")
        assert result is not None
        assert result.params.get("BatchSize") == 10000
        assert result.params.get("ScanMode") == "level"
        assert result.params.get("LevelFilter") == ["1"]

    def test_batch_with_category_level(self):
        """Batch size works with category+level."""
        result = resolve_prompt(
            "Run InventoryModel for Walls on Level 1 batch 10000"
        )
        assert result is not None
        assert result.params.get("BatchSize") == 10000
        assert result.params.get("ScanMode") == "category_level"
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("LevelFilter") == ["1"]

    def test_sample_mode_ignores_batch(self):
        """Sample mode should not pick up batch keyword."""
        result = resolve_prompt("Run InventoryModel sample")
        assert result is not None
        assert result.params.get("ScanMode") == "sample"
        assert result.params.get("MaxElements") == 100
        assert "BatchSize" not in result.params

    def test_whole_model_batch_defaults_to_schema(self):
        """'Run InventoryModel batch 100' resolves to schema (not full values)."""
        result = resolve_prompt("Run InventoryModel batch 100")
        assert result is not None
        assert result.params.get("ScanMode") == "object_schema"
        assert result.params.get("BatchSize") == 100
        assert result.params.get("SummaryOnly") is False
        assert result.params.get("SchemaOnly") is True
        assert result.params.get("IncludeParameters") is False

    def test_whole_model_limit_defaults_to_schema(self):
        """'Run InventoryModel limit 10000' resolves to schema."""
        result = resolve_prompt("Run InventoryModel limit 10000")
        assert result is not None
        assert result.params.get("ScanMode") == "object_schema"
        assert result.params.get("BatchSize") == 10000
        assert result.params.get("SchemaOnly") is True

    def test_whole_model_batch_is_not_full_scan(self):
        """Whole-model batch is distinct from blocked full scan."""
        batch_result = resolve_prompt("Run InventoryModel batch 500")
        full_result = resolve_prompt("Run full InventoryModel")
        assert batch_result.status == "resolved"
        assert full_result.status == "clarification_needed"
        assert batch_result.params.get("ScanMode") == "object_schema"

    def test_bare_inventory_still_summary(self):
        """Bare 'Run InventoryModel' (no batch number) stays summary."""
        result = resolve_prompt("Run InventoryModel")
        assert result is not None
        assert result.params.get("ScanMode") == "summary"
        assert result.params.get("SummaryOnly") is True

    def test_batch_10000_category_still_value_extraction(self):
        """Category batch still does value extraction (not schema)."""
        result = resolve_prompt("Run InventoryModel for Walls limit 10000")
        assert result is not None
        assert result.params.get("BatchSize") == 10000
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("SummaryOnly") is False
        assert result.params.get("IncludeParameters") is True
        assert result.params.get("ScanMode") == "category"

    def test_object_schema_whole_model(self):
        """'Run InventoryModel schema' resolves to object schema (element inventory)."""
        result = resolve_prompt("Run InventoryModel schema")
        assert result is not None
        assert result.params.get("ScanMode") == "object_schema"
        assert result.params.get("SchemaOnly") is True
        assert result.params.get("SummaryOnly") is False
        assert result.params.get("IncludeParameters") is False

    def test_object_schema_with_batch(self):
        """'Run InventoryModel schema batch 500' resolves to object schema with batch."""
        result = resolve_prompt("Run InventoryModel schema batch 500")
        assert result is not None
        assert result.params.get("ScanMode") == "object_schema"
        assert result.params.get("SchemaOnly") is True
        assert result.params.get("BatchSize") == 500

    def test_object_schema_category(self):
        """'Run InventoryModel for Walls schema' resolves to category object schema."""
        result = resolve_prompt("Run InventoryModel for Walls schema")
        assert result is not None
        assert result.params.get("ScanMode") == "category_object_schema"
        assert result.params.get("SchemaOnly") is True
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("IncludeParameters") is False

    def test_parameter_schema_whole_model_blocked(self):
        """'Run InventoryModel parameter schema' is blocked (crashed Revit 2027)."""
        result = resolve_prompt("Run InventoryModel parameter schema")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "disabled" in result.clarification_message.lower() or \
               "blocked" in result.clarification_message.lower()
        assert "category" in result.clarification_message.lower()

    def test_parameter_schema_with_batch_blocked(self):
        """'Run InventoryModel parameter schema batch 500' is blocked (no category/level)."""
        result = resolve_prompt("Run InventoryModel parameter schema batch 500")
        assert result is not None
        assert result.status == "clarification_needed"

    def test_param_schema_alias_blocked(self):
        """'Run InventoryModel param schema' is blocked (whole-model)."""
        result = resolve_prompt("Run InventoryModel param schema")
        assert result is not None
        assert result.status == "clarification_needed"

    def test_parameter_schema_category(self):
        """'Run InventoryModel for Walls parameter schema' resolves to category parameter schema."""
        result = resolve_prompt("Run InventoryModel for Walls parameter schema")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_parameter_schema"
        assert result.params.get("ParameterSchemaOnly") is True
        assert result.params.get("CategoryFilter") == ["Walls"]

    def test_parameter_schema_ceilings(self):
        """'Run InventoryModel for Ceilings parameter schema' resolves correctly."""
        result = resolve_prompt("Run InventoryModel for Ceilings parameter schema")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_parameter_schema"
        assert result.params.get("CategoryFilter") == ["Ceilings"]

    def test_parameter_schema_plumbing(self):
        """'Run InventoryModel for Plumbing Fixtures parameter schema' resolves correctly."""
        result = resolve_prompt("Run InventoryModel for Plumbing Fixtures parameter schema")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_parameter_schema"
        assert result.params.get("CategoryFilter") == ["Plumbing Fixtures"]

    def test_parameter_schema_on_level(self):
        """'Run InventoryModel parameter schema on Level 1' resolves with level constraint."""
        result = resolve_prompt("Run InventoryModel parameter schema on Level 1")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_parameter_schema"
        assert result.params.get("ParameterSchemaOnly") is True
        assert result.params.get("LevelFilter") == ["1"]

    def test_parameter_schema_category_and_level(self):
        """'Run InventoryModel for Walls on Level 1 parameter schema' resolves with both."""
        result = resolve_prompt("Run InventoryModel for Walls on Level 1 parameter schema")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_parameter_schema"
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("LevelFilter") == ["1"]

    def test_sample_values_whole_model_blocked(self):
        """'Run InventoryModel sample values' is blocked (crashed Revit 2027)."""
        result = resolve_prompt("Run InventoryModel sample values")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "blocked" in result.clarification_message.lower() or \
               "disabled" in result.clarification_message.lower()
        assert "constrained" in result.clarification_message.lower() or \
               "category" in result.clarification_message.lower()

    def test_sample_values_category(self):
        """'Run InventoryModel for Walls sample values' resolves correctly."""
        result = resolve_prompt("Run InventoryModel for Walls sample values")
        assert result is not None
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("SampleValues") is True
        assert result.params.get("SampleLimit") == 5
        assert result.params.get("MaxElements") == 25
        assert result.params.get("CategoryFilter") == ["Walls"]

    def test_sample_values_for_category_alternate_syntax(self):
        """'Run InventoryModel sample values for Walls' works."""
        result = resolve_prompt("Run InventoryModel sample values for Walls")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("SampleValues") is True
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("MaxElements") == 25
        assert result.params.get("SampleLimit") == 5

    def test_sample_values_with_max(self):
        """'Run InventoryModel sample values for Walls max 25' uses explicit max."""
        result = resolve_prompt("Run InventoryModel sample values for Walls max 25")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("MaxElements") == 25
        assert result.params.get("SampleLimit") == 5

    def test_sample_values_on_level(self):
        """'Run InventoryModel sample values on Level 1 max 25' works."""
        result = resolve_prompt("Run InventoryModel sample values on Level 1 max 25")
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("LevelFilter") == ["1"]
        assert result.params.get("MaxElements") == 25

    def test_sample_values_category_and_level(self):
        """'Run InventoryModel sample values for Walls on Level 1 max 25' works."""
        result = resolve_prompt(
            "Run InventoryModel sample values for Walls on Level 1 max 25"
        )
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("CategoryFilter") == ["Walls"]
        assert result.params.get("LevelFilter") == ["1"]
        assert result.params.get("MaxElements") == 25

    def test_sample_values_plumbing_fixtures(self):
        """'Run InventoryModel sample values for Plumbing Fixtures' works."""
        result = resolve_prompt(
            "Run InventoryModel sample values for Plumbing Fixtures"
        )
        assert result is not None
        assert result.status == "resolved"
        assert result.params.get("ScanMode") == "category_sample_values"
        assert result.params.get("CategoryFilter") == ["Plumbing Fixtures"]

    def test_full_values_blocked(self):
        """'Run InventoryModel full values' is blocked."""
        result = resolve_prompt("Run InventoryModel full values")
        assert result.status == "clarification_needed"

    def test_blocked_message_mentions_schema(self):
        """Full scan blocked message mentions schema discovery."""
        result = resolve_prompt("Run full InventoryModel")
        assert "schema" in result.clarification_message.lower()
        assert "sample" in result.clarification_message.lower()

    def test_no_batch_unbounded(self):
        """No prompt path resolves to full/unbounded value extraction."""
        prompts = [
            "Run InventoryModel for Walls batch 10000",
            "Run InventoryModel on Level 1 limit 5000",
            "Run InventoryModel for Doors max 3000",
            "Run InventoryModel for Walls on Level 1 batch 10000",
            "Run InventoryModel batch 100",
            "Run InventoryModel batch 500",
            "Run InventoryModel schema",
            "Run InventoryModel sample values for Walls",
        ]
        for prompt_text in prompts:
            result = resolve_prompt(prompt_text)
            assert result is not None
            assert result.params.get("ScanMode") != "full"
            assert result.status == "resolved"

    def test_whole_model_sample_values_always_blocked(self):
        """No prompt path lets unconstrained sample values through."""
        prompts = [
            "Run InventoryModel sample values",
            "Run InventoryModel sample value",
        ]
        for prompt_text in prompts:
            result = resolve_prompt(prompt_text)
            assert result is not None
            assert result.status == "clarification_needed"

    def test_whole_model_parameter_schema_always_blocked(self):
        """No prompt path lets unconstrained parameter schema through."""
        prompts = [
            "Run InventoryModel parameter schema",
            "Run InventoryModel param schema",
            "Run InventoryModel parameter schema batch 500",
        ]
        for prompt_text in prompts:
            result = resolve_prompt(prompt_text)
            assert result is not None
            assert result.status == "clarification_needed"


class TestInventoryCombineCLI:
    """Tests for the inventory-combine CLI command."""

    def test_combine_batch_files(self, tmp_path):
        """Combine multiple batch JSON files into a single output."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        # Create batch files
        for i in range(3):
            batch = {
                "run_id": "batch_test",
                "source_model": "Test Model",
                "instance_count": 10,
                "type_count": 0,
                "parameter_count": 5,
                "error_count": 0,
                "category_counts": {"Walls": 5, "Doors": 5},
                "elements": [
                    {"ElementId": 100 + i * 10 + j, "Category": "Walls" if j < 5 else "Doors"}
                    for j in range(10)
                ],
            }
            (tmp_path / f"batch_{i+1:03d}.json").write_text(json.dumps(batch))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-combine",
            "--batch-dir", str(tmp_path),
            "--output-dir", str(tmp_path / "output"),
            "--run-id", "combine_test",
        ])

        assert result.exit_code == 0
        assert "Combined 3 batches" in result.output
        assert "30 elements" in result.output

        # Check metadata
        meta_path = tmp_path / "output" / "combine_test" / "run_metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["batch_count"] == 3
        assert meta["total_elements"] == 30

    def test_combine_with_manifest(self, tmp_path):
        """Combine via manifest file."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        batch_1 = {
            "source_model": "Model A",
            "instance_count": 5,
            "elements": [{"ElementId": i, "Category": "Walls"} for i in range(5)],
            "category_counts": {"Walls": 5},
        }
        batch_2 = {
            "source_model": "Model A",
            "instance_count": 3,
            "elements": [{"ElementId": 100 + i, "Category": "Doors"} for i in range(3)],
            "category_counts": {"Doors": 3},
        }

        b1_path = tmp_path / "batch_001.json"
        b2_path = tmp_path / "batch_002.json"
        b1_path.write_text(json.dumps(batch_1))
        b2_path.write_text(json.dumps(batch_2))

        manifest = {
            "source_model": "Model A",
            "batch_files": [str(b1_path), str(b2_path)],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-combine",
            "--manifest", str(manifest_path),
            "--output-dir", str(tmp_path / "output"),
            "--run-id", "manifest_test",
        ])

        assert result.exit_code == 0
        assert "Combined 2 batches" in result.output

        meta = json.loads((tmp_path / "output" / "manifest_test" / "run_metadata.json").read_text())
        assert meta["total_elements"] == 8
        assert meta["category_counts"] == {"Walls": 5, "Doors": 3}


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


class TestInventoryImport:
    """Tests for importing Revit inventory JSON exports into the artifact pipeline."""

    def _write_export_json(self, export_dir: Path, elements: list[dict],
                           run_id: str = "inv_20260506_120000",
                           source_model: str = "TestProject.rvt") -> Path:
        """Write a mock inventory export JSON file."""
        export_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": run_id,
            "source_model": source_model,
            "timestamp": "2026-05-06T12:00:00Z",
            "duration_ms": 150,
            "element_count": sum(1 for e in elements if not e.get("IsType", False)),
            "type_count": sum(1 for e in elements if e.get("IsType", False)),
            "parameter_count": sum(len(e.get("Parameters", [])) for e in elements),
            "elements": elements,
        }
        path = export_dir / f"{run_id}.json"
        import json
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_import_from_json_file(self):
        """Import a specific JSON file and verify Parquet artifacts are created."""
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            output_dir = Path(tmpdir) / "artifacts"

            json_path = self._write_export_json(export_dir, MOCK_ELEMENTS)

            # Directly call persist_inventory (same as what the CLI does)
            import json
            with open(json_path, "r") as f:
                data = json.load(f)

            persist_inventory(
                elements=data["elements"],
                output_dir=output_dir,
                run_id=data["run_id"],
                source_model=data["source_model"],
            )

            # Verify artifacts exist
            run_dir = output_dir / "inv_20260506_120000"
            assert (run_dir / "elements.parquet").exists()
            assert (run_dir / "parameters.parquet").exists()
            assert (run_dir / "elements.jsonl").exists()

            # Verify summary can be loaded
            s = load_summary(run_dir)
            assert s.run_id == "inv_20260506_120000"
            assert s.source_model == "TestProject.rvt"
            assert s.total_elements == 4  # 3 instances + 1 type
            assert s.total_parameters > 0

    def test_import_empty_inventory(self):
        """Import an empty inventory JSON and verify clean output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            output_dir = Path(tmpdir) / "artifacts"

            json_path = self._write_export_json(
                export_dir, EMPTY_ELEMENTS, run_id="inv_empty"
            )

            import json
            with open(json_path, "r") as f:
                data = json.load(f)

            persist_inventory(
                elements=data["elements"],
                output_dir=output_dir,
                run_id=data["run_id"],
                source_model=data["source_model"],
            )

            run_dir = output_dir / "inv_empty"
            assert (run_dir / "elements.parquet").exists()
            assert (run_dir / "parameters.parquet").exists()

    def test_import_preserves_parameter_details(self):
        """Verify imported parameters retain storage type, value, and read-only status."""
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            output_dir = Path(tmpdir) / "artifacts"

            json_path = self._write_export_json(export_dir, MOCK_ELEMENTS)

            import json
            with open(json_path, "r") as f:
                data = json.load(f)

            persist_inventory(
                elements=data["elements"],
                output_dir=output_dir,
                run_id=data["run_id"],
                source_model=data["source_model"],
            )

            s = load_summary(output_dir / "inv_20260506_120000")
            assert s.read_only_params > 0
            assert s.writable_params > 0
            assert s.instance_params > 0
            assert s.type_params > 0

    def test_import_latest_finds_newest(self):
        """Verify latest export selection picks the most recent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)

            self._write_export_json(
                export_dir, MOCK_ELEMENTS, run_id="inv_20260501_100000"
            )
            self._write_export_json(
                export_dir, MOCK_ELEMENTS, run_id="inv_20260506_120000"
            )

            json_files = sorted(export_dir.glob("inv_*.json"), reverse=True)
            assert json_files[0].name == "inv_20260506_120000.json"

    def test_import_utf8_bom_json(self):
        """Import a JSON file written with UTF-8 BOM (as Revit/C# may produce)."""
        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            output_dir = Path(tmpdir) / "artifacts"
            export_dir.mkdir(parents=True, exist_ok=True)

            import json as json_mod
            data = {
                "run_id": "inv_bom_test",
                "source_model": "BomTest.rvt",
                "timestamp": "2026-05-06T12:00:00Z",
                "duration_ms": 100,
                "element_count": 3,
                "type_count": 1,
                "parameter_count": 5,
                "elements": MOCK_ELEMENTS,
            }
            bom_path = export_dir / "inv_bom_test.json"
            # Write with UTF-8 BOM prefix (byte order mark)
            bom_path.write_bytes(
                b"\xef\xbb\xbf" + json_mod.dumps(data).encode("utf-8")
            )

            # Read with utf-8-sig (same as inventory-import CLI)
            with open(bom_path, "r", encoding="utf-8-sig") as f:
                loaded = json_mod.load(f)

            persist_inventory(
                elements=loaded["elements"],
                output_dir=output_dir,
                run_id=loaded["run_id"],
                source_model=loaded["source_model"],
            )

            run_dir = output_dir / "inv_bom_test"
            assert (run_dir / "elements.parquet").exists()
            assert (run_dir / "parameters.parquet").exists()

            s = load_summary(run_dir)
            assert s.run_id == "inv_bom_test"
            assert s.source_model == "BomTest.rvt"
            assert s.total_elements == 4

    def test_summary_mode_inventory_zero_parameters(self):
        """Summary-mode run with elements counted but 0 parameters persisted."""
        import json as json_mod

        from axiom_core.inventory.review import load_summary

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "artifacts"

            # Simulate a summary-mode import: elements list is empty,
            # but counts are provided in the top-level JSON
            run_id = "inv_summary_test"
            run_dir = output_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            # Write empty parquet files (as persist_inventory does with [])
            persist_inventory(
                elements=[],
                output_dir=output_dir,
                run_id=run_id,
                source_model="SummaryModel.rvt",
            )

            # Write run_metadata.json (as inventory-import CLI does)
            category_counts = {"Walls": 500, "Doors": 120, "Windows": 80}
            meta = {
                "run_id": run_id,
                "source_model": "SummaryModel.rvt",
                "scan_mode": "summary",
                "instance_count": 600,
                "type_count": 100,
                "parameter_count": 0,
                "category_counts": category_counts,
            }
            meta_path = run_dir / "run_metadata.json"
            meta_path.write_text(json_mod.dumps(meta), encoding="utf-8")

            s = load_summary(run_dir)
            assert s.run_id == run_id
            assert s.source_model == "SummaryModel.rvt"
            assert s.scan_mode == "summary"
            assert s.total_instances == 600
            assert s.total_types == 100
            assert s.total_elements == 700
            assert s.total_parameters == 0
            assert s.category_counts == category_counts


class TestParameterSchemaWorkflow:
    """Tests for the complete parameter discovery workflow."""

    def test_all_requested_categories_resolve(self):
        """All 14 requested categories resolve for parameter schema."""
        categories = [
            "Walls", "Ceilings", "Plumbing Fixtures", "Doors", "Windows",
            "Floors", "Rooms", "Views", "Sheets", "Mechanical Equipment",
            "Lighting Fixtures", "Electrical Fixtures", "Ducts", "Pipes",
        ]
        for cat in categories:
            result = resolve_prompt(f"Run InventoryModel for {cat} parameter schema")
            assert result is not None, f"Failed for {cat}"
            assert result.status == "resolved", f"Not resolved for {cat}: {result.status}"
            assert result.params.get("ScanMode") == "category_parameter_schema", f"Wrong mode for {cat}"
            assert result.params.get("ParameterSchemaOnly") is True, f"Not schema-only for {cat}"

    def test_parameter_schema_output_no_values(self):
        """Parameter schema Parquet schema contains no value columns."""
        from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

        field_names = [f.name for f in PARAMETER_SCHEMA_PARQUET_SCHEMA]
        # Must contain definition fields
        assert "parameter_name" in field_names
        assert "storage_type" in field_names
        assert "built_in_parameter_id" in field_names
        assert "is_read_only" in field_names
        assert "is_instance_param" in field_names
        assert "is_type_param" in field_names
        assert "observed_count" in field_names
        assert "category" in field_names
        assert "class_name" in field_names
        assert "run_id" in field_names
        assert "source_model" in field_names
        assert "scan_mode" in field_names
        # Must NOT contain value columns
        assert "value_string" not in field_names
        assert "value_number" not in field_names
        assert "value_integer" not in field_names
        assert "value_double" not in field_names

    def test_parameter_schema_storage(self, tmp_path):
        """persist_parameter_schema writes JSONL + Parquet files."""
        from axiom_core.inventory.storage import persist_parameter_schema

        param_defs = [
            {
                "ParameterName": "Width",
                "StorageType": "Double",
                "BuiltInParameterId": "WALL_ATTR_WIDTH_PARAM",
                "IsReadOnly": False,
                "IsInstanceParam": True,
                "IsTypeParam": False,
                "ObservedCount": 42,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["FamilyInstance"],
            },
            {
                "ParameterName": "Comments",
                "StorageType": "String",
                "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS",
                "IsReadOnly": False,
                "IsInstanceParam": True,
                "IsTypeParam": False,
                "ObservedCount": 100,
                "ObservedOnCategories": ["Walls", "Doors"],
                "ObservedOnClasses": ["FamilyInstance"],
            },
        ]

        paths = persist_parameter_schema(
            param_defs, tmp_path, "test_run",
            source_model="TestModel.rvt",
        )

        assert "jsonl" in paths
        assert "parquet" in paths
        assert paths["jsonl"].exists()
        assert paths["parquet"].exists()

        # Verify JSONL content
        import json
        with open(paths["jsonl"]) as f:
            lines = [json.loads(line) for line in f]
        assert len(lines) == 2
        assert lines[0]["ParameterName"] == "Width"

        # Verify Parquet content
        import pyarrow.parquet as pq
        table = pq.read_table(str(paths["parquet"]))
        assert table.num_rows == 2
        names = table.column("parameter_name").to_pylist()
        assert "Width" in names
        assert "Comments" in names

    def test_parameter_schema_import_cli(self, tmp_path):
        """inventory-import detects parameter schema JSON and routes correctly."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        # Create a parameter schema JSON
        ps_json = {
            "run_id": "ps_test_001",
            "source_model": "TestModel.rvt",
            "scan_mode": "category_parameter_schema",
            "parameter_definitions": [
                {
                    "ParameterName": "Width",
                    "StorageType": "Double",
                    "BuiltInParameterId": "WALL_ATTR_WIDTH_PARAM",
                    "IsReadOnly": False,
                    "IsInstanceParam": True,
                    "IsTypeParam": False,
                    "ObservedCount": 42,
                    "ObservedOnCategories": ["Walls"],
                    "ObservedOnClasses": ["FamilyInstance"],
                },
            ],
        }
        json_path = tmp_path / "ps_export.json"
        json_path.write_text(json.dumps(ps_json), encoding="utf-8")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(output_dir),
        ])

        assert result.exit_code == 0
        assert "Parameter schema import complete" in result.output

        # Verify artifacts
        run_dir = output_dir / "ps_test_001"
        assert (run_dir / "parameter_schema.jsonl").exists()
        assert (run_dir / "parameter_schema.parquet").exists()
        assert (run_dir / "run_metadata.json").exists()
        assert (run_dir / "summary.md").exists()

    def test_parameter_schema_summary(self, tmp_path):
        """inventory-summary handles parameter schema runs."""
        import json

        from axiom_core.inventory.review import load_summary
        from axiom_core.inventory.storage import persist_parameter_schema

        param_defs = [
            {
                "ParameterName": "Width",
                "StorageType": "Double",
                "BuiltInParameterId": "WALL_ATTR_WIDTH",
                "IsReadOnly": False,
                "IsInstanceParam": True,
                "IsTypeParam": False,
                "ObservedCount": 42,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["FamilyInstance"],
            },
            {
                "ParameterName": "Height",
                "StorageType": "Double",
                "BuiltInParameterId": "WALL_ATTR_HEIGHT",
                "IsReadOnly": True,
                "IsInstanceParam": False,
                "IsTypeParam": True,
                "ObservedCount": 10,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["WallType"],
            },
        ]

        run_id = "ps_summary_test"
        persist_parameter_schema(param_defs, tmp_path, run_id, source_model="TestModel.rvt")

        # Write run_metadata.json
        run_dir = tmp_path / run_id
        meta = {
            "run_id": run_id,
            "source_model": "TestModel.rvt",
            "scan_mode": "category_parameter_schema",
            "parameter_definition_count": 2,
        }
        (run_dir / "run_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        s = load_summary(run_dir)
        assert s.is_parameter_schema is True
        assert s.parameter_definition_count == 2
        assert s.unique_parameter_names == 2
        assert s.read_only_params == 1
        assert s.writable_params == 1
        assert s.instance_params == 1
        assert s.type_params == 1

    def test_planner_parameter_schema_mode(self, tmp_path):
        """inventory-plan --mode parameter-schema produces category-by-category commands."""
        from axiom_core.inventory.extraction_planner import (
            build_parameter_schema_plan,
        )

        category_counts = {
            "Walls": 500,
            "Doors": 120,
            "Ceilings": 78,
            "Plumbing Fixtures": 150,
        }

        plan = build_parameter_schema_plan(
            category_counts,
            run_id="ps_plan_test",
            source_model="TestModel.rvt",
        )

        # Should have one job per category
        assert len(plan.jobs) == 4

        # All jobs should use category_parameter_schema strategy
        for job in plan.jobs:
            assert job.strategy == "category_parameter_schema"
            assert "parameter schema" in job.expected_prompt.lower()
            assert "Run InventoryModel for" in job.expected_prompt

        # Priority categories come first, then remaining smallest-to-largest
        # All 4 categories are priority, so they appear in priority order
        job_cats = [j.categories[0] for j in plan.jobs]
        assert job_cats[0] == "Walls"  # priority order
        assert job_cats[1] == "Doors"

        # No job should recommend whole-model
        for job in plan.jobs:
            assert "Run InventoryModel parameter schema" != job.expected_prompt

        # Warnings should mention blocked
        warning_text = " ".join(plan.warnings)
        assert "blocked" in warning_text.lower()
        assert "whole-model" in warning_text.lower()

    def test_planner_no_whole_model_parameter_schema(self, tmp_path):
        """Planner never recommends unconstrained parameter schema."""
        from axiom_core.inventory.extraction_planner import (
            build_extraction_plan,
        )

        category_counts = {"Walls": 500, "Doors": 120}
        plan = build_extraction_plan(
            category_counts, run_id="test_plan",
        )

        for job in plan.jobs:
            prompt_lower = job.expected_prompt.lower()
            if "parameter schema" in prompt_lower:
                assert "for " in prompt_lower, \
                    f"Unqualified parameter schema in prompt: {job.expected_prompt}"

    def test_registry_builder_dedup(self, tmp_path):
        """parameter-registry-build deduplicates by composite key."""
        import json

        from axiom_core.inventory.storage import persist_parameter_schema

        # Create two runs with overlapping parameter defs
        defs1 = [
            {"ParameterName": "Width", "StorageType": "Double",
             "BuiltInParameterId": "WALL_WIDTH", "IsReadOnly": False,
             "IsInstanceParam": True, "IsTypeParam": False,
             "ObservedCount": 10, "ObservedOnCategories": ["Walls"],
             "ObservedOnClasses": ["FamilyInstance"]},
            {"ParameterName": "Height", "StorageType": "Double",
             "BuiltInParameterId": "WALL_HEIGHT", "IsReadOnly": False,
             "IsInstanceParam": True, "IsTypeParam": False,
             "ObservedCount": 10, "ObservedOnCategories": ["Walls"],
             "ObservedOnClasses": ["FamilyInstance"]},
        ]
        defs2 = [
            {"ParameterName": "Width", "StorageType": "Double",
             "BuiltInParameterId": "WALL_WIDTH", "IsReadOnly": False,
             "IsInstanceParam": True, "IsTypeParam": False,
             "ObservedCount": 5, "ObservedOnCategories": ["Walls"],
             "ObservedOnClasses": ["FamilyInstance"]},
            {"ParameterName": "Depth", "StorageType": "Double",
             "BuiltInParameterId": "WALL_DEPTH", "IsReadOnly": False,
             "IsInstanceParam": True, "IsTypeParam": False,
             "ObservedCount": 8, "ObservedOnCategories": ["Walls"],
             "ObservedOnClasses": ["FamilyInstance"]},
        ]

        persist_parameter_schema(defs1, tmp_path, "run1", source_model="M.rvt")
        persist_parameter_schema(defs2, tmp_path, "run2", source_model="M.rvt")

        from axiom_cli.main import cli
        from click.testing import CliRunner

        out_dir = tmp_path / "registry_out"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "parameter-registry-build",
            "--from-inventory", str(tmp_path),
            "--output-dir", str(out_dir),
            "--run-id", "test_registry",
        ])

        assert result.exit_code == 0
        assert "Property registry built" in result.output

        reg_dir = out_dir / "test_registry"
        assert (reg_dir / "revit_property_registry.jsonl").exists()
        assert (reg_dir / "revit_property_registry.parquet").exists()
        assert (reg_dir / "summary.md").exists()

        # Verify dedup: Width appears in both runs → should be 1 entry, not 2
        with open(reg_dir / "revit_property_registry.jsonl") as f:
            lines = [json.loads(line) for line in f]

        # Should have 3 unique defs (Width deduped, Height + Depth unique)
        assert len(lines) == 3
        names = [row["ParameterName"] for row in lines]
        assert names.count("Width") == 1

        # Width observed_count should be merged: 10 + 5 = 15
        width_row = [row for row in lines if row["ParameterName"] == "Width"][0]
        assert width_row["ObservedCount"] == 15

    def test_parameter_schema_import_with_object_category(self, tmp_path):
        """inventory-import passes through object_category to metadata."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        ps_json = {
            "run_id": "ps_cat_test",
            "source_model": "TestModel.rvt",
            "scan_mode": "category_parameter_schema",
            "object_category": "Ceilings",
            "parameter_definitions": [
                {
                    "ParameterName": "Height Offset From Level",
                    "StorageType": "Double",
                    "BuiltInParameterId": "CEILING_HEIGHTABOVELEVEL_PARAM",
                    "IsReadOnly": False,
                    "IsInstanceParam": True,
                    "IsTypeParam": False,
                    "ObservedCount": 78,
                    "ObservedOnCategories": ["Ceilings"],
                    "ObservedOnClasses": ["FamilyInstance"],
                },
            ],
        }
        json_path = tmp_path / "ps_cat_export.json"
        json_path.write_text(json.dumps(ps_json), encoding="utf-8")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(output_dir),
        ])

        assert result.exit_code == 0
        assert "Object Category" in result.output
        assert "Ceilings" in result.output

        # Verify metadata includes object_category
        run_dir = output_dir / "ps_cat_test"
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        assert meta["object_category"] == "Ceilings"
        assert meta["scan_mode"] == "category_parameter_schema"

    def test_standard_import_with_object_category(self, tmp_path):
        """Standard inventory-import passes through object_category."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        inv_json = {
            "run_id": "inv_cat_test",
            "source_model": "TestModel.rvt",
            "scan_mode": "category",
            "object_category": "Walls",
            "element_count": 500,
            "type_count": 20,
            "parameter_count": 1200,
            "elements": [],
        }
        json_path = tmp_path / "inv_cat_export.json"
        json_path.write_text(json.dumps(inv_json), encoding="utf-8")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(output_dir),
        ])

        assert result.exit_code == 0
        assert "Object Category" in result.output
        assert "Walls" in result.output

        run_dir = output_dir / "inv_cat_test"
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        assert meta["object_category"] == "Walls"

    def test_enriched_fields_in_parquet_schema(self):
        """PARAMETER_SCHEMA_PARQUET_SCHEMA includes enriched metadata fields."""
        from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

        field_names = set(PARAMETER_SCHEMA_PARQUET_SCHEMA.names)
        enriched = {
            "data_type_id", "data_type_label",
            "group_type_id", "group_type_label",
            "is_measurable_spec",
            "unit_type_id", "unit_label",
            "discipline_label",
        }
        assert enriched.issubset(field_names), f"Missing: {enriched - field_names}"

    def test_enriched_fields_persist_in_parquet(self, tmp_path):
        """Enriched metadata fields are written to and read from Parquet."""
        from axiom_core.inventory.storage import write_parameter_schema_parquet

        defs = [{
            "ParameterName": "Height",
            "StorageType": "Double",
            "BuiltInParameterId": "WALL_USER_HEIGHT_PARAM",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 200,
            "ObservedOnCategories": ["Walls"],
            "ObservedOnClasses": ["Wall"],
            "DataTypeId": "autodesk.spec.aec:length-2.0.0",
            "DataTypeLabel": "Length",
            "GroupTypeId": "autodesk.parameter.group:constraints-2.0.0",
            "GroupTypeLabel": "Constraints",
            "IsMeasurableSpec": True,
            "UnitTypeId": "autodesk.unit.unit:millimeters-1.0.1",
            "UnitLabel": "Millimeters",
            "DisciplineLabel": "Common",
        }]

        parquet_path = tmp_path / "ps.parquet"
        write_parameter_schema_parquet(
            defs, parquet_path, run_id="test_run",
            source_model="Test.rvt", scan_mode="category_parameter_schema",
        )

        import pyarrow.parquet as pq
        table = pq.read_table(str(parquet_path))
        assert table.num_rows == 1
        row = {col: table.column(col).to_pylist()[0] for col in table.schema.names}
        assert row["data_type_id"] == "autodesk.spec.aec:length-2.0.0"
        assert row["data_type_label"] == "Length"
        assert row["group_type_id"] == "autodesk.parameter.group:constraints-2.0.0"
        assert row["group_type_label"] == "Constraints"
        assert row["is_measurable_spec"] is True
        assert row["unit_type_id"] == "autodesk.unit.unit:millimeters-1.0.1"
        assert row["unit_label"] == "Millimeters"
        assert row["discipline_label"] == "Common"

    def test_enriched_fields_in_summary(self, tmp_path):
        """inventory-summary reports enriched metadata stats."""
        import json

        from axiom_core.inventory.storage import write_parameter_schema_parquet

        defs = [
            {
                "ParameterName": "Height",
                "StorageType": "Double",
                "ObservedCount": 100,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["Wall"],
                "IsReadOnly": False,
                "IsInstanceParam": True,
                "IsTypeParam": False,
                "DataTypeLabel": "Length",
                "GroupTypeLabel": "Constraints",
                "IsMeasurableSpec": True,
                "DisciplineLabel": "Common",
            },
            {
                "ParameterName": "Width",
                "StorageType": "Double",
                "ObservedCount": 50,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["Wall"],
                "IsReadOnly": True,
                "IsInstanceParam": False,
                "IsTypeParam": True,
                "DataTypeLabel": "Length",
                "GroupTypeLabel": "Dimensions",
                "IsMeasurableSpec": True,
                "DisciplineLabel": "Common",
            },
            {
                "ParameterName": "Mark",
                "StorageType": "String",
                "ObservedCount": 200,
                "ObservedOnCategories": ["Walls"],
                "ObservedOnClasses": ["Wall"],
                "IsReadOnly": False,
                "IsInstanceParam": True,
                "IsTypeParam": False,
                "DataTypeLabel": "Text",
                "GroupTypeLabel": "Identity Data",
                "IsMeasurableSpec": False,
                "DisciplineLabel": "",
            },
        ]

        run_dir = tmp_path / "ps_enriched_run"
        run_dir.mkdir()

        write_parameter_schema_parquet(
            defs, run_dir / "parameter_schema.parquet",
            run_id="test_enr", source_model="Test.rvt",
        )
        meta = {"run_id": "test_enr", "source_model": "Test.rvt",
                "scan_mode": "category_parameter_schema"}
        (run_dir / "run_metadata.json").write_text(json.dumps(meta))

        from axiom_core.inventory.review import load_summary

        summary = load_summary(run_dir)
        assert summary.is_parameter_schema
        assert summary.parameter_definition_count == 3
        assert summary.unique_data_types == 2  # Length, Text
        assert summary.unique_groups == 3  # Constraints, Dimensions, Identity Data
        assert summary.measurable_count == 2  # Height, Width
        assert summary.unique_disciplines == 1  # Common (empty string excluded)

    def test_prompt_traceability_in_parameter_schema_import(self, tmp_path):
        """inventory-import preserves prompt traceability fields in metadata."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        ps_json = {
            "run_id": "ps_trace_test",
            "source_model": "TestModel.rvt",
            "scan_mode": "category_parameter_schema",
            "object_category": "Walls",
            "raw_prompt": "Run InventoryModel for Walls parameter schema",
            "resolved_capability": "InventoryModel",
            "result_class": "success",
            "source": "revit_prompt_dialog",
            "active_view": "Level 1",
            "parameter_definitions": [
                {
                    "ParameterName": "Height",
                    "StorageType": "Double",
                    "BuiltInParameterId": "",
                    "IsReadOnly": False,
                    "IsInstanceParam": True,
                    "IsTypeParam": False,
                    "ObservedCount": 10,
                    "ObservedOnCategories": ["Walls"],
                    "ObservedOnClasses": ["Wall"],
                },
            ],
        }
        json_path = tmp_path / "ps_trace.json"
        json_path.write_text(json.dumps(ps_json), encoding="utf-8")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(output_dir),
        ])

        assert result.exit_code == 0
        assert "Raw prompt" in result.output

        run_dir = output_dir / "ps_trace_test"
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        assert meta["raw_prompt"] == "Run InventoryModel for Walls parameter schema"
        assert meta["resolved_capability"] == "InventoryModel"
        assert meta["result_class"] == "success"
        assert meta["source"] == "revit_prompt_dialog"
        assert meta["active_view"] == "Level 1"

        summary_md = (run_dir / "summary.md").read_text()
        assert "Run InventoryModel for Walls parameter schema" in summary_md

    def test_prompt_traceability_in_standard_import(self, tmp_path):
        """Standard inventory-import preserves prompt traceability fields."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        inv_json = {
            "run_id": "inv_trace_test",
            "source_model": "TestModel.rvt",
            "scan_mode": "category",
            "raw_prompt": "Run InventoryModel for Walls",
            "resolved_capability": "InventoryModel",
            "result_class": "success",
            "source": "revit_prompt_dialog",
            "element_count": 500,
            "type_count": 20,
            "parameter_count": 1200,
            "elements": [],
        }
        json_path = tmp_path / "inv_trace.json"
        json_path.write_text(json.dumps(inv_json), encoding="utf-8")

        output_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(output_dir),
        ])

        assert result.exit_code == 0

        run_dir = output_dir / "inv_trace_test"
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        assert meta["raw_prompt"] == "Run InventoryModel for Walls"
        assert meta["resolved_capability"] == "InventoryModel"

        summary_md = (run_dir / "summary.md").read_text()
        assert "Run InventoryModel for Walls" in summary_md


class TestRegistryCoverageWorkflow:
    """Tests for the full registry coverage workflow."""

    def test_planner_creates_all_category_plan(self):
        """inventory-plan creates plan for all categories with priority ordering."""
        from axiom_core.inventory.extraction_planner import (
            BLOCKED_COMMANDS,
            PRIORITY_CATEGORIES,
            build_parameter_schema_plan,
        )

        category_counts = {
            "Walls": 1241,
            "Doors": 300,
            "Windows": 200,
            "Ceilings": 85,
            "Plumbing Fixtures": 50,
            "Generic Models": 500,
            "Analytical Members": 10,
        }
        plan = build_parameter_schema_plan(
            category_counts, run_id="test_plan", source_model="Test.rvt",
        )
        assert len(plan.jobs) == 7
        # Priority categories come first
        priority_lower = {p.lower() for p in PRIORITY_CATEGORIES}
        first_job_cats = [j.categories[0] for j in plan.jobs[:5]]
        for cat in first_job_cats:
            assert cat.lower() in priority_lower, f"{cat} should be priority"
        # Last jobs are non-priority
        last_cats = [j.categories[0] for j in plan.jobs[5:]]
        for cat in last_cats:
            assert cat.lower() not in priority_lower
        # All prompts use safe pattern
        for j in plan.jobs:
            assert j.expected_prompt.startswith("Run InventoryModel for ")
            assert "parameter schema" in j.expected_prompt
        # Warnings include blocked commands
        warning_text = " ".join(plan.warnings)
        for cmd in BLOCKED_COMMANDS:
            assert cmd in warning_text

    def test_planner_excludes_zero_count_categories(self):
        """Plan skips categories with zero element count."""
        from axiom_core.inventory.extraction_planner import build_parameter_schema_plan

        category_counts = {"Walls": 100, "Empty Category": 0}
        plan = build_parameter_schema_plan(category_counts, run_id="test")
        assert len(plan.jobs) == 1
        assert plan.jobs[0].categories[0] == "Walls"

    def test_planner_skips_non_executable_categories(self):
        """Plan excludes (No Category) and similar non-executable categories."""
        from axiom_core.inventory.extraction_planner import (
            SKIP_CATEGORIES,
            build_parameter_schema_plan,
        )

        category_counts = {
            "Walls": 100,
            "(No Category)": 50,
            "No Category": 30,
            "<Unnamed>": 10,
            "Doors": 80,
        }
        plan = build_parameter_schema_plan(category_counts, run_id="test")
        job_cats = [j.categories[0] for j in plan.jobs]
        assert "Walls" in job_cats
        assert "Doors" in job_cats
        for skip_cat in SKIP_CATEGORIES:
            assert skip_cat not in job_cats
        # Warning should mention skipped categories
        warning_text = " ".join(plan.warnings)
        assert "non-executable" in warning_text or "Skipped" in warning_text

    def test_structured_dispatch_bypasses_resolver(self):
        """Plan execution uses structured dispatch, not NLP prompt parsing.

        Verifies that categories like 'Grids' that were previously blocked
        by the NLP resolver can now be dispatched structurally.
        """
        from axiom_core.inventory.extraction_planner import build_parameter_schema_plan

        # All Revit categories should produce valid plan jobs
        # including ones that the NLP resolver didn't recognize
        category_counts = {
            "Grids": 50,
            "Walls": 100,
            "Project Information": 1,
            "Materials": 200,
            "Mass": 5,
        }
        plan = build_parameter_schema_plan(category_counts, run_id="test")
        job_cats = [j.categories[0] for j in plan.jobs]
        # All categories should be in the plan
        assert "Grids" in job_cats
        assert "Project Information" in job_cats
        assert "Materials" in job_cats
        assert "Mass" in job_cats
        # All should use category_parameter_schema strategy
        for j in plan.jobs:
            assert j.strategy == "category_parameter_schema"

    def test_planner_md_output_has_blocked_section(self, tmp_path):
        """Plan markdown includes BLOCKED commands section."""
        from axiom_core.inventory.extraction_planner import (
            build_parameter_schema_plan,
            write_parameter_schema_plan_md,
        )

        plan = build_parameter_schema_plan(
            {"Walls": 100, "Doors": 50}, run_id="test",
        )
        md_path = write_parameter_schema_plan_md(plan, tmp_path / "plan.md")
        content = md_path.read_text()
        assert "BLOCKED Commands" in content
        assert "Run InventoryModel parameter schema" in content
        assert "Run InventoryModel sample values" in content
        assert "Run full InventoryModel" in content

    def test_object_schema_import(self, tmp_path):
        """object_schema import creates object registry candidate."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        obj_json = {
            "run_id": "obj_test",
            "source_model": "TestModel.rvt",
            "scan_mode": "object_schema",
            "instance_count": 100,
            "type_count": 20,
            "element_count": 120,
            "elements": [
                {
                    "ElementId": 1,
                    "Category": "Walls",
                    "ClassName": "Wall",
                    "Name": "Basic Wall",
                    "IsType": False,
                },
                {
                    "ElementId": 2,
                    "Category": "Doors",
                    "ClassName": "FamilyInstance",
                    "Name": "Single Flush",
                    "IsType": False,
                },
            ],
        }
        json_path = tmp_path / "obj_schema.json"
        json_path.write_text(json.dumps(obj_json), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import",
            "--file", str(json_path),
            "--output-dir", str(tmp_path / "runs"),
        ])
        assert result.exit_code == 0
        assert "Object schema import complete" in result.output

        # Check run metadata was created
        run_dir = tmp_path / "runs" / "obj_test"
        assert (run_dir / "run_metadata.json").exists()
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        assert meta["scan_mode"] == "object_schema"
        assert meta["element_count"] == 120

    def test_batch_import_filters_by_scan_mode(self, tmp_path):
        """inventory-import-batch only imports matching scan_mode."""
        import json

        from axiom_cli.main import cli
        from click.testing import CliRunner

        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        # Create matching file
        matching = {
            "run_id": "ps_batch_1",
            "source_model": "Test.rvt",
            "scan_mode": "category_parameter_schema",
            "object_category": "Walls",
            "parameter_definitions": [
                {"ParameterName": "Height", "StorageType": "Double"},
            ],
        }
        (exports_dir / "walls_ps.json").write_text(json.dumps(matching))

        # Create non-matching file
        non_matching = {
            "run_id": "summary_1",
            "source_model": "Test.rvt",
            "scan_mode": "summary",
            "element_count": 100,
            "elements": [],
        }
        (exports_dir / "summary.json").write_text(json.dumps(non_matching))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import-batch",
            "--dir", str(exports_dir),
            "--scan-mode", "category_parameter_schema",
            "--output-dir", str(tmp_path / "runs"),
        ])
        assert result.exit_code == 0
        assert "Imported: 1" in result.output
        assert "Skipped: 1" in result.output

    def test_registry_build_dedup_with_expanded_keys(self, tmp_path):
        """Registry build deduplicates by expanded key including DataTypeId."""
        import json

        import pyarrow as pa
        import pyarrow.parquet as pq
        from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

        inventory_dir = tmp_path / "inventory"

        # Create two runs with overlapping params
        for run_name, cat in [("run_walls", "Walls"), ("run_doors", "Doors")]:
            run_dir = inventory_dir / run_name
            run_dir.mkdir(parents=True)

            rows = [{
                "run_id": run_name,
                "source_model": "Test.rvt",
                "scan_mode": "category_parameter_schema",
                "category": cat,
                "class_name": "Wall" if cat == "Walls" else "FamilyInstance",
                "parameter_name": "Height",
                "storage_type": "Double",
                "built_in_parameter_id": "",
                "is_read_only": False,
                "is_instance_param": True,
                "is_type_param": False,
                "observed_count": 50,
                "observed_on_categories": cat,
                "observed_on_classes": "",
                "data_type_id": "autodesk.spec.aec:length-1.0.0",
                "data_type_label": "Length",
                "group_type_id": "",
                "group_type_label": "Dimensions",
                "is_measurable_spec": True,
                "unit_type_id": "",
                "unit_label": "Feet",
                "discipline_label": "Common",
            }]
            arrays = {}
            for fld in PARAMETER_SCHEMA_PARQUET_SCHEMA:
                arrays[fld.name] = [r.get(fld.name) for r in rows]
            table = pa.table(arrays, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
            pq.write_table(table, str(run_dir / "parameter_schema.parquet"))

            meta = {"run_id": run_name, "source_model": "Test.rvt"}
            (run_dir / "run_metadata.json").write_text(json.dumps(meta))

        from axiom_cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, [
            "parameter-registry-build",
            "--from-inventory", str(inventory_dir),
            "--output-dir", str(tmp_path / "registry"),
            "--run-id", "test_registry",
        ])
        assert result.exit_code == 0
        assert "Property registry built" in result.output

        # Check outputs
        reg_dir = tmp_path / "registry" / "test_registry"
        assert (reg_dir / "revit_property_registry.jsonl").exists()
        assert (reg_dir / "revit_property_registry.parquet").exists()
        assert (reg_dir / "summary.md").exists()
        assert (reg_dir / "run_metadata.json").exists()

        # Verify dedup: different categories = different keys = 2 rows
        jsonl_lines = (reg_dir / "revit_property_registry.jsonl").read_text().strip().split("\n")
        assert len(jsonl_lines) == 2

        # Check metadata has coverage info
        meta = json.loads((reg_dir / "run_metadata.json").read_text())
        assert meta["after_dedup_count"] == 2
        assert "Walls" in meta["categories_with_coverage"]
        assert "Doors" in meta["categories_with_coverage"]

    def test_registry_build_merges_observed_count_on_dedup(self, tmp_path):
        """When same key appears in two runs, observed_count sums."""
        import json

        import pyarrow as pa
        import pyarrow.parquet as pq
        from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

        inventory_dir = tmp_path / "inventory"

        for run_name, count in [("run_a", 50), ("run_b", 75)]:
            run_dir = inventory_dir / run_name
            run_dir.mkdir(parents=True)

            rows = [{
                "run_id": run_name,
                "source_model": "Test.rvt",
                "scan_mode": "category_parameter_schema",
                "category": "Walls",
                "class_name": "Wall",
                "parameter_name": "Height",
                "storage_type": "Double",
                "built_in_parameter_id": "",
                "is_read_only": False,
                "is_instance_param": True,
                "is_type_param": False,
                "observed_count": count,
                "observed_on_categories": "Walls",
                "observed_on_classes": "Wall",
                "data_type_id": "autodesk.spec.aec:length-1.0.0",
                "data_type_label": "Length",
                "group_type_id": "",
                "group_type_label": "",
                "is_measurable_spec": True,
                "unit_type_id": "",
                "unit_label": "",
                "discipline_label": "",
            }]
            arrays = {}
            for fld in PARAMETER_SCHEMA_PARQUET_SCHEMA:
                arrays[fld.name] = [r.get(fld.name) for r in rows]
            table = pa.table(arrays, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
            pq.write_table(table, str(run_dir / "parameter_schema.parquet"))
            (run_dir / "run_metadata.json").write_text(
                json.dumps({"run_id": run_name, "source_model": "Test.rvt"}),
            )

        from axiom_cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, [
            "parameter-registry-build",
            "--from-inventory", str(inventory_dir),
            "--output-dir", str(tmp_path / "registry"),
            "--run-id", "merge_test",
        ])
        assert result.exit_code == 0

        # Should dedup to 1 row with merged count
        reg_dir = tmp_path / "registry" / "merge_test"
        jsonl = (reg_dir / "revit_property_registry.jsonl").read_text().strip()
        row = json.loads(jsonl)
        assert row["ObservedCount"] == 125  # 50 + 75

    def test_registry_coverage_summary_reports_missing(self, tmp_path):
        """Coverage summary identifies categories missing parameter schema."""
        import json

        import pyarrow as pa
        import pyarrow.parquet as pq
        from axiom_core.inventory.storage import (
            OBJECT_REGISTRY_PARQUET_SCHEMA,
            PARAMETER_SCHEMA_PARQUET_SCHEMA,
        )

        # Create object registry with 3 categories
        obj_dir = tmp_path / "obj_reg" / "obj_run"
        obj_dir.mkdir(parents=True)
        obj_rows = [
            {"run_id": "obj", "source_model": "T.rvt", "element_id": 1,
             "category": "Walls", "class_name": "Wall", "name": "W",
             "family_name": "", "type_name": "", "level_name": "", "is_type": False},
            {"run_id": "obj", "source_model": "T.rvt", "element_id": 2,
             "category": "Doors", "class_name": "FI", "name": "D",
             "family_name": "", "type_name": "", "level_name": "", "is_type": False},
            {"run_id": "obj", "source_model": "T.rvt", "element_id": 3,
             "category": "Windows", "class_name": "FI", "name": "Win",
             "family_name": "", "type_name": "", "level_name": "", "is_type": False},
        ]
        arrays = {}
        for fld in OBJECT_REGISTRY_PARQUET_SCHEMA:
            arrays[fld.name] = [r.get(fld.name) for r in obj_rows]
        table = pa.table(arrays, schema=OBJECT_REGISTRY_PARQUET_SCHEMA)
        pq.write_table(table, str(obj_dir / "revit_object_registry.parquet"))

        # Create parameter schema for Walls only
        ps_dir = tmp_path / "inventory" / "ps_walls"
        ps_dir.mkdir(parents=True)
        ps_rows = [{
            "run_id": "ps", "source_model": "T.rvt",
            "scan_mode": "category_parameter_schema",
            "category": "Walls", "class_name": "Wall",
            "parameter_name": "Height", "storage_type": "Double",
            "built_in_parameter_id": "", "is_read_only": False,
            "is_instance_param": True, "is_type_param": False,
            "observed_count": 10, "observed_on_categories": "Walls",
            "observed_on_classes": "Wall",
            "data_type_id": "", "data_type_label": "",
            "group_type_id": "", "group_type_label": "",
            "is_measurable_spec": False,
            "unit_type_id": "", "unit_label": "", "discipline_label": "",
        }]
        arrays = {}
        for fld in PARAMETER_SCHEMA_PARQUET_SCHEMA:
            arrays[fld.name] = [r.get(fld.name) for r in ps_rows]
        table = pa.table(arrays, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
        pq.write_table(table, str(ps_dir / "parameter_schema.parquet"))
        (ps_dir / "run_metadata.json").write_text(
            json.dumps({"run_id": "ps", "source_model": "T.rvt"}),
        )

        from axiom_cli.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, [
            "parameter-registry-build",
            "--from-inventory", str(tmp_path / "inventory"),
            "--output-dir", str(tmp_path / "registry"),
            "--run-id", "coverage_test",
            "--object-registry", str(tmp_path / "obj_reg"),
        ])
        assert result.exit_code == 0
        assert "Missing coverage" in result.output

        meta = json.loads(
            (tmp_path / "registry" / "coverage_test" / "run_metadata.json").read_text(),
        )
        assert "Doors" in meta["categories_missing_coverage"]
        assert "Windows" in meta["categories_missing_coverage"]
        assert "Walls" not in meta["categories_missing_coverage"]


class TestParameterSchemaPlanExecution:
    """Tests for Phase 4b: parameter schema plan execution queue."""

    def test_plan_execution_prompt_resolves(self):
        """'Run InventoryModel parameter schema plan' resolves correctly."""
        result = resolve_prompt("Run InventoryModel parameter schema plan")
        assert result.capability_name == "InventoryModel"
        assert result.status == "ok"
        assert result.params.get("ScanMode") == "parameter_schema_plan"
        assert result.params.get("PlanExecution") is True
        assert result.params.get("IsResume") is False
        assert result.params.get("PriorityOnly") is False
        assert result.params.get("MaxCategories") == 0

    def test_plan_execution_max_10(self):
        """'parameter schema plan max 10' parses max category limit."""
        result = resolve_prompt("Run InventoryModel parameter schema plan max 10")
        assert result.status == "ok"
        assert result.params.get("MaxCategories") == 10
        assert result.params.get("PlanExecution") is True

    def test_plan_execution_priority_only(self):
        """'parameter schema plan priority only' parses priority flag."""
        result = resolve_prompt("Run InventoryModel parameter schema plan priority only")
        assert result.status == "ok"
        assert result.params.get("PriorityOnly") is True
        assert result.params.get("PlanExecution") is True

    def test_plan_execution_resume(self):
        """'parameter schema plan resume' parses resume flag."""
        result = resolve_prompt("Run InventoryModel parameter schema plan resume")
        assert result.status == "ok"
        assert result.params.get("IsResume") is True

    def test_plan_execution_max_and_priority(self):
        """Combined max + priority flags parse correctly."""
        result = resolve_prompt(
            "Run InventoryModel parameter schema plan priority only max 5",
        )
        assert result.status == "ok"
        assert result.params.get("PriorityOnly") is True
        assert result.params.get("MaxCategories") == 5

    def test_plan_prompt_not_blocked_as_whole_model(self):
        """'parameter schema plan' must NOT be blocked as whole-model parameter schema."""
        result = resolve_prompt("Run InventoryModel parameter schema plan")
        assert result.status == "ok"
        assert "blocked" not in (result.clarification_message or "").lower()
        assert "disabled" not in (result.clarification_message or "").lower()

    def test_whole_model_parameter_schema_still_blocked(self):
        """'Run InventoryModel parameter schema' (no 'plan') remains blocked."""
        result = resolve_prompt("Run InventoryModel parameter schema")
        assert result.status == "clarification_needed"

    def test_manifest_structure(self, tmp_path):
        """Manifest JSON has required fields for plan execution tracking."""
        manifest = {
            "source_model": "Test Model.rvt",
            "run_id": "plan_20260506_120000",
            "plan_id": "plan_test",
            "started_at": "2026-05-06T12:00:00Z",
            "completed_at": "2026-05-06T12:05:00Z",
            "total_categories": 3,
            "completed_categories": 2,
            "failed_categories": 1,
            "skipped_categories": 0,
            "raw_prompt": "Run InventoryModel parameter schema plan max 3",
            "is_resume": False,
            "priority_only": False,
            "max_categories": 3,
            "duration_ms": 30000,
            "exports": [
                {
                    "category": "Walls",
                    "status": "success",
                    "export_path": "/tmp/inv_walls.json",
                    "error_message": "",
                    "duration_ms": 10000,
                },
                {
                    "category": "Doors",
                    "status": "success",
                    "export_path": "/tmp/inv_doors.json",
                    "error_message": "",
                    "duration_ms": 8000,
                },
                {
                    "category": "Windows",
                    "status": "failed",
                    "export_path": "",
                    "error_message": "Revit API timeout",
                    "duration_ms": 12000,
                },
            ],
        }

        manifest_path = tmp_path / "parameter_schema_manifest_test.json"
        manifest_path.write_text(json.dumps(manifest))
        loaded = json.loads(manifest_path.read_text())

        assert loaded["source_model"] == "Test Model.rvt"
        assert loaded["total_categories"] == 3
        assert loaded["completed_categories"] == 2
        assert loaded["failed_categories"] == 1
        assert len(loaded["exports"]) == 3

        successful = [e for e in loaded["exports"] if e["status"] == "success"]
        failed = [e for e in loaded["exports"] if e["status"] == "failed"]
        assert len(successful) == 2
        assert len(failed) == 1
        assert failed[0]["category"] == "Windows"
        assert failed[0]["error_message"] == "Revit API timeout"

    def test_failed_category_preserves_completed(self, tmp_path):
        """Failed category in manifest does not affect completed export entries."""
        manifest = {
            "total_categories": 3,
            "completed_categories": 2,
            "failed_categories": 1,
            "skipped_categories": 0,
            "exports": [
                {"category": "Walls", "status": "success",
                 "export_path": str(tmp_path / "walls.json"), "error_message": ""},
                {"category": "Doors", "status": "success",
                 "export_path": str(tmp_path / "doors.json"), "error_message": ""},
                {"category": "Ceilings", "status": "failed",
                 "export_path": "", "error_message": "API error"},
            ],
        }

        # Simulate export files existing
        (tmp_path / "walls.json").write_text("{}")
        (tmp_path / "doors.json").write_text("{}")

        successful = [
            e for e in manifest["exports"]
            if e["status"] == "success" and Path(e["export_path"]).exists()
        ]
        assert len(successful) == 2
        assert manifest["failed_categories"] == 1

    def test_blocked_commands_never_in_plan_jobs(self):
        """Plan jobs never contain blocked unsafe commands."""
        from axiom_core.inventory.extraction_planner import (
            BLOCKED_COMMANDS,
            build_parameter_schema_plan,
        )

        category_counts = {
            "Walls": 100, "Doors": 50, "Windows": 30,
        }
        plan = build_parameter_schema_plan(
            category_counts, run_id="safety_test", source_model="Test.rvt",
        )

        blocked_lower = {cmd.lower() for cmd in BLOCKED_COMMANDS}
        for job in plan.jobs:
            prompt_lower = job.expected_prompt.lower()
            for blocked in blocked_lower:
                assert blocked not in prompt_lower, (
                    f"Blocked command '{blocked}' found in job prompt: {job.expected_prompt}"
                )

    def test_manifest_import_batch_cli(self, tmp_path):
        """inventory-import-batch --manifest reads manifest and imports successful exports."""
        from axiom_cli.main import cli
        from click.testing import CliRunner

        # Create mock export files
        walls_export = {
            "run_id": "inv_walls",
            "source_model": "Test.rvt",
            "scan_mode": "category_parameter_schema",
            "object_category": "Walls",
            "instance_count": 100,
            "type_count": 10,
            "element_count": 110,
            "parameter_count": 0,
            "error_count": 0,
            "parameter_definition_count": 50,
            "parameter_definitions": [
                {
                    "Category": "Walls",
                    "ClassName": "Wall",
                    "ParameterName": "Width",
                    "StorageType": "Double",
                    "BuiltInParameterId": "WALL_ATTR_WIDTH_PARAM",
                    "DataTypeId": "autodesk.spec.aec:length-2.0.0",
                    "IsReadOnly": False,
                    "IsInstanceParam": True,
                    "IsTypeParam": False,
                    "ObservedCount": 100,
                },
            ],
        }
        walls_path = tmp_path / "inv_walls.json"
        walls_path.write_text(json.dumps(walls_export))

        # Create manifest
        manifest = {
            "source_model": "Test.rvt",
            "run_id": "plan_test",
            "plan_id": "plan_001",
            "total_categories": 2,
            "completed_categories": 1,
            "failed_categories": 1,
            "skipped_categories": 0,
            "exports": [
                {
                    "category": "Walls",
                    "status": "success",
                    "export_path": str(walls_path),
                    "error_message": "",
                    "duration_ms": 5000,
                },
                {
                    "category": "Doors",
                    "status": "failed",
                    "export_path": "",
                    "error_message": "API error",
                    "duration_ms": 2000,
                },
            ],
        }
        manifest_path = tmp_path / "parameter_schema_manifest_test.json"
        manifest_path.write_text(json.dumps(manifest))

        out_dir = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import-batch",
            "--manifest", str(manifest_path),
            "--output-dir", str(out_dir),
        ])
        assert result.exit_code == 0
        assert "Imported: 1" in result.output
        assert "Manifest" in result.output


class TestPlanHandoff:
    """Tests for plan handoff path mismatch fix (BHV-019)."""

    def test_plan_writes_handoff_copy(self, tmp_path):
        """inventory-plan should write LocalAppData handoff copy when mode=parameter-schema."""
        import os

        from axiom_cli.main import cli
        from click.testing import CliRunner

        # Create a summary JSON with category counts
        summary = {
            "category_counts": {"Walls": 100, "Doors": 50},
            "document_title": "Test.rvt",
            "instance_count": 150,
            "type_count": 20,
        }
        summary_path = tmp_path / "summary.json"
        summary_path.write_text(json.dumps(summary))

        plan_output = tmp_path / "plans"

        # Set LOCALAPPDATA to a temp dir to test handoff
        handoff_dir = tmp_path / "localappdata"
        env_patch = {**os.environ, "LOCALAPPDATA": str(handoff_dir)}

        runner = CliRunner(env=env_patch)
        result = runner.invoke(cli, [
            "inventory-plan",
            "--file", str(summary_path),
            "--output-dir", str(plan_output),
            "--mode", "parameter-schema",
        ])
        assert result.exit_code == 0

        # Verify handoff copies exist
        latest_plan = handoff_dir / "Axiom" / "inventory_plans" / "latest" / "parameter_schema_plan.json"
        flat_plan = handoff_dir / "Axiom" / "inventory_plans" / "parameter_schema_plan.json"
        assert latest_plan.exists(), f"Latest handoff plan not found at {latest_plan}"
        assert flat_plan.exists(), f"Flat handoff plan not found at {flat_plan}"

        # Verify handoff plan content matches repo plan
        latest_data = json.loads(latest_plan.read_text())
        assert "jobs" in latest_data
        assert len(latest_data["jobs"]) == 2

        # Verify console output mentions both paths
        assert "Revit handoff plan" in result.output

    def test_plan_status_reports_locations(self, tmp_path):
        """inventory-plan-status should report plan locations and existence."""
        import os

        from axiom_cli.main import cli
        from click.testing import CliRunner

        handoff_dir = tmp_path / "localappdata"
        env_patch = {**os.environ, "LOCALAPPDATA": str(handoff_dir)}

        runner = CliRunner(env=env_patch)
        result = runner.invoke(cli, ["inventory-plan-status"], env=env_patch)
        assert result.exit_code == 0
        assert "MISSING" in result.output
        assert "Plan locations" in result.output

    def test_plan_status_reads_existing_plan(self, tmp_path):
        """inventory-plan-status should read and report an existing plan."""
        import os

        from axiom_cli.main import cli
        from click.testing import CliRunner

        handoff_dir = tmp_path / "localappdata"
        latest_dir = handoff_dir / "Axiom" / "inventory_plans" / "latest"
        latest_dir.mkdir(parents=True)
        plan = {
            "run_id": "plan_test_123",
            "source_model": "TestModel.rvt",
            "jobs": [
                {"categories": ["Walls"], "expected_prompt": "Run InventoryModel for Walls parameter schema"},
                {"categories": ["Doors"], "expected_prompt": "Run InventoryModel for Doors parameter schema"},
            ],
        }
        (latest_dir / "parameter_schema_plan.json").write_text(json.dumps(plan))

        env_patch = {**os.environ, "LOCALAPPDATA": str(handoff_dir)}
        runner = CliRunner(env=env_patch)
        result = runner.invoke(cli, ["inventory-plan-status"], env=env_patch)
        assert result.exit_code == 0
        assert "plan_test_123" in result.output
        assert "Total categories" in result.output or "2" in result.output
        assert "EXISTS" in result.output


class TestManifestImportHardened:
    """Tests for hardened manifest import behavior (BHV-019)."""

    def test_manifest_import_reports_failed_entries(self, tmp_path):
        """Import-batch should report failed entries clearly without failing."""
        from axiom_cli.main import cli
        from click.testing import CliRunner

        # Create a successful export
        walls_export = {
            "scan_mode": "category_parameter_schema",
            "run_id": "walls_001",
            "source_model": "Test.rvt",
            "object_category": "Walls",
            "parameter_definitions": [
                {"parameter_name": "Length", "storage_type": "Double",
                 "built_in_parameter_id": "CURVE_ELEM_LENGTH", "is_read_only": True,
                 "is_instance_param": True, "is_type_param": False},
            ],
        }
        walls_path = tmp_path / "inv_walls.json"
        walls_path.write_text(json.dumps(walls_export))

        manifest = {
            "source_model": "Test.rvt",
            "plan_id": "plan_test",
            "total_categories": 3,
            "completed_categories": 1,
            "failed_categories": 1,
            "skipped_categories": 1,
            "exports": [
                {"category": "Walls", "prompt": "Run InventoryModel for Walls parameter schema",
                 "status": "success", "export_path": str(walls_path)},
                {"category": "Doors", "prompt": "Run InventoryModel for Doors parameter schema",
                 "status": "failed", "error_message": "Revit API error"},
                {"category": "Windows", "prompt": "Run InventoryModel for Windows parameter schema",
                 "status": "skipped_resume", "error_message": "Already completed"},
            ],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import-batch",
            "--manifest", str(manifest_path),
            "--output-dir", str(tmp_path / "output"),
        ])
        assert result.exit_code == 0
        assert "Imported: 1" in result.output
        assert "Failed categories" in result.output
        assert "Doors" in result.output
        assert "Revit API error" in result.output

    def test_manifest_import_handles_missing_files(self, tmp_path):
        """Import-batch should warn about missing export files."""
        from axiom_cli.main import cli
        from click.testing import CliRunner

        manifest = {
            "source_model": "Test.rvt",
            "plan_id": "plan_test",
            "total_categories": 1,
            "completed_categories": 1,
            "failed_categories": 0,
            "skipped_categories": 0,
            "exports": [
                {"category": "Walls", "status": "success",
                 "export_path": str(tmp_path / "nonexistent.json")},
            ],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import-batch",
            "--manifest", str(manifest_path),
            "--output-dir", str(tmp_path / "output"),
        ])
        assert result.exit_code == 0
        assert "Missing export file" in result.output or "missing" in result.output.lower()

    def test_manifest_all_failed_gives_guidance(self, tmp_path):
        """Import-batch should give resume guidance when all entries failed."""
        from axiom_cli.main import cli
        from click.testing import CliRunner

        manifest = {
            "source_model": "Test.rvt",
            "plan_id": "plan_test",
            "total_categories": 2,
            "completed_categories": 0,
            "failed_categories": 2,
            "skipped_categories": 0,
            "exports": [
                {"category": "Walls", "status": "failed", "error_message": "crash"},
                {"category": "Doors", "status": "failed", "error_message": "timeout"},
            ],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inventory-import-batch",
            "--manifest", str(manifest_path),
            "--output-dir", str(tmp_path / "output"),
        ])
        assert result.exit_code == 0
        assert "No successful exports" in result.output
        assert "resume" in result.output.lower() or "retry" in result.output.lower()


class TestRegistryCoveragePriority:
    """Tests for priority coverage in registry build (BHV-019)."""

    def test_registry_summary_includes_priority_coverage(self, tmp_path):
        """Registry build summary should include priority category coverage."""

        # Create a mock parameter_schema.parquet and run_metadata
        import pyarrow as pa
        from axiom_core.inventory.storage import PARAMETER_SCHEMA_PARQUET_SCHEMA

        run_dir = tmp_path / "inventory" / "walls_run"
        run_dir.mkdir(parents=True)

        rows = {
            "run_id": ["walls_run"],
            "source_model": ["Test.rvt"],
            "scan_mode": ["category_parameter_schema"],
            "category": ["Walls"],
            "class_name": ["Wall"],
            "parameter_name": ["Length"],
            "storage_type": ["Double"],
            "built_in_parameter_id": ["CURVE_ELEM_LENGTH"],
            "is_read_only": [True],
            "is_instance_param": [True],
            "is_type_param": [False],
            "observed_count": [100],
            "observed_on_categories": ["Walls"],
            "observed_on_classes": ["Wall"],
            "data_type_id": [""],
            "data_type_label": ["Length"],
            "group_type_id": [""],
            "group_type_label": ["Constraints"],
            "is_measurable_spec": [True],
            "unit_type_id": [""],
            "unit_label": ["ft"],
            "discipline_label": ["Common"],
        }
        table = pa.table(rows, schema=PARAMETER_SCHEMA_PARQUET_SCHEMA)
        import pyarrow.parquet as pq
        pq.write_table(table, str(run_dir / "parameter_schema.parquet"))

        meta = {"run_id": "walls_run", "source_model": "Test.rvt",
                "scan_mode": "category_parameter_schema"}
        (run_dir / "run_metadata.json").write_text(json.dumps(meta))

        from axiom_cli.main import cli
        from click.testing import CliRunner

        out_dir = tmp_path / "registry_out"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "parameter-registry-build",
            "--from-inventory", str(tmp_path / "inventory"),
            "--output-dir", str(out_dir),
        ])
        assert result.exit_code == 0
        assert "Priority coverage" in result.output

        # Check summary.md mentions priority coverage
        summary_files = list(out_dir.rglob("summary.md"))
        assert len(summary_files) > 0
        summary_text = summary_files[0].read_text()
        assert "Priority categories covered" in summary_text
        assert "Walls" in summary_text
