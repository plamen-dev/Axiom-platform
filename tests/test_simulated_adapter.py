"""Tests for the Simulated Product Adapter (Adapter 000)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.automation_bridge import execute_capability_via_bridge
from axiom_core.schemas import StepStatus
from axiom_core.simulated_adapter import (
    ADAPTER_ID,
    MAX_SET_PARAMETER_ELEMENTS,
    SUPPORTED_CAPABILITIES,
    SimulatedModel,
    SimulatedPipeClient,
)
from click.testing import CliRunner


@pytest.fixture
def client() -> SimulatedPipeClient:
    return SimulatedPipeClient()


class TestAdapterContract:
    def test_supported_capabilities(self) -> None:
        assert SUPPORTED_CAPABILITIES == (
            "CreateGrids",
            "CreateLevels",
            "InventoryModel",
            "SetParameterValue",
        )

    def test_always_available(self, client: SimulatedPipeClient) -> None:
        assert client.is_available() is True

    def test_unsupported_capability_fails(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool("DeleteEverything")
        assert result.status == StepStatus.FAILED
        assert "does not support" in result.errors[0]

    def test_results_stamped_simulated(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool("InventoryModel")
        assert result.output_data["adapter"] == ADAPTER_ID
        assert result.output_data["simulated_model"] is True


class TestCreateGrids:
    def test_creates_grids(self, client: SimulatedPipeClient) -> None:
        result = client.execute_tool(
            "CreateGrids",
            {"HorizontalCount": 3, "VerticalCount": 2, "SpacingFeet": 10.0},
        )
        assert result.status == StepStatus.SUCCESS
        assert len(result.created_ids) == 5
        assert result.output_data["numeric_names"] == ["1", "2", "3"]
        assert result.output_data["alphabetic_names"] == ["A", "B"]
        assert len(client.model.by_category("Grids")) == 5

    def test_invalid_spacing_fails(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "CreateGrids",
            {"HorizontalCount": 1, "VerticalCount": 1, "SpacingFeet": 0},
        )
        assert result.status == StepStatus.FAILED
        assert result.created_ids == []


class TestCreateLevels:
    def test_uniform_elevations(self, client: SimulatedPipeClient) -> None:
        result = client.execute_tool(
            "CreateLevels",
            {
                "LevelCount": 3,
                "FloorToFloorFeet": 12.0,
                "StartElevationFeet": 0,
            },
        )
        assert result.status == StepStatus.SUCCESS
        elevations = [
            lvl["elevation_feet"] for lvl in result.output_data["levels"]
        ]
        assert elevations == [0.0, 12.0, 24.0]

    def test_variable_elevations_and_names(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "CreateLevels",
            {
                "LevelCount": 2,
                "VariableElevationsFeet": [-10.0, 5.0],
                "LevelNames": ["Basement", "Ground"],
            },
        )
        assert result.status == StepStatus.SUCCESS
        assert result.output_data["levels"] == [
            {"name": "Basement", "elevation_feet": -10.0},
            {"name": "Ground", "elevation_feet": 5.0},
        ]

    def test_length_mismatch_fails(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "CreateLevels",
            {"LevelCount": 3, "VariableElevationsFeet": [1.0, 2.0]},
        )
        assert result.status == StepStatus.FAILED
        assert any("length must match" in e for e in result.errors)

    def test_missing_count_fails(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "CreateLevels", {"FloorToFloorFeet": 10.0}
        )
        assert result.status == StepStatus.FAILED


class TestInventoryModel:
    def test_summary_mode_only_no_parameter_dump(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool("InventoryModel")
        assert result.status == StepStatus.SUCCESS
        out = result.output_data
        assert out["mode"] == "summary"
        assert out["element_count"] == 5
        assert out["categories"] == {"Doors": 2, "Walls": 3}
        assert "parameters" not in json.dumps(out)

    def test_category_filter(self, client: SimulatedPipeClient) -> None:
        result = client.execute_tool(
            "InventoryModel", {"CategoryFilter": ["Walls"]}
        )
        assert result.output_data["categories"] == {"Walls": 3}

    def test_reflects_created_elements(
        self, client: SimulatedPipeClient
    ) -> None:
        client.execute_tool(
            "CreateLevels", {"LevelCount": 2, "FloorToFloorFeet": 10.0}
        )
        result = client.execute_tool("InventoryModel")
        assert result.output_data["categories"]["Levels"] == 2


class TestSetParameterValue:
    def test_preview_does_not_mutate(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "SetParameterValue",
            {
                "Category": "Walls",
                "ParameterName": "Comments",
                "Value": "checked",
                "ElementCount": 2,
            },
        )
        assert result.status == StepStatus.SUCCESS
        assert result.output_data["applied"] is False
        assert result.modified_ids == []
        walls = client.model.by_category("Walls")
        assert all(w.parameters["Comments"]["value"] == "" for w in walls)

    def test_apply_mutates_capped_targets(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "SetParameterValue",
            {
                "Category": "Walls",
                "ParameterName": "Comments",
                "Value": "checked",
                "ElementCount": 2,
                "Mode": "apply",
            },
        )
        assert result.status == StepStatus.SUCCESS
        assert len(result.modified_ids) == 2
        modified = {
            e.element_id: e.parameters["Comments"]["value"]
            for e in client.model.by_category("Walls")
        }
        assert list(modified.values()).count("checked") == 2

    def test_hard_cap_enforced(self, client: SimulatedPipeClient) -> None:
        result = client.execute_tool(
            "SetParameterValue",
            {
                "Category": "Walls",
                "ParameterName": "Comments",
                "Value": "x",
                "ElementCount": MAX_SET_PARAMETER_ELEMENTS + 1,
                "Mode": "apply",
            },
        )
        assert result.status == StepStatus.FAILED
        assert any("hard cap" in e for e in result.errors)

    def test_category_required(self, client: SimulatedPipeClient) -> None:
        result = client.execute_tool(
            "SetParameterValue",
            {"ParameterName": "Comments", "Value": "x", "ElementCount": 1},
        )
        assert result.status == StepStatus.FAILED
        assert any("Category is required" in e for e in result.errors)

    def test_read_only_parameter_rejected(
        self, client: SimulatedPipeClient
    ) -> None:
        result = client.execute_tool(
            "SetParameterValue",
            {
                "Category": "Walls",
                "ParameterName": "Type Name",
                "Value": "x",
                "ElementCount": 1,
                "Mode": "apply",
            },
        )
        assert result.status == StepStatus.FAILED
        assert result.modified_ids == []


class TestBridgeIntegration:
    def test_bridge_run_produces_evidence_bundle(
        self, tmp_path: Any
    ) -> None:
        result = execute_capability_via_bridge(
            capability="InventoryModel",
            output_dir=str(tmp_path / "validation_runs"),
            pipe_client=SimulatedPipeClient(),
        )
        assert result.classification == "pass"
        assert result.checkpoints.evidence_produced is True
        bridge_dir = (
            tmp_path / "validation_runs" / result.run_id / "bridge"
        )
        response = json.loads(
            (bridge_dir / "bridge_response.json").read_text(encoding="utf-8")
        )
        assert response["output_data"]["adapter"] == ADAPTER_ID
        pass_fail = json.loads(
            (bridge_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is True

    def test_fresh_model_is_deterministic(self) -> None:
        first = SimulatedModel().category_counts()
        second = SimulatedModel().category_counts()
        assert first == second == {"Doors": 2, "Walls": 3}


class TestCli:
    def test_cli_inventory_json(self, tmp_path: Any) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "simulated-adapter-run",
                "--capability",
                "InventoryModel",
                "--output-dir",
                str(tmp_path / "validation_runs"),
                "--json-output",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["adapter"] == "simulated-000"
        assert payload["classification"] == "pass"

    def test_cli_unsupported_capability(self, tmp_path: Any) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "simulated-adapter-run",
                "--capability",
                "Nope",
                "--output-dir",
                str(tmp_path / "validation_runs"),
            ],
        )
        assert result.exit_code == 1
        assert "does not support" in result.output

    def test_cli_failed_capability_exits_nonzero(
        self, tmp_path: Any
    ) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "simulated-adapter-run",
                "--capability",
                "CreateLevels",
                "--args-json",
                '{"LevelCount": 0}',
                "--output-dir",
                str(tmp_path / "validation_runs"),
            ],
        )
        assert result.exit_code == 1
