"""Execution Chain Orchestrator v1.

A *thin* vertical-slice orchestrator that drives one deterministic capability
through the existing execution stack as a real, linked producer/consumer chain:

    selected capability (self-model-build / code-inventory)
        -> ExecutionPlan
        -> ExecutionStep
        -> ExecutionAttempt
        -> ExecutionResult
        -> ExecutionArtifact
        -> Evidence (bundle)
        -> ExecutionReport

This module introduces **no new execution object family** and **does not
replace** any existing execution object. It is a coordinator only: it calls the
existing ``execution_plan``, ``execution_step``, ``execution_attempt_v2``,
``execution_result``, ``execution_artifact`` and ``execution_report`` engines in
order and passes each stage's *real* identifier forward as a typed reference, so
that for every transition::

    downstream.reference(type == Upstream).reference_value == upstream.<id>

Where PR #144's gap analysis found the chain to be *nominal* (declared by
docstrings, "consumed read-only", but unwired by any real id flow), this layer
proves the chain is *executable*: each downstream stage reconstructs its
upstream via a recorded identifier rather than prose.

It is deliberately observational over the capability it runs: the selected
capability (``self-model-build``) is deterministic, CI-safe and requires no
Revit runtime. Non-goals: no new framework, no Execution Graph Synthesizer, no
Organizational State schema, no Evidence-to-Promotion implementation, no
Purpose/Layer Index implementation, no scheduling, no network calls.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.evidence_quality import evaluate_quality
from axiom_core.execution_artifact import ExecutionArtifactEngine
from axiom_core.execution_attempt_v2 import ExecutionAttemptEngine
from axiom_core.execution_plan import ExecutionPlanEngine
from axiom_core.execution_report import ExecutionReportEngine
from axiom_core.execution_result import ExecutionResultEngine
from axiom_core.execution_step import ExecutionStepEngine
from axiom_core.self_model import SelfModelBuilder

SCHEMA_VERSION = "1.0"

# Capability names this orchestrator accepts for the deterministic slice. Both
# names resolve to the same self-model-build path (M1's producer).
_SELF_MODEL_CAPABILITIES = {"self-model-build", "code-inventory"}


class ExecutionChainError(RuntimeError):
    """Raised when the chain cannot preserve real id flow between stages.

    This is the missing-upstream guard: if any stage fails to yield a real
    identifier, the orchestrator refuses to fabricate a downstream object with a
    dangling reference and raises instead.
    """


# ---------------------------------------------------------------------------
# Trace model (a view over the created objects; not a new execution object)
# ---------------------------------------------------------------------------


@dataclass
class ChainTransition:
    """One proven upstream -> downstream id-flow edge."""

    upstream_stage: str
    upstream_id: str
    downstream_stage: str
    reference_type: str
    reference_value: str

    @property
    def ok(self) -> bool:
        return bool(self.reference_value) and self.reference_value == self.upstream_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "upstream_stage": self.upstream_stage,
            "upstream_id": self.upstream_id,
            "downstream_stage": self.downstream_stage,
            "reference_type": self.reference_type,
            "reference_value": self.reference_value,
            "ok": self.ok,
        }


@dataclass
class ExecutionChainTrace:
    """A linked, inspectable trace of one execution-chain run.

    Holds the real identifier produced at every stage, the created objects (for
    deep inspection / re-validation), the proven id-flow transitions, the
    evidence reference, and the M2/M3 hooks. ``status`` is ``PASS`` only when
    every required transition resolves ``downstream == upstream``.
    """

    capability_id: str
    run_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = SCHEMA_VERSION

    plan_id: str = ""
    step_id: str = ""
    attempt_id: str = ""
    result_id: str = ""
    artifact_id: str = ""
    evidence_id: str = ""
    report_id: str = ""

    capability_output: dict[str, Any] = field(default_factory=dict)
    evidence_reference: dict[str, Any] = field(default_factory=dict)
    transitions: list[ChainTransition] = field(default_factory=list)
    objects: dict[str, Any] = field(default_factory=dict)
    m2_hook: dict[str, Any] = field(default_factory=dict)
    m3_hook: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "PASS" if self.transitions and all(t.ok for t in self.transitions) else (
            "FAIL"
        )

    def resolve_chain(self) -> list[str]:
        """Walk report -> artifact/result -> attempt -> step -> plan by id.

        Returns the ordered identifiers proving the terminal report resolves all
        the way back to the originating plan. Raises if any link is missing.
        """
        chain = [
            ("report", self.report_id),
            ("artifact", self.artifact_id),
            ("result", self.result_id),
            ("attempt", self.attempt_id),
            ("step", self.step_id),
            ("plan", self.plan_id),
        ]
        for stage, value in chain:
            if not value:
                raise ExecutionChainError(
                    f"end-to-end trace broken: missing {stage} id"
                )
        return [value for _, value in chain]

    def deterministic_view(self) -> dict[str, Any]:
        """Id-/timestamp-free view for determinism assertions."""
        return {
            "capability_id": self.capability_id,
            "schema_version": self.schema_version,
            "capability_output": self.capability_output,
            "transitions": [
                {
                    "upstream_stage": t.upstream_stage,
                    "downstream_stage": t.downstream_stage,
                    "reference_type": t.reference_type,
                    "ok": t.ok,
                }
                for t in self.transitions
            ],
            "evidence_reference": {
                # capability_id is deterministic; per-run object ids are not, so
                # only the stable reference *shape* is compared here.
                "reference_keys": sorted(
                    self.evidence_reference.get("references", {}).keys()
                ),
                "capability_id": self.evidence_reference.get(
                    "references", {}
                ).get("capability_id", ""),
            },
            "status": self.status,
            "m2_hook": {
                "could_affect": self.m2_hook.get("could_affect", []),
                "metrics": self.m2_hook.get("evidence_produced", {}).get(
                    "metrics", {}
                ),
                "note": self.m2_hook.get("note", ""),
            },
            "m3_hook": self.m3_hook,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "capability_id": self.capability_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "result_id": self.result_id,
            "artifact_id": self.artifact_id,
            "evidence_id": self.evidence_id,
            "report_id": self.report_id,
            "status": self.status,
            "capability_output": self.capability_output,
            "evidence_reference": self.evidence_reference,
            "transitions": [t.to_dict() for t in self.transitions],
            "m2_hook": self.m2_hook,
            "m3_hook": self.m3_hook,
        }

    def summary(self) -> dict[str, Any]:
        """Compact id + status roll-up (used by the CLI)."""
        return {
            "capability_id": self.capability_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "result_id": self.result_id,
            "artifact_id": self.artifact_id,
            "evidence_reference": self.evidence_id,
            "report_id": self.report_id,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ExecutionChainOrchestrator:
    """Drives one deterministic capability through the full execution chain.

    The orchestrator owns no execution object model; it instantiates the
    existing engines and threads real identifiers from one stage to the next.
    """

    def __init__(
        self, repo_root: str | Path = ".", artifacts_root: str | None = None
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self.artifacts_root = str(artifacts_root)
        self._chain_dir = Path(self.artifacts_root) / "execution_chain"

    # -- public API --------------------------------------------------------

    def run(self, capability: str) -> ExecutionChainTrace:
        """Execute ``capability`` through Plan -> ... -> Report.

        Returns a linked :class:`ExecutionChainTrace`. Raises
        :class:`ExecutionChainError` for an unsupported capability or any broken
        id-flow transition (missing-upstream guard).
        """
        capability_id = self._normalize_capability(capability)
        trace = ExecutionChainTrace(capability_id=capability_id)

        # Stage 0: run the deterministic capability (real producer output).
        model, metrics = self._run_capability()
        trace.capability_output = metrics

        # Stage 1: ExecutionPlan.
        plan = self._create_plan(capability_id, metrics)
        trace.plan_id = plan["plan_id"]

        # Stage 2: ExecutionStep references the real plan id.
        step = self._create_step(capability_id, trace.plan_id, metrics)
        trace.step_id = step["step_id"]

        # Stage 3: ExecutionAttempt references the real step id.
        attempt = self._create_attempt(
            capability_id, trace.plan_id, trace.step_id
        )
        trace.attempt_id = attempt["attempt_id"]

        # Stage 4: ExecutionResult references the real attempt id.
        result = self._create_result(
            capability_id, trace.step_id, trace.attempt_id, metrics
        )
        trace.result_id = result["result_id"]

        # Stage 5: ExecutionArtifact references the real result id.
        artifact_path = self._write_capability_artifact(trace.run_id, model, metrics)
        artifact = self._create_artifact(
            capability_id,
            trace.attempt_id,
            trace.result_id,
            artifact_path,
        )
        trace.artifact_id = artifact["artifact_id"]

        # Stage 6: Evidence bundle references result + artifact + capability.
        evidence = self._write_evidence(trace, metrics)
        trace.evidence_id = evidence["evidence_id"]
        trace.evidence_reference = evidence

        # Stage 7: ExecutionReport references result + artifact + evidence.
        report = self._create_report(
            capability_id,
            trace.attempt_id,
            trace.result_id,
            trace.artifact_id,
            trace.evidence_id,
            metrics,
        )
        trace.report_id = report["report_id"]

        trace.objects = {
            "plan": plan,
            "step": step,
            "attempt": attempt,
            "result": result,
            "artifact": artifact,
            "evidence": evidence,
            "report": report,
        }
        trace.transitions = self._build_transitions(trace, step, attempt, result,
                                                     artifact, report)
        trace.m2_hook = self._m2_hook(trace, metrics)
        trace.m3_hook = self._m3_hook(capability_id)

        self._assert_id_flow(trace)
        self._persist_trace(trace)
        return trace

    # -- capability --------------------------------------------------------

    def _normalize_capability(self, capability: str) -> str:
        name = (capability or "").strip()
        if name not in _SELF_MODEL_CAPABILITIES:
            raise ExecutionChainError(
                f"Unsupported capability for the deterministic chain slice: "
                f"{capability!r}. Supported: {sorted(_SELF_MODEL_CAPABILITIES)}"
            )
        # Canonical id for the slice subject.
        return "self-model-build"

    def _run_capability(self) -> tuple[dict[str, Any], dict[str, Any]]:
        builder = SelfModelBuilder(self.repo_root)
        model = builder.build()
        modules = model["modules"]
        edges = model["edges"]
        connected: set[str] = set()
        for src, dst in edges:
            connected.add(src)
            connected.add(dst)
        isolated = sorted(m for m in modules if m not in connected)
        metrics = {
            "module_count": len(modules),
            "import_edge_count": len(edges),
            "isolated_module_count": len(isolated),
        }
        return model, metrics

    # -- stage builders ----------------------------------------------------

    def _create_plan(
        self, capability_id: str, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        engine = ExecutionPlanEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            plans=[
                {
                    "capability_id": capability_id,
                    "readiness_id": f"chain-readiness-{capability_id}",
                    "chain_id": f"chain-{capability_id}",
                    "plan_type": "VALIDATION",
                    "status": "COMPLETED",
                    "summary": (
                        f"Execution-chain plan for {capability_id}: prove real "
                        f"id flow through the existing execution stack."
                    ),
                    "steps": [
                        {
                            "step_name": "run-deterministic-capability",
                            "order_index": 0,
                            "summary": (
                                f"Run {capability_id} "
                                f"({metrics['module_count']} modules)."
                            ),
                        }
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "plans", "plan_id")

    def _create_step(
        self, capability_id: str, plan_id: str, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        engine = ExecutionStepEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            steps=[
                {
                    "plan_id": plan_id,
                    "capability_id": capability_id,
                    "step_type": "VALIDATION",
                    "status": "COMPLETED",
                    "order_index": 0,
                    "summary": f"Execute {capability_id} for the chain slice.",
                    "references": [
                        {
                            "reference_type": "PLAN",
                            "reference_value": plan_id,
                            "summary": "Consumes the originating ExecutionPlan id.",
                        }
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "steps", "step_id")

    def _create_attempt(
        self, capability_id: str, plan_id: str, step_id: str
    ) -> dict[str, Any]:
        engine = ExecutionAttemptEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            attempts=[
                {
                    "step_id": step_id,
                    "plan_id": plan_id,
                    "capability_id": capability_id,
                    "status": "COMPLETED",
                    "result": "SUCCESS",
                    "summary": f"Attempt executing {capability_id}.",
                    "references": [
                        {
                            "reference_type": "STEP",
                            "reference_value": step_id,
                            "summary": "Consumes the upstream ExecutionStep id.",
                        }
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "attempts", "attempt_id")

    def _create_result(
        self,
        capability_id: str,
        step_id: str,
        attempt_id: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        engine = ExecutionResultEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            results=[
                {
                    "attempt_id": attempt_id,
                    "step_id": step_id,
                    "capability_id": capability_id,
                    "result_type": "OUTPUT",
                    "status": "PRODUCED",
                    "summary": (
                        f"{capability_id} produced "
                        f"{metrics['module_count']} modules / "
                        f"{metrics['import_edge_count']} import edges."
                    ),
                    "references": [
                        {
                            "reference_type": "ATTEMPT",
                            "reference_value": attempt_id,
                            "summary": "Consumes the upstream ExecutionAttempt id.",
                        }
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "results", "result_id")

    def _create_artifact(
        self,
        capability_id: str,
        attempt_id: str,
        result_id: str,
        artifact_path: str,
    ) -> dict[str, Any]:
        engine = ExecutionArtifactEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            artifacts=[
                {
                    "result_id": result_id,
                    "attempt_id": attempt_id,
                    "capability_id": capability_id,
                    "artifact_type": "FILE",
                    "status": "CREATED",
                    "artifact_path": artifact_path,
                    "summary": f"Structured output of {capability_id}.",
                    "references": [
                        {
                            "reference_type": "RESULT",
                            "reference_value": result_id,
                            "summary": "Consumes the upstream ExecutionResult id.",
                        }
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "artifacts", "artifact_id")

    def _create_report(
        self,
        capability_id: str,
        attempt_id: str,
        result_id: str,
        artifact_id: str,
        evidence_id: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        engine = ExecutionReportEngine(artifacts_root=self.artifacts_root)
        assembled = engine.create(
            reports=[
                {
                    "capability_id": capability_id,
                    "attempt_id": attempt_id,
                    "result_id": result_id,
                    "report_type": "FINAL_SUMMARY",
                    "status": "COMPLETE",
                    "summary": (
                        f"Execution-chain run for {capability_id}: "
                        f"{metrics['module_count']} modules, "
                        f"{metrics['import_edge_count']} edges."
                    ),
                    "sections": [
                        {
                            "section_type": "RESULT",
                            "title": "Capability output",
                            "order_index": 0,
                            "content": json.dumps(metrics, sort_keys=True),
                        },
                        {
                            "section_type": "ARTIFACTS",
                            "title": "Evidence",
                            "order_index": 1,
                            "content": (
                                f"artifact={artifact_id}; evidence={evidence_id}"
                            ),
                        },
                    ],
                    "references": [
                        {
                            "reference_type": "RESULT",
                            "reference_value": result_id,
                            "summary": "Consumes the upstream ExecutionResult id.",
                        },
                        {
                            "reference_type": "ARTIFACT",
                            "reference_value": artifact_id,
                            "summary": "Consumes the upstream ExecutionArtifact id.",
                        },
                        {
                            "reference_type": "FILE",
                            "reference_value": evidence_id,
                            "summary": "Consumes the run evidence-bundle id.",
                        },
                    ],
                }
            ],
            raw_metadata=self._meta(capability_id),
        )
        return self._extract(assembled, "reports", "report_id")

    # -- evidence / artifacts on disk -------------------------------------

    def _write_capability_artifact(
        self, run_id: str, model: dict[str, Any], metrics: dict[str, Any]
    ) -> str:
        run_dir = self._chain_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "self_model.json"
        payload = {
            "modules": model["modules"],
            "edges": [list(e) for e in model["edges"]],
            "metrics": metrics,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return str(path)

    def _write_evidence(
        self, trace: ExecutionChainTrace, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        run_dir = self._chain_dir / trace.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        evidence_id = str(uuid4())
        references = {
            "capability_id": trace.capability_id,
            "result_id": trace.result_id,
            "artifact_id": trace.artifact_id,
        }
        # Evidence-quality / substance verdict (Finding 2). This is orthogonal
        # to the chain's id-flow ``status``: it judges whether the produced
        # metrics are substantive so the downstream promotion gate can quarantine
        # semantically empty evidence. Stamped here so the verdict travels with
        # the bundle (the bundle is the navigable record).
        quality = evaluate_quality(trace.capability_id, metrics)
        evidence = {
            "evidence_id": evidence_id,
            "references": references,
            "metrics": metrics,
            "quality": quality,
            "summary": (
                f"Evidence for {trace.capability_id} chain run: "
                f"result {trace.result_id} produced artifact {trace.artifact_id}."
            ),
        }
        path = run_dir / "evidence.json"
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True))
        evidence["evidence_path"] = str(path)
        return evidence

    def _persist_trace(self, trace: ExecutionChainTrace) -> None:
        run_dir = self._chain_dir / trace.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "trace.json"
        path.write_text(json.dumps(trace.to_dict(), indent=2, sort_keys=True))

    # -- persisted-record resolution --------------------------------------

    # (stage subdir, container key, id field) for the six execution engines.
    _PERSISTED_STAGES = (
        ("execution_plan", "plans", "plan_id"),
        ("execution_step", "steps", "step_id"),
        ("execution_attempt_v2", "attempts", "attempt_id"),
        ("execution_result", "results", "result_id"),
        ("execution_artifact", "artifacts", "artifact_id"),
        ("execution_report", "reports", "report_id"),
    )

    def load_persisted_index(self) -> dict[str, dict[str, Any]]:
        """Index every persisted execution object by its real id.

        Reads each engine's append-only ``report.json`` files back from
        ``artifacts_root`` so resolution is proven against records on disk, not
        against the in-memory orchestrator response.
        """
        index: dict[str, dict[str, Any]] = {}
        root = Path(self.artifacts_root)
        for subdir, container_key, id_field in self._PERSISTED_STAGES:
            for report_file in (root / subdir).glob("*/report.json"):
                data = json.loads(report_file.read_text())
                for obj in data.get(container_key, []):
                    obj_id = obj.get(id_field)
                    if obj_id:
                        index[obj_id] = obj
        return index

    def resolve_persisted(self, trace: ExecutionChainTrace) -> list[str]:
        """Resolve report -> artifact/result -> attempt -> step -> plan on disk.

        Walks the terminal report's persisted references back to the plan,
        confirming each upstream record exists and each id link matches. Raises
        :class:`ExecutionChainError` if any persisted link is missing.
        """
        index = self.load_persisted_index()

        def _require(obj_id: str, stage: str) -> dict[str, Any]:
            obj = index.get(obj_id)
            if obj is None:
                raise ExecutionChainError(
                    f"persisted {stage} record {obj_id!r} not found on disk"
                )
            return obj

        report = _require(trace.report_id, "report")
        result_ref = self._ref_value(report, "RESULT")
        artifact_ref = self._ref_value(report, "ARTIFACT")
        if result_ref != trace.result_id or artifact_ref != trace.artifact_id:
            raise ExecutionChainError("persisted report references do not match")
        artifact = _require(artifact_ref, "artifact")
        result = _require(result_ref, "result")
        attempt = _require(self._ref_value(result, "ATTEMPT"), "attempt")
        step = _require(self._ref_value(attempt, "STEP"), "step")
        plan = _require(self._ref_value(step, "PLAN"), "plan")
        if self._ref_value(artifact, "RESULT") != trace.result_id:
            raise ExecutionChainError("persisted artifact does not reference result")
        return [
            report["report_id"],
            artifact["artifact_id"],
            result["result_id"],
            attempt["attempt_id"],
            step["step_id"],
            plan["plan_id"],
        ]

    # -- id-flow proof -----------------------------------------------------

    @staticmethod
    def _ref_value(obj: dict[str, Any], reference_type: str) -> str:
        for ref in obj.get("references", []):
            if ref.get("reference_type") == reference_type:
                return str(ref.get("reference_value", ""))
        return ""

    def _build_transitions(
        self,
        trace: ExecutionChainTrace,
        step: dict[str, Any],
        attempt: dict[str, Any],
        result: dict[str, Any],
        artifact: dict[str, Any],
        report: dict[str, Any],
    ) -> list[ChainTransition]:
        return [
            ChainTransition(
                "ExecutionPlan", trace.plan_id, "ExecutionStep", "PLAN",
                self._ref_value(step, "PLAN"),
            ),
            ChainTransition(
                "ExecutionStep", trace.step_id, "ExecutionAttempt", "STEP",
                self._ref_value(attempt, "STEP"),
            ),
            ChainTransition(
                "ExecutionAttempt", trace.attempt_id, "ExecutionResult", "ATTEMPT",
                self._ref_value(result, "ATTEMPT"),
            ),
            ChainTransition(
                "ExecutionResult", trace.result_id, "ExecutionArtifact", "RESULT",
                self._ref_value(artifact, "RESULT"),
            ),
            ChainTransition(
                "ExecutionResult", trace.result_id, "ExecutionReport", "RESULT",
                self._ref_value(report, "RESULT"),
            ),
            ChainTransition(
                "ExecutionArtifact", trace.artifact_id, "ExecutionReport", "ARTIFACT",
                self._ref_value(report, "ARTIFACT"),
            ),
            ChainTransition(
                "Evidence", trace.evidence_id, "ExecutionReport", "FILE",
                self._ref_value(report, "FILE"),
            ),
        ]

    def _assert_id_flow(self, trace: ExecutionChainTrace) -> None:
        broken = [t for t in trace.transitions if not t.ok]
        if broken:
            details = ", ".join(
                f"{t.downstream_stage}.{t.reference_type}="
                f"{t.reference_value!r} != {t.upstream_stage}={t.upstream_id!r}"
                for t in broken
            )
            raise ExecutionChainError(f"id flow not preserved: {details}")
        # Evidence must reference the real result + artifact + capability.
        refs = trace.evidence_reference.get("references", {})
        if refs.get("result_id") != trace.result_id:
            raise ExecutionChainError("evidence does not reference the real result id")
        if refs.get("artifact_id") != trace.artifact_id:
            raise ExecutionChainError(
                "evidence does not reference the real artifact id"
            )

    # -- hooks (recorded only; not implemented beyond M4) ------------------

    def _m2_hook(
        self, trace: ExecutionChainTrace, metrics: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "evidence_produced": {
                "evidence_id": trace.evidence_id,
                "artifact_id": trace.artifact_id,
                "result_id": trace.result_id,
                "metrics": metrics,
            },
            "could_affect": [
                "capability_state",
                "readiness",
                "confidence",
                "promotion_status",
            ],
            "note": (
                "Evidence-to-Promotion is NOT implemented in this PR. Recorded "
                "only: a future M2 step could feed this evidence into "
                "global_capability_registry / capability_confidence to change "
                "the capability's promotion state."
            ),
        }

    def _m3_hook(self, capability_id: str) -> dict[str, Any]:
        return {
            "purpose": "Build a deterministic repository self-model.",
            "layer": "self_model",
            "consumes": ["code-inventory"],
            "intended_use": (
                "Answer structural repository questions and feed gap analysis."
            ),
            "required_to_execute": [
                "capability purpose (what self-model-build produces)",
                "capability layer (self_model)",
                "upstream dependency (code-inventory import edges)",
            ],
            "note": (
                "Purpose/Layer Index is NOT implemented in this PR. Recorded "
                "only: this is the purpose/layer/consumer information that was "
                f"required to execute {capability_id} intelligently."
            ),
        }

    # -- helpers -----------------------------------------------------------

    def _meta(self, capability_id: str) -> dict[str, Any]:
        return {
            "source": "execution_chain_orchestrator",
            "milestone": "M4",
            "capability_id": capability_id,
        }

    @staticmethod
    def _extract(
        assembled: dict[str, Any], container_key: str, id_field: str
    ) -> dict[str, Any]:
        items = assembled.get(container_key) or []
        if not items:
            raise ExecutionChainError(
                f"stage produced no {container_key[:-1]} object "
                f"(missing-upstream guard: cannot continue the chain)"
            )
        obj = items[0]
        if not obj.get(id_field):
            raise ExecutionChainError(
                f"stage object is missing its real {id_field}"
            )
        return obj
