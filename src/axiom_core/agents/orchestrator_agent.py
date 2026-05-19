"""OrchestratorAgent — receives prompt, chooses workflow, coordinates.

This is the entry point for the vertical slice.
Receives a user prompt, resolves it to a capability call,
delegates execution to ExecutionAgent, and logs via TelemetryAgent.

Selects capability through registry metadata.
"""

from typing import Optional
from uuid import uuid4

from axiom_core.agents.execution_agent import ExecutionAgent
from axiom_core.agents.telemetry_agent import TelemetryAgent
from axiom_core.capability_registry import CapabilityRegistry, get_default_registry
from axiom_core.prompt_resolver import resolve_prompt
from axiom_core.schemas import (
    Plan,
    PlanStatus,
    StepStatus,
    ToolStep,
)


class OrchestratorAgent:
    """Receives a prompt, resolves it, coordinates execution and logging."""

    def __init__(
        self,
        execution_agent: ExecutionAgent,
        telemetry_agent: TelemetryAgent,
        registry: Optional[CapabilityRegistry] = None,
    ):
        self.execution_agent = execution_agent
        self.telemetry_agent = telemetry_agent
        self.registry = registry or get_default_registry()

    def handle_prompt(self, prompt: str, simulate: bool = False) -> dict:
        """Process a user prompt end-to-end.

        Returns a dict with:
            resolved: ResolvedPrompt or None
            plan: Plan
            results: list[ToolResult]
            status: "SUCCESS" | "FAILED" | "UNRESOLVED"
        """
        self.telemetry_agent.log_event(
            event_type="prompt_received",
            data={"prompt": prompt, "simulate": simulate},
        )

        # Step 1: Resolve prompt to capability call
        resolved = resolve_prompt(prompt)
        if resolved is None:
            self.telemetry_agent.log_event(
                event_type="prompt_unresolved",
                data={"prompt": prompt},
            )
            return {
                "resolved": None,
                "plan": None,
                "results": [],
                "status": "UNRESOLVED",
            }

        # Step 1a: Check if clarification is needed
        if resolved.status == "clarification_needed":
            self.telemetry_agent.log_event(
                event_type="clarification_needed",
                data={
                    "capability": resolved.capability_name,
                    "clarification": resolved.clarification_message,
                    "prompt": prompt,
                },
            )
            return {
                "resolved": resolved,
                "plan": None,
                "results": [],
                "status": "CLARIFICATION_NEEDED",
                "clarification": resolved.clarification_message,
            }

        self.telemetry_agent.log_event(
            event_type="prompt_resolved",
            data={
                "capability": resolved.capability_name,
                "params": resolved.params,
                "assumptions": resolved.assumptions,
            },
        )

        # Step 1b: Verify capability is registered and usable
        cap_meta = self.registry.get(resolved.capability_name)
        if cap_meta is None:
            self.telemetry_agent.log_event(
                event_type="capability_not_registered",
                data={"capability": resolved.capability_name},
            )
            return {
                "resolved": resolved,
                "plan": None,
                "results": [],
                "status": "FAILED",
                "error": f"Capability not registered: {resolved.capability_name}",
            }

        if cap_meta.status == "planned":
            self.telemetry_agent.log_event(
                event_type="capability_not_implemented",
                data={
                    "capability": resolved.capability_name,
                    "status": cap_meta.status,
                },
            )
            return {
                "resolved": resolved,
                "plan": None,
                "results": [],
                "status": "FAILED",
                "error": (
                    f"Unsupported capability: {resolved.capability_name} "
                    f"is not implemented yet."
                ),
            }

        # Step 2: Build a minimal plan
        job_id = uuid4()
        step = ToolStep(
            sequence=0,
            tool_name=resolved.capability_name,
            args=resolved.params,
        )

        plan = Plan(
            job_id=job_id,
            steps=[step],
            status=PlanStatus.DRAFT,
        )

        # Step 3: Execute via ExecutionAgent
        results = self.execution_agent.execute_plan(plan, simulate=simulate)

        # Step 4: Determine overall status
        failed = any(r.status == StepStatus.FAILED for r in results)
        plan.status = PlanStatus.FAILED if failed else PlanStatus.COMPLETED

        self.telemetry_agent.log_event(
            event_type="plan_completed",
            data={
                "plan_id": str(plan.plan_id),
                "status": plan.status.value,
                "results_count": len(results),
            },
        )

        return {
            "resolved": resolved,
            "plan": plan,
            "results": results,
            "status": "SUCCESS" if not failed else "FAILED",
        }
