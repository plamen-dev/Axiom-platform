"""Tests for the simulated mutation loop (Lane-3B rehearsal vs Adapter 000)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.simulated_mutation_loop import SimulatedMutationLoop
from click.testing import CliRunner

GATES = [
    "baseline",
    "preview",
    "apply",
    "verify",
    "revert",
    "final_verify",
]


@pytest.fixture
def report(tmp_path: Any) -> dict:
    return SimulatedMutationLoop(
        artifacts_root=str(tmp_path / "artifacts")
    ).run()


class TestMutationLoop:
    def test_all_gates_pass(self, report: dict) -> None:
        assert report["status"] == "passed"
        assert [g["gate"] for g in report["gates"]] == GATES
        assert all(g["passed"] for g in report["gates"])

    def test_apply_matches_preview(self, report: dict) -> None:
        apply_gate = report["gates"][2]
        assert {
            a["assertion"]: a["passed"] for a in apply_gate["assertions"]
        }["modified ids match previewed ids"] is True

    def test_final_state_restored(self, report: dict) -> None:
        final = report["gates"][5]
        checks = {
            a["assertion"]: a["passed"] for a in final["assertions"]
        }
        assert checks["values restored"] is True
        assert checks["category counts unchanged"] is True

    def test_mutation_gates_link_bridge_evidence(
        self, report: dict, tmp_path: Any
    ) -> None:
        for entry in report["gates"]:
            if entry["run_id"] is None:
                continue
            assert entry["run_id"].startswith(report["loop_id"])
            bridge = (
                tmp_path
                / "artifacts"
                / "validation_runs"
                / entry["run_id"]
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
            / "simulated_mutation_loop"
            / report["loop_id"]
        )
        on_disk = json.loads(
            (run_dir / "report.json").read_text(encoding="utf-8")
        )
        assert "never implies live-Revit" in on_disk["fidelity_note"]
        pass_fail = json.loads(
            (run_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is True
        assert pass_fail["gates_passed"] == 6

    def test_element_count_respects_hard_cap(self, tmp_path: Any) -> None:
        report = SimulatedMutationLoop(
            artifacts_root=str(tmp_path / "artifacts"),
            mutation_args={"ElementCount": 1},
        ).run()
        assert report["status"] == "passed"
        assert report["mutation"]["element_count"] == 1


class TestCli:
    def test_cli_json_output(self, tmp_path: Any) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "simulated-mutation-loop",
                "--artifacts-root",
                str(tmp_path / "artifacts"),
                "--json-output",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "passed"
        assert payload["adapter"] == "simulated-000"
