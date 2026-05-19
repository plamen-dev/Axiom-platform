"""ExecutionAgent — sends deterministic commands to Revit executor.

No reasoning. Takes a Plan with ToolSteps and sends each step
to the C# capability via the named pipe bridge.
"""

from axiom_core.pipe_client import PipeClient
from axiom_core.schemas import Plan, StepStatus, ToolResult


class ExecutionAgent:
    """Executes Plan steps via the pipe bridge. No reasoning, just dispatch."""

    def __init__(self, pipe_client: PipeClient):
        self.pipe_client = pipe_client

    def execute_plan(self, plan: Plan, simulate: bool = False) -> list[ToolResult]:
        """Execute all steps in a plan sequentially.

        Stops on first failure.
        """
        results: list[ToolResult] = []

        for step in plan.steps:
            step.status = StepStatus.RUNNING

            result = self.pipe_client.execute_tool(
                tool_name=step.tool_name,
                args=step.args,
                simulate=simulate,
                step_id=step.step_id,
                transaction_name=f"Axiom_{step.tool_name}",
            )

            results.append(result)
            step.status = result.status

            if result.status == StepStatus.FAILED:
                break

        return results
