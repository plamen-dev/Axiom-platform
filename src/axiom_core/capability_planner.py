"""Knowledge-Aware Capability Planner — structured plan generation.

Consumes the knowledge graph, semantic retrieval engine, workflow registry,
provenance records, learning candidates, and reviews to produce structured
capability plans.

Planning infrastructure only.  No execution.  No workflow mutation.
No autonomous behavior.  No learning.

Plans are recommendations only — they do not execute capabilities or
mutate knowledge state.

Persistence via SQLAlchemy/SQLite (reuses the Axiom database layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_STEPS_DEFAULT = 15
MAX_STEPS_CAP = 50


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DependencyType(Enum):
    """Relationship between planning steps."""

    REQUIRES = "requires"
    RECOMMENDS = "recommends"
    VALIDATES = "validates"
    DERIVED_FROM = "derived_from"


class PlanStatus(Enum):
    """Status of a generated plan."""

    GENERATED = "generated"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# ORM Row
# ---------------------------------------------------------------------------


class CapabilityPlanRow(Base):
    """SQLAlchemy row for persisted capability plans."""

    __tablename__ = "capability_plans"

    plan_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="generated")
    steps_json: Mapped[str] = mapped_column(Text, nullable=True)
    dependencies_json: Mapped[str] = mapped_column(Text, nullable=True)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=True)
    risks_json: Mapped[str] = mapped_column(Text, nullable=True)
    validations_json: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    explanations_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PlanningExplanation:
    """Explains why a planning step exists."""

    def __init__(self, reason: str, source: str | None = None) -> None:
        self.reason = reason
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"reason": self.reason}
        if self.source is not None:
            d["source"] = self.source
        return d


class PlanningEvidence:
    """Evidence supporting a planning step or decision."""

    def __init__(
        self,
        evidence_type: str = "",
        reference_id: str | None = None,
        description: str | None = None,
        trust_level: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.reference_id = reference_id
        self.description = description
        self.trust_level = trust_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "reference_id": self.reference_id,
            "description": self.description,
            "trust_level": self.trust_level,
        }


class PlanningDependency:
    """A dependency between planning steps."""

    def __init__(
        self,
        dependency_id: str = "",
        from_step_id: str = "",
        to_step_id: str = "",
        dependency_type: DependencyType | str = DependencyType.REQUIRES,
        description: str | None = None,
    ) -> None:
        self.dependency_id = dependency_id or str(uuid4())
        self.from_step_id = from_step_id
        self.to_step_id = to_step_id
        if isinstance(dependency_type, str):
            try:
                self.dependency_type = DependencyType(dependency_type)
            except ValueError:
                self.dependency_type = DependencyType.REQUIRES
        else:
            self.dependency_type = dependency_type
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "from_step_id": self.from_step_id,
            "to_step_id": self.to_step_id,
            "dependency_type": self.dependency_type.value,
            "description": self.description,
        }


class PlanningStep:
    """A single step in a capability plan."""

    def __init__(
        self,
        step_id: str = "",
        sequence: int = 0,
        title: str = "",
        description: str | None = None,
        required_capabilities: list[str] | None = None,
        evidence: list[PlanningEvidence] | None = None,
        risk_notes: str | None = None,
        explanation: PlanningExplanation | None = None,
    ) -> None:
        self.step_id = step_id or str(uuid4())
        self.sequence = sequence
        self.title = title
        self.description = description
        self.required_capabilities = required_capabilities if required_capabilities is not None else []
        self.evidence = evidence if evidence is not None else []
        self.risk_notes = risk_notes
        self.explanation = explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "sequence": self.sequence,
            "title": self.title,
            "description": self.description,
            "required_capabilities": self.required_capabilities,
            "evidence": [e.to_dict() for e in self.evidence],
            "risk_notes": self.risk_notes,
            "explanation": self.explanation.to_dict() if self.explanation else None,
        }


class PlanningRequest:
    """Encapsulates a planning request."""

    def __init__(
        self,
        objective: str,
        max_steps: int = MAX_STEPS_DEFAULT,
    ) -> None:
        self.objective = objective
        self.max_steps = min(max(max_steps, 1), MAX_STEPS_CAP)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "max_steps": self.max_steps,
        }


class PlanningResult:
    """Container for a generated capability plan."""

    def __init__(
        self,
        plan_id: str = "",
        objective: str = "",
        status: PlanStatus | str = PlanStatus.GENERATED,
        assumptions: list[str] | None = None,
        steps: list[PlanningStep] | None = None,
        dependencies: list[PlanningDependency] | None = None,
        risks: list[str] | None = None,
        validations: list[str] | None = None,
        evidence_references: list[PlanningEvidence] | None = None,
        explanations: list[PlanningExplanation] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.plan_id = plan_id or str(uuid4())
        self.objective = objective
        if isinstance(status, str):
            try:
                self.status = PlanStatus(status)
            except ValueError:
                self.status = PlanStatus.GENERATED
        else:
            self.status = status
        self.assumptions = assumptions if assumptions is not None else []
        self.steps = steps if steps is not None else []
        self.dependencies = dependencies if dependencies is not None else []
        self.risks = risks if risks is not None else []
        self.validations = validations if validations is not None else []
        self.evidence_references = evidence_references if evidence_references is not None else []
        self.explanations = explanations if explanations is not None else []
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "objective": self.objective,
            "status": self.status.value,
            "assumptions": self.assumptions,
            "steps": [s.to_dict() for s in self.steps],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "risks": self.risks,
            "validations": self.validations,
            "evidence_references": [e.to_dict() for e in self.evidence_references],
            "explanations": [e.to_dict() for e in self.explanations],
            "metadata": self.metadata,
            "step_count": len(self.steps),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Capability Planner
# ---------------------------------------------------------------------------


class CapabilityPlanner:
    """Knowledge-aware capability planner.

    Consumes the knowledge graph, semantic retrieval engine, workflow
    definitions, provenance records, reviews, and learning candidates
    to produce structured plans.

    Read-only — never mutates knowledge.
    Plans are recommendations only — they never execute capabilities.
    Deterministic — ordering is by dependency priority, approval status,
    trust level, then name ascending.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path
        self._engine = create_db_engine(db_path)
        init_db(self._engine)
        self._session_factory = make_session_factory(self._engine)

    # --- Public API ---

    def generate_plan(self, request: PlanningRequest) -> PlanningResult:
        """Generate a capability plan from a planning request.

        Raises ValueError for empty objectives.
        """
        objective = request.objective.strip()
        if not objective:
            raise ValueError("Planning objective must not be empty.")

        # Step 1: Retrieve relevant knowledge
        retrieval_matches = self._retrieve_knowledge(objective)

        # Step 2: Extract workflows and their steps
        workflow_steps = self._extract_workflow_steps(retrieval_matches)

        # Step 3: Build planning steps from retrieved knowledge
        steps = self._build_steps(objective, retrieval_matches, workflow_steps, request.max_steps)

        # Step 4: Derive dependencies between steps
        dependencies = self._derive_dependencies(steps, retrieval_matches)

        # Step 5: Collect assumptions, risks, validations
        assumptions = self._collect_assumptions(retrieval_matches)
        risks = self._collect_risks(retrieval_matches)
        validations = self._collect_validations(retrieval_matches)

        # Step 6: Collect evidence references
        evidence_refs = self._collect_evidence(retrieval_matches)

        # Step 7: Generate explanations
        explanations = self._generate_explanations(steps, retrieval_matches)

        result = PlanningResult(
            objective=objective,
            assumptions=assumptions,
            steps=steps,
            dependencies=dependencies,
            risks=risks,
            validations=validations,
            evidence_references=evidence_refs,
            explanations=explanations,
            metadata={
                "knowledge_matches": len(retrieval_matches),
                "workflow_steps_consumed": len(workflow_steps),
            },
        )

        # Persist plan
        self._persist_plan(result)

        return result

    def get_plan(self, plan_id: str) -> PlanningResult | None:
        """Retrieve a persisted plan by ID."""
        with get_session(self._session_factory) as session:
            row = session.get(CapabilityPlanRow, plan_id)
            if row is None:
                return None
            return self._row_to_result(row)

    def list_plans(
        self,
        objective_filter: str | None = None,
        status_filter: PlanStatus | None = None,
    ) -> list[PlanningResult]:
        """List persisted plans with optional filters."""
        with get_session(self._session_factory) as session:
            query = session.query(CapabilityPlanRow)
            if status_filter is not None:
                query = query.filter(CapabilityPlanRow.status == status_filter.value)
            if objective_filter is not None:
                escaped = objective_filter.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.filter(
                    CapabilityPlanRow.objective.ilike(f"%{escaped}%", escape="\\")
                )
            rows = query.order_by(CapabilityPlanRow.created_at.desc()).all()
            return [self._row_to_result(r) for r in rows]

    # --- Internal: Knowledge retrieval ---

    def _retrieve_knowledge(self, objective: str) -> list[dict[str, Any]]:
        """Retrieve relevant knowledge from the semantic retrieval engine."""
        from axiom_core.semantic_retrieval import (
            RetrievalQuery,
            SemanticRetrievalEngine,
        )

        try:
            engine = SemanticRetrievalEngine(db_path=self._db_path)
            query = RetrievalQuery(query_text=objective, max_results=30)
            result = engine.retrieve(query)
            return [m.to_dict() for m in result.matches]
        except (ValueError, Exception):
            return []

    def _extract_workflow_steps(self, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract workflow step information from matched knowledge."""
        from axiom_core.workflow_registry import WorkflowKnowledgeRegistry

        workflow_steps: list[dict[str, Any]] = []
        workflow_ids_seen: set[str] = set()

        try:
            registry = WorkflowKnowledgeRegistry(db_path=self._db_path)
        except Exception:
            return workflow_steps

        for match in matches:
            obj_type = match.get("object_type", "")
            obj_id = match.get("object_id", "")

            if obj_type in ("workflow", "workflow_step") and obj_id:
                # Extract workflow_id from step or workflow node
                wf_id = obj_id.split(":")[0] if ":" in obj_id else obj_id
                if wf_id in workflow_ids_seen:
                    continue
                workflow_ids_seen.add(wf_id)

                wf = registry.get_workflow(wf_id)
                if wf is not None:
                    for step in wf.steps:
                        workflow_steps.append(step.to_dict())

        # Sort by step_order for determinism
        workflow_steps.sort(key=lambda s: (s.get("workflow_id", ""), s.get("step_order", 0)))
        return workflow_steps

    # --- Internal: Step building ---

    def _build_steps(
        self,
        objective: str,
        matches: list[dict[str, Any]],
        workflow_steps: list[dict[str, Any]],
        max_steps: int,
    ) -> list[PlanningStep]:
        """Build planning steps from knowledge matches and workflow steps."""
        steps: list[PlanningStep] = []
        sequence = 1

        # Phase 1: Steps from workflow definitions (highest priority)
        for ws in workflow_steps:
            if sequence > max_steps:
                break
            step = PlanningStep(
                sequence=sequence,
                title=ws.get("step_name", f"Step {sequence}"),
                description=ws.get("description"),
                required_capabilities=[],
                evidence=[],
                explanation=PlanningExplanation(
                    reason="Step derived from approved workflow.",
                    source=f"workflow:{ws.get('workflow_id', 'unknown')}",
                ),
            )
            # Extract capabilities from step inputs
            for inp in ws.get("inputs", []):
                cap_name = inp.get("name", "")
                if cap_name and cap_name not in step.required_capabilities:
                    step.required_capabilities.append(cap_name)
            steps.append(step)
            sequence += 1

        # Phase 2: Steps from direct knowledge matches (if room remains)
        seen_names: set[str] = {s.title.lower() for s in steps}
        for match in matches:
            if sequence > max_steps:
                break
            obj_name = match.get("object_name", "")
            obj_type = match.get("object_type", "")

            if not obj_name or obj_name.lower() in seen_names:
                continue
            # Skip workflow/workflow_step types already consumed
            if obj_type in ("workflow", "workflow_step"):
                continue

            trust = match.get("trust_level")
            approval = match.get("approval_status")
            explanation_text = match.get("explanation", {})
            reason = explanation_text.get("reason", "") if isinstance(explanation_text, dict) else ""

            evidence_list: list[PlanningEvidence] = []
            for ev in match.get("evidence", []):
                evidence_list.append(PlanningEvidence(
                    evidence_type=ev.get("evidence_type", ""),
                    reference_id=ev.get("provenance_id"),
                    description=ev.get("path"),
                    trust_level=ev.get("trust_level"),
                ))

            step = PlanningStep(
                sequence=sequence,
                title=f"Address: {obj_name}",
                description=f"Knowledge ({obj_type}) relevant to objective.",
                required_capabilities=[obj_name] if obj_type == "capability" else [],
                evidence=evidence_list,
                risk_notes=f"Trust: {trust or 'unknown'}, Approval: {approval or 'unknown'}",
                explanation=PlanningExplanation(
                    reason=reason or f"Knowledge match for objective ({obj_type}).",
                    source=f"{obj_type}:{match.get('object_id', 'unknown')}",
                ),
            )
            seen_names.add(obj_name.lower())
            steps.append(step)
            sequence += 1

        # Phase 3: If no steps found, create a generic exploration step
        if not steps:
            steps.append(PlanningStep(
                sequence=1,
                title=f"Explore: {objective}",
                description="No existing knowledge found. Manual exploration recommended.",
                explanation=PlanningExplanation(
                    reason="No relevant knowledge found in registries.",
                ),
            ))

        return steps

    # --- Internal: Dependencies ---

    def _derive_dependencies(
        self,
        steps: list[PlanningStep],
        matches: list[dict[str, Any]],
    ) -> list[PlanningDependency]:
        """Derive dependencies between planning steps."""
        dependencies: list[PlanningDependency] = []

        # Sequential dependencies: each step depends on the prior step
        for i in range(1, len(steps)):
            dep = PlanningDependency(
                from_step_id=steps[i - 1].step_id,
                to_step_id=steps[i].step_id,
                dependency_type=DependencyType.REQUIRES,
                description=f"Step {steps[i].sequence} follows step {steps[i - 1].sequence}.",
            )
            dependencies.append(dep)

        return dependencies

    # --- Internal: Assumptions, risks, validations ---

    def _collect_assumptions(self, matches: list[dict[str, Any]]) -> list[str]:
        """Collect planning assumptions from knowledge matches."""
        assumptions: list[str] = []
        if matches:
            assumptions.append("Knowledge graph is current and complete for this domain.")
            # Check for trust levels
            trust_levels = {m.get("trust_level") for m in matches if m.get("trust_level")}
            if "candidate" in trust_levels:
                assumptions.append("Some knowledge is at candidate level and may not be validated.")
            if "founder_verified" in trust_levels or "human_verified" in trust_levels:
                assumptions.append("Plan includes human-verified knowledge.")
        else:
            assumptions.append("No existing knowledge found — plan is exploratory.")
        return assumptions

    def _collect_risks(self, matches: list[dict[str, Any]]) -> list[str]:
        """Collect planning risks from knowledge matches."""
        risks: list[str] = []

        # Check for deprecated or rejected knowledge
        for match in matches:
            approval = match.get("approval_status", "")
            if approval == "rejected":
                risks.append(f"Rejected knowledge referenced: {match.get('object_name', 'unknown')}")
            elif approval == "deprecated":
                risks.append(f"Deprecated knowledge referenced: {match.get('object_name', 'unknown')}")

        # Check for failure patterns
        failure_matches = [m for m in matches if m.get("object_type") == "failure_pattern"]
        if failure_matches:
            for fm in failure_matches:
                risks.append(f"Known failure pattern: {fm.get('object_name', 'unknown')}")

        if not risks:
            risks.append("No known failure patterns or rejected knowledge detected.")

        return risks

    def _collect_validations(self, matches: list[dict[str, Any]]) -> list[str]:
        """Collect required validations from knowledge matches."""
        validations: list[str] = []
        seen: set[str] = set()

        for match in matches:
            obj_type = match.get("object_type", "")
            obj_name = match.get("object_name", "")

            if obj_type == "capability" and obj_name not in seen:
                validations.append(f"Validate capability: {obj_name}")
                seen.add(obj_name)
            elif obj_type == "rule" and obj_name not in seen:
                validations.append(f"Validate rule: {obj_name}")
                seen.add(obj_name)

        if not validations:
            validations.append("Standard workflow validation required.")

        return validations

    # --- Internal: Evidence and explanations ---

    def _collect_evidence(self, matches: list[dict[str, Any]]) -> list[PlanningEvidence]:
        """Collect evidence references from knowledge matches."""
        evidence_refs: list[PlanningEvidence] = []
        seen_ids: set[str] = set()

        for match in matches:
            for ev in match.get("evidence", []):
                ref_id = ev.get("provenance_id", "")
                if ref_id and ref_id not in seen_ids:
                    seen_ids.add(ref_id)
                    evidence_refs.append(PlanningEvidence(
                        evidence_type=ev.get("evidence_type", ""),
                        reference_id=ref_id,
                        description=ev.get("path"),
                        trust_level=ev.get("trust_level"),
                    ))

        return evidence_refs

    def _generate_explanations(
        self,
        steps: list[PlanningStep],
        matches: list[dict[str, Any]],
    ) -> list[PlanningExplanation]:
        """Generate plan-level explanations."""
        explanations: list[PlanningExplanation] = []

        workflow_count = sum(1 for m in matches if m.get("object_type") in ("workflow", "workflow_step"))
        if workflow_count > 0:
            explanations.append(PlanningExplanation(
                reason=f"Plan incorporates {workflow_count} workflow-derived knowledge items.",
                source="workflow_registry",
            ))

        capability_count = sum(1 for m in matches if m.get("object_type") == "capability")
        if capability_count > 0:
            explanations.append(PlanningExplanation(
                reason=f"Plan references {capability_count} registered capabilities.",
                source="capability_registry",
            ))

        if not explanations:
            explanations.append(PlanningExplanation(
                reason="Plan generated from available knowledge graph.",
                source="knowledge_graph",
            ))

        return explanations

    # --- Internal: Persistence ---

    def _persist_plan(self, result: PlanningResult) -> None:
        """Persist a generated plan to the database."""
        with get_session(self._session_factory) as session:
            row = CapabilityPlanRow(
                plan_id=result.plan_id,
                objective=result.objective,
                status=result.status.value,
                steps_json=json.dumps([s.to_dict() for s in result.steps], default=str),
                dependencies_json=json.dumps([d.to_dict() for d in result.dependencies], default=str),
                assumptions_json=json.dumps(result.assumptions, default=str),
                risks_json=json.dumps(result.risks, default=str),
                validations_json=json.dumps(result.validations, default=str),
                evidence_json=json.dumps([e.to_dict() for e in result.evidence_references], default=str),
                explanations_json=json.dumps([e.to_dict() for e in result.explanations], default=str),
                metadata_json=json.dumps(result.metadata, default=str),
                step_count=len(result.steps),
                created_at=result.created_at,
                updated_at=result.updated_at,
            )
            session.add(row)

    def _row_to_result(self, row: CapabilityPlanRow) -> PlanningResult:
        """Convert a database row to a PlanningResult."""
        steps_data = _safe_json_loads(row.steps_json, [])
        deps_data = _safe_json_loads(row.dependencies_json, [])
        assumptions = _safe_json_loads(row.assumptions_json, [])
        risks = _safe_json_loads(row.risks_json, [])
        validations = _safe_json_loads(row.validations_json, [])
        evidence_data = _safe_json_loads(row.evidence_json, [])
        explanations_data = _safe_json_loads(row.explanations_json, [])
        metadata = _safe_json_loads(row.metadata_json, {})

        steps = [
            PlanningStep(
                step_id=s.get("step_id", ""),
                sequence=s.get("sequence", 0),
                title=s.get("title", ""),
                description=s.get("description"),
                required_capabilities=s.get("required_capabilities", []),
                evidence=[
                    PlanningEvidence(
                        evidence_type=e.get("evidence_type", ""),
                        reference_id=e.get("reference_id"),
                        description=e.get("description"),
                        trust_level=e.get("trust_level"),
                    )
                    for e in s.get("evidence", [])
                ],
                risk_notes=s.get("risk_notes"),
                explanation=PlanningExplanation(
                    reason=s["explanation"]["reason"],
                    source=s["explanation"].get("source"),
                ) if s.get("explanation") else None,
            )
            for s in steps_data
        ]

        dependencies = [
            PlanningDependency(
                dependency_id=d.get("dependency_id", ""),
                from_step_id=d.get("from_step_id", ""),
                to_step_id=d.get("to_step_id", ""),
                dependency_type=d.get("dependency_type", "requires"),
                description=d.get("description"),
            )
            for d in deps_data
        ]

        evidence_refs = [
            PlanningEvidence(
                evidence_type=e.get("evidence_type", ""),
                reference_id=e.get("reference_id"),
                description=e.get("description"),
                trust_level=e.get("trust_level"),
            )
            for e in evidence_data
        ]

        explanations = [
            PlanningExplanation(
                reason=e.get("reason", ""),
                source=e.get("source"),
            )
            for e in explanations_data
        ]

        return PlanningResult(
            plan_id=row.plan_id,
            objective=row.objective,
            status=row.status,
            assumptions=assumptions,
            steps=steps,
            dependencies=dependencies,
            risks=risks,
            validations=validations,
            evidence_references=evidence_refs,
            explanations=explanations,
            metadata=metadata,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json_loads(value: str | None, default: Any) -> Any:
    """Safely parse JSON, returning default on failure."""
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
