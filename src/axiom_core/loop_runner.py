"""Loop Runner v1.

Wires the existing engines into one bounded autonomous cycle:

    gap analysis -> work queue -> execution chain -> evidence apply -> re-queue

Per cycle it (1) builds the repository self-model and runs the gap
analyzer over it, (2) creates a work-queue report whose items are the
top-ranked gap recommendations plus the executable chain run, (3) drives
the deterministic capability through the execution-chain orchestrator,
(4) applies the produced evidence bundle to capability confidence via the
evidence-promotion engine, and (5) re-queues follow-up work derived from
the intake decision (rejected/quarantined evidence re-queues at high
priority).

The loop is strictly bounded (``MAX_LOOP_CYCLES``), stops on the first
chain failure, owns no new object model, and mutates nothing upstream —
every stage is the existing engine producing its normal artifacts. The
loop report links the real ids from every stage of every cycle.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox
from axiom_core.evidence_promotion import EvidencePromotionLoop
from axiom_core.execution_chain_orchestrator import (
    ExecutionChainError,
    ExecutionChainOrchestrator,
)
from axiom_core.self_model import SelfModelBuilder
from axiom_core.self_model_gap_analysis import SelfModelGapAnalyzer
from axiom_core.work_queue import WorkQueueEngine

SCHEMA_VERSION = "1.0"

MAX_LOOP_CYCLES = 10
MAX_QUEUED_GAP_ITEMS = 5

# Gap-analysis priority (high/medium/low) -> work-queue priority.
_QUEUE_PRIORITY = {
    "high": "high",
    "medium": "normal",
    "low": "low",
}


class LoopRunner:
    """Run bounded gap->queue->chain->evidence->re-queue cycles."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        artifacts_root: str | None = None,
        capability: str = "self-model-build",
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self.artifacts_root = str(artifacts_root)
        self.capability = capability
        self._loop_dir = Path(self.artifacts_root) / "loop_runner"
        self._queue_engine = WorkQueueEngine(artifacts_root=self.artifacts_root)
        self._promotion = EvidencePromotionLoop(
            artifacts_root=self.artifacts_root
        )
        self._orchestrator = ExecutionChainOrchestrator(
            repo_root=self.repo_root, artifacts_root=self.artifacts_root
        )

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def _gap_analysis(self) -> dict[str, Any]:
        builder = SelfModelBuilder(self.repo_root)
        model = builder.build()
        payload = builder.graph_payload(model)
        connected: set[str] = set()
        for edge in payload["edges"]:
            connected.add(edge["source_node_id"])
            connected.add(edge["target_node_id"])
        orphans = sorted(
            m for m in payload["modules"] if m not in connected
        )
        analyzer = SelfModelGapAnalyzer(
            {
                "report_id": "",
                "nodes": payload["nodes"],
                "edges": payload["edges"],
                "orphan_node_ids": orphans,
            }
        )
        return analyzer.analyze()

    def _queue_items(
        self, gap_result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {
                "title": f"execution-chain-run {self.capability}",
                "description": (
                    "Executable loop item: drive the capability through "
                    "the full execution chain and apply its evidence."
                ),
                "priority": "high",
                "status": "pending",
            }
        ]
        for gap in gap_result.get("gaps", [])[:MAX_QUEUED_GAP_ITEMS]:
            items.append({
                "title": f"{gap.get('gap_id', '')}: {gap.get('title', '')}",
                "description": str(
                    gap.get("proposed_smallest_fix", "")
                )[:500],
                "priority": _QUEUE_PRIORITY.get(
                    str(gap.get("priority", "")).lower(), "normal"
                ),
                "status": "pending",
            })
        return items

    def _requeue_items(
        self, intake: dict[str, Any]
    ) -> list[dict[str, Any]]:
        decision = str(intake.get("decision", "")).strip().lower()
        capability_id = intake.get("capability_id", self.capability)
        if decision == "accepted":
            state = intake.get("updated_state", {}) or {}
            return [{
                "title": f"re-validate {capability_id}",
                "description": (
                    f"Evidence accepted (confidence="
                    f"{state.get('confidence_level', '')}, readiness="
                    f"{state.get('readiness', '')}); queue the next "
                    "distinct run to accumulate evidence mass."
                ),
                "priority": "normal",
                "status": "pending",
            }]
        return [{
            "title": f"investigate {decision or 'unknown'} evidence "
                     f"for {capability_id}",
            "description": str(intake.get("reason", ""))[:500],
            "priority": "high",
            "status": "pending",
        }]

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def run(self, cycles: int = 1) -> dict[str, Any]:
        """Run ``cycles`` bounded loop cycles and persist a loop report."""
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        if cycles > MAX_LOOP_CYCLES:
            raise ValueError(
                f"cycles must be <= {MAX_LOOP_CYCLES} (bounded loop)"
            )

        loop_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        cycle_records: list[dict[str, Any]] = []
        status = "passed"

        for index in range(1, cycles + 1):
            record: dict[str, Any] = {"cycle": index}

            gap_result = self._gap_analysis()
            record["gap_analysis"] = {
                "module_count": gap_result["module_count"],
                "edge_count": gap_result["edge_count"],
                "gap_count": gap_result["gap_count"],
                "gap_counts_by_type": gap_result["gap_counts_by_type"],
            }

            queue = self._queue_engine.create(
                self._queue_items(gap_result)
            )
            record["queue_report_id"] = queue["report_id"]
            record["queued_item_count"] = queue["queue"]["item_count"]

            try:
                trace = self._orchestrator.run(self.capability)
            except ExecutionChainError as exc:
                record["chain_error"] = str(exc)
                cycle_records.append(record)
                status = "failed"
                break

            record["chain_run_id"] = trace.run_id
            record["chain_status"] = trace.status
            record["chain_ids"] = {
                "plan_id": trace.plan_id,
                "attempt_id": trace.attempt_id,
                "result_id": trace.result_id,
                "artifact_id": trace.artifact_id,
                "evidence_id": trace.evidence_id,
                "report_id": trace.report_id,
            }

            evidence_path = os.path.join(
                self.artifacts_root,
                "execution_chain",
                trace.run_id,
                "evidence.json",
            )
            intake = self._promotion.apply(
                evidence_path, capability_id=self.capability
            )
            record["intake_id"] = intake.get("intake_id", "")
            record["evidence_decision"] = intake.get("decision", "")
            record["state_changed"] = intake.get("state_changed", False)
            record["updated_state"] = intake.get("updated_state", {})

            requeue = self._queue_engine.create(
                self._requeue_items(intake)
            )
            record["requeue_report_id"] = requeue["report_id"]
            cycle_records.append(record)

        report = {
            "loop_id": loop_id,
            "schema_version": SCHEMA_VERSION,
            "capability_id": self.capability,
            "requested_cycles": cycles,
            "completed_cycles": len(
                [r for r in cycle_records if "chain_run_id" in r]
            ),
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "cycles": cycle_records,
        }
        self._persist(report)
        return report

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: dict[str, Any]) -> None:
        run_dir = self._loop_dir / report["loop_id"]
        if not is_within_sandbox(run_dir, self._loop_dir):
            raise ValueError(f"Unsafe loop report path: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        (run_dir / "pass_fail.json").write_text(
            json.dumps(
                {
                    "loop_id": report["loop_id"],
                    "status": report["status"],
                    "passed": report["status"] == "passed",
                    "completed_cycles": report["completed_cycles"],
                    "requested_cycles": report["requested_cycles"],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
