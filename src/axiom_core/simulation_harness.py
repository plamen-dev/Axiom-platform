"""Simulation Harness v1 — run the capability suite against Adapter 000.

Runs all four capabilities (CreateLevels, CreateGrids, InventoryModel,
SetParameterValue preview + apply) against **one shared**
:class:`~axiom_core.simulated_adapter.SimulatedModel` through the existing
automation-bridge driver, so each step produces a real bridge evidence
bundle and later steps can verify the effects of earlier ones (the
inventory step must see the created grids/levels; the apply step must
mutate what the preview step previewed).

The harness owns no new evidence semantics: per-step evidence is the
normal bridge bundle (stamped ``adapter: simulated-000``); the harness
report at ``artifacts/simulation_harness/<harness_id>/report.json`` just
links the step run_ids and records a per-step and overall PASS/FAIL.

Fidelity doctrine: harness results prove capability *contract* behavior
against the simulated model only — they never count as live-Revit proof.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox
from axiom_core.automation_bridge import (
    BridgeRunResult,
    execute_capability_via_bridge,
)
from axiom_core.simulated_adapter import ADAPTER_ID, SimulatedPipeClient

SCHEMA_VERSION = "1.0"

_LEVEL_ARGS = {"LevelCount": 3, "FloorToFloorFeet": 12.0}
_GRID_ARGS = {"HorizontalCount": 3, "VerticalCount": 3, "SpacingFeet": 20.0}
_SET_PARAM_ARGS = {
    "Category": "Walls",
    "ParameterName": "Comments",
    "Value": "simulation-harness",
    "ElementCount": 2,
}


class SimulationHarness:
    """Run the four-capability suite against one shared simulated model."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self.artifacts_root = str(artifacts_root)
        self._harness_dir = Path(self.artifacts_root) / "simulation_harness"
        self._bridge_dir = os.path.join(
            self.artifacts_root, "validation_runs"
        )

    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        harness_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        client = SimulatedPipeClient()
        model = client.model
        steps: list[dict[str, Any]] = []

        # 1. CreateLevels
        result = execute_capability_via_bridge(
            capability="CreateLevels",
            args=dict(_LEVEL_ARGS),
            run_id=f"{harness_id}-s1-createlevels",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )
        tr = result.tool_result
        steps.append(
            self._assemble_step(
                1,
                "CreateLevels",
                result,
                [
                    (
                        "creates 3 levels",
                        tr is not None and len(tr.created_ids) == 3,
                    ),
                    (
                        "levels exist in model",
                        len(model.by_category("Levels")) == 3,
                    ),
                ],
            )
        )

        # 2. CreateGrids
        result = execute_capability_via_bridge(
            capability="CreateGrids",
            args=dict(_GRID_ARGS),
            run_id=f"{harness_id}-s2-creategrids",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )
        tr = result.tool_result
        steps.append(
            self._assemble_step(
                2,
                "CreateGrids",
                result,
                [
                    (
                        "creates 6 grids",
                        tr is not None and len(tr.created_ids) == 6,
                    ),
                    (
                        "grids exist in model",
                        len(model.by_category("Grids")) == 6,
                    ),
                ],
            )
        )

        # 3. InventoryModel — must reflect the elements created above
        result = execute_capability_via_bridge(
            capability="InventoryModel",
            args={},
            run_id=f"{harness_id}-s3-inventorymodel",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )
        tr = result.tool_result
        categories = (
            tr.output_data.get("categories", {}) if tr is not None else {}
        )
        steps.append(
            self._assemble_step(
                3,
                "InventoryModel",
                result,
                [
                    ("summary mode", tr is not None
                     and tr.output_data.get("mode") == "summary"),
                    ("sees created levels", categories.get("Levels") == 3),
                    ("sees created grids", categories.get("Grids") == 6),
                    ("sees seed walls", categories.get("Walls") == 3),
                ],
            )
        )

        # 4. SetParameterValue preview — must not mutate
        result = execute_capability_via_bridge(
            capability="SetParameterValue",
            args=dict(_SET_PARAM_ARGS),
            run_id=f"{harness_id}-s4-setparameter-preview",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )
        tr = result.tool_result
        walls = model.by_category("Walls")
        steps.append(
            self._assemble_step(
                4,
                "SetParameterValue (preview)",
                result,
                [
                    (
                        "preview reports targets",
                        tr is not None
                        and len(tr.output_data.get("previews", [])) == 2,
                    ),
                    (
                        "preview does not mutate",
                        tr is not None
                        and not tr.modified_ids
                        and all(
                            w.parameters["Comments"]["value"] == ""
                            for w in walls
                        ),
                    ),
                ],
            )
        )

        # 5. SetParameterValue apply — must mutate exactly the previewed set
        result = execute_capability_via_bridge(
            capability="SetParameterValue",
            args={**_SET_PARAM_ARGS, "Mode": "apply"},
            run_id=f"{harness_id}-s5-setparameter-apply",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )
        tr = result.tool_result
        mutated = [
            w
            for w in model.by_category("Walls")
            if w.parameters["Comments"]["value"] == "simulation-harness"
        ]
        steps.append(
            self._assemble_step(
                5,
                "SetParameterValue (apply)",
                result,
                [
                    (
                        "apply modifies 2 elements",
                        tr is not None and len(tr.modified_ids) == 2,
                    ),
                    ("model reflects mutation", len(mutated) == 2),
                ],
            )
        )

        status = "passed" if all(s["passed"] for s in steps) else "failed"
        report = {
            "schema_version": SCHEMA_VERSION,
            "harness_id": harness_id,
            "adapter": ADAPTER_ID,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "step_count": len(steps),
            "steps": steps,
            "fidelity_note": (
                "Simulated-adapter evidence proves capability contract "
                "behavior only; it never counts as live-Revit proof."
            ),
        }
        self._persist(report)
        return report

    def _assemble_step(
        self,
        index: int,
        capability: str,
        result: BridgeRunResult,
        checks: list[tuple[str, bool]],
    ) -> dict[str, Any]:
        assertions = [
            {"assertion": name, "passed": ok} for name, ok in checks
        ]
        return {
            "step": index,
            "capability": capability,
            "run_id": result.run_id,
            "classification": result.classification,
            "assertions": assertions,
            "passed": result.classification == "pass"
            and all(a["passed"] for a in assertions),
            "evidence_dir": result.artifact_dir,
        }

    def _persist(self, report: dict[str, Any]) -> None:
        sandbox = self._harness_dir.resolve()
        run_dir = (sandbox / report["harness_id"]).resolve()
        if not is_within_sandbox(run_dir, sandbox):
            raise ValueError("harness run dir escapes the artifacts sandbox")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        (run_dir / "pass_fail.json").write_text(
            json.dumps(
                {
                    "harness_id": report["harness_id"],
                    "passed": report["status"] == "passed",
                    "step_count": report["step_count"],
                    "steps_passed": sum(
                        1 for s in report["steps"] if s["passed"]
                    ),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
