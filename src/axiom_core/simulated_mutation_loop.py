"""Simulated Mutation Loop v1 — preview→apply→verify→revert vs Adapter 000.

Lane-3B rehearsal with zero Revit: runs the controlled single-mutation
discipline (baseline → preview → apply → independent verify → revert →
final verify) against the in-memory Adapter 000 model, every mutation
going through the ``SetParameterValue`` capability via the automation
bridge — never by poking the model directly.

Gates (mirroring the Lane-3B runbook):

1. **baseline** — read the target parameter values and inventory counts.
2. **preview** — must report the targets and must not mutate.
3. **apply** — must modify exactly the previewed element ids.
4. **verify** — independent re-read: targets carry the new value.
5. **revert** — apply the recorded baseline value back through the same
   capability path.
6. **final_verify** — model matches the baseline (values + counts).

Fidelity doctrine: a passed loop proves the preview/apply/revert contract
against the simulated model only — it never implies live-Revit (Lane-3B)
mutation readiness.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox
from axiom_core.automation_bridge import execute_capability_via_bridge
from axiom_core.simulated_adapter import ADAPTER_ID, SimulatedPipeClient

SCHEMA_VERSION = "1.0"

_DEFAULT_ARGS = {
    "Category": "Walls",
    "ParameterName": "Comments",
    "Value": "mutation-loop",
    "ElementCount": 2,
}

FIDELITY_NOTE = (
    "Simulated mutation loop (adapter: simulated-000) proves the "
    "preview/apply/revert contract only; it never implies live-Revit "
    "(Lane-3B) mutation readiness."
)


class SimulatedMutationLoop:
    """Run one bounded preview→apply→verify→revert cycle vs Adapter 000."""

    def __init__(
        self,
        artifacts_root: str | None = None,
        mutation_args: dict[str, Any] | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self.artifacts_root = str(artifacts_root)
        self._loop_dir = (
            Path(self.artifacts_root) / "simulated_mutation_loop"
        )
        self._bridge_dir = os.path.join(
            self.artifacts_root, "validation_runs"
        )
        self.mutation_args = {**_DEFAULT_ARGS, **(mutation_args or {})}

    # ------------------------------------------------------------------

    def _bridge(
        self,
        client: SimulatedPipeClient,
        loop_id: str,
        stage: str,
        capability: str,
        args: dict[str, Any],
    ):
        return execute_capability_via_bridge(
            capability=capability,
            args=args,
            run_id=f"{loop_id}-{stage}",
            output_dir=self._bridge_dir,
            pipe_client=client,
        )

    @staticmethod
    def _snapshot(
        client: SimulatedPipeClient, category: str, parameter: str
    ) -> dict[str, Any]:
        return {
            element.element_id: element.parameters.get(parameter, {}).get(
                "value"
            )
            for element in client.model.by_category(category)
        }

    def run(self) -> dict[str, Any]:
        loop_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        client = SimulatedPipeClient()
        args = dict(self.mutation_args)
        category = str(args["Category"])
        parameter = str(args["ParameterName"])
        new_value = str(args["Value"])
        count = int(args["ElementCount"])
        gates: list[dict[str, Any]] = []

        def gate(
            name: str,
            run_id: str | None,
            checks: list[tuple[str, bool]],
        ) -> bool:
            assertions = [
                {"assertion": label, "passed": ok} for label, ok in checks
            ]
            passed = all(a["passed"] for a in assertions)
            gates.append(
                {
                    "gate": name,
                    "run_id": run_id,
                    "assertions": assertions,
                    "passed": passed,
                }
            )
            return passed

        # 1. baseline
        baseline_values = self._snapshot(client, category, parameter)
        baseline_counts = client.model.category_counts()
        inventory = self._bridge(
            client, loop_id, "g1-baseline", "InventoryModel", {}
        )
        gate(
            "baseline",
            inventory.run_id,
            [
                ("baseline inventory pass",
                 inventory.classification == "pass"),
                (
                    "category has enough elements",
                    len(baseline_values) >= count,
                ),
            ],
        )

        # 2. preview — no mutation
        preview = self._bridge(
            client, loop_id, "g2-preview", "SetParameterValue", args
        )
        preview_tr = preview.tool_result
        previewed_ids = (
            [
                p["element_id"]
                for p in preview_tr.output_data.get("previews", [])
            ]
            if preview_tr is not None
            else []
        )
        gate(
            "preview",
            preview.run_id,
            [
                ("preview pass", preview.classification == "pass"),
                ("preview reports targets", len(previewed_ids) == count),
                (
                    "preview does not mutate",
                    self._snapshot(client, category, parameter)
                    == baseline_values,
                ),
            ],
        )

        # 3. apply — exactly the previewed ids
        apply_result = self._bridge(
            client,
            loop_id,
            "g3-apply",
            "SetParameterValue",
            {**args, "Mode": "apply"},
        )
        apply_tr = apply_result.tool_result
        modified_ids = (
            list(apply_tr.modified_ids) if apply_tr is not None else []
        )
        gate(
            "apply",
            apply_result.run_id,
            [
                ("apply pass", apply_result.classification == "pass"),
                (
                    "modified ids match previewed ids",
                    sorted(modified_ids) == sorted(previewed_ids)
                    and len(modified_ids) == count,
                ),
            ],
        )

        # 4. independent verify — re-read the model state
        after_apply = self._snapshot(client, category, parameter)
        gate(
            "verify",
            None,
            [
                (
                    "targets carry new value",
                    all(
                        after_apply.get(eid) == new_value
                        for eid in modified_ids
                    ),
                ),
                (
                    "non-targets untouched",
                    all(
                        after_apply[eid] == baseline_values[eid]
                        for eid in baseline_values
                        if eid not in modified_ids
                    ),
                ),
            ],
        )

        # 5. revert — through the same capability path
        original_values = {
            eid: baseline_values[eid] for eid in modified_ids
        }
        distinct_originals = set(original_values.values())
        revert_ok = len(distinct_originals) == 1
        revert_run_id = None
        if revert_ok:
            revert = self._bridge(
                client,
                loop_id,
                "g5-revert",
                "SetParameterValue",
                {
                    **args,
                    "Value": next(iter(distinct_originals)),
                    "Mode": "apply",
                },
            )
            revert_run_id = revert.run_id
            revert_tr = revert.tool_result
            reverted_ids = (
                list(revert_tr.modified_ids)
                if revert_tr is not None
                else []
            )
            gate(
                "revert",
                revert_run_id,
                [
                    ("revert pass", revert.classification == "pass"),
                    (
                        "revert targets match applied ids",
                        sorted(reverted_ids) == sorted(modified_ids),
                    ),
                ],
            )
        else:
            gate(
                "revert",
                None,
                [
                    (
                        "single original value (v1 revert constraint)",
                        False,
                    )
                ],
            )

        # 6. final verify — model back to baseline
        final_values = self._snapshot(client, category, parameter)
        gate(
            "final_verify",
            None,
            [
                ("values restored", final_values == baseline_values),
                (
                    "category counts unchanged",
                    client.model.category_counts() == baseline_counts,
                ),
            ],
        )

        status = (
            "passed" if all(g["passed"] for g in gates) else "failed"
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "loop_id": loop_id,
            "adapter": ADAPTER_ID,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "mutation": {
                "category": category,
                "parameter_name": parameter,
                "value": new_value,
                "element_count": count,
            },
            "gates": gates,
            "fidelity_note": FIDELITY_NOTE,
        }
        self._persist(report)
        return report

    def _persist(self, report: dict[str, Any]) -> None:
        sandbox = self._loop_dir.resolve()
        run_dir = (sandbox / report["loop_id"]).resolve()
        if not is_within_sandbox(run_dir, sandbox):
            raise ValueError("loop run dir escapes the artifacts sandbox")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        (run_dir / "pass_fail.json").write_text(
            json.dumps(
                {
                    "loop_id": report["loop_id"],
                    "passed": report["status"] == "passed",
                    "gates_passed": sum(
                        1 for g in report["gates"] if g["passed"]
                    ),
                    "gate_count": len(report["gates"]),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
