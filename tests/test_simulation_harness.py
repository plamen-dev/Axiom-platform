"""Tests for the Simulation Harness (capability suite vs Adapter 000)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.simulation_harness import SimulationHarness
from click.testing import CliRunner


@pytest.fixture
def report(tmp_path: Any) -> dict:
    return SimulationHarness(
        artifacts_root=str(tmp_path / "artifacts")
    ).run()


class TestHarnessRun:
    def test_all_steps_pass(self, report: dict) -> None:
        assert report["status"] == "passed"
        assert report["step_count"] == 5
        assert [s["capability"] for s in report["steps"]] == [
            "CreateLevels",
            "CreateGrids",
            "InventoryModel",
            "SetParameterValue (preview)",
            "SetParameterValue (apply)",
        ]
        assert all(s["passed"] for s in report["steps"])

    def test_steps_share_one_model(self, report: dict) -> None:
        inventory = report["steps"][2]
        checks = {
            a["assertion"]: a["passed"] for a in inventory["assertions"]
        }
        assert checks["sees created levels"] is True
        assert checks["sees created grids"] is True

    def test_preview_then_apply_semantics(self, report: dict) -> None:
        preview = report["steps"][3]
        apply_step = report["steps"][4]
        assert {
            a["assertion"]: a["passed"] for a in preview["assertions"]
        }["preview does not mutate"] is True
        assert {
            a["assertion"]: a["passed"] for a in apply_step["assertions"]
        }["model reflects mutation"] is True

    def test_step_run_ids_link_to_bridge_evidence(
        self, report: dict, tmp_path: Any
    ) -> None:
        for step in report["steps"]:
            assert step["run_id"].startswith(report["harness_id"])
            bridge = (
                tmp_path
                / "artifacts"
                / "validation_runs"
                / step["run_id"]
                / "bridge"
            )
            assert (bridge / "pass_fail.json").exists()
            response = json.loads(
                (bridge / "bridge_response.json").read_text(
                    encoding="utf-8"
                )
            )
            assert response["output_data"]["adapter"] == "simulated-000"

    def test_report_persisted_with_fidelity_note(
        self, report: dict, tmp_path: Any
    ) -> None:
        run_dir = (
            tmp_path
            / "artifacts"
            / "simulation_harness"
            / report["harness_id"]
        )
        on_disk = json.loads(
            (run_dir / "report.json").read_text(encoding="utf-8")
        )
        assert "never counts as live-Revit proof" in on_disk[
            "fidelity_note"
        ]
        pass_fail = json.loads(
            (run_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is True
        assert pass_fail["steps_passed"] == 5


class TestCli:
    def test_cli_json_output(self, tmp_path: Any) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "simulation-harness-run",
                "--artifacts-root",
                str(tmp_path / "artifacts"),
                "--json-output",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "passed"
        assert payload["adapter"] == "simulated-000"
