"""Tests for agents — vertical slice end-to-end."""

import sys

import pytest
from axiom_core.agents.execution_agent import ExecutionAgent
from axiom_core.agents.orchestrator_agent import OrchestratorAgent
from axiom_core.agents.telemetry_agent import TelemetryAgent
from axiom_core.pipe_client import PipeClient
from axiom_core.schemas import PlanStatus, StepStatus


class TestExecutionAgent:
    def test_execute_plan_mock(self):
        pipe_client = PipeClient(pipe_name="axiom_test")
        agent = ExecutionAgent(pipe_client=pipe_client)

        from uuid import uuid4

        from axiom_core.schemas import Plan, ToolStep

        plan = Plan(
            job_id=uuid4(),
            steps=[
                ToolStep(
                    sequence=0,
                    tool_name="CreateGrids",
                    args={
                        "HorizontalCount": 5,
                        "VerticalCount": 5,
                        "SpacingFeet": 30.0,
                        "Length": 0,
                        "Naming": "Default",
                    },
                )
            ],
        )

        results = agent.execute_plan(plan, simulate=True)
        assert len(results) == 1
        assert results[0].status == StepStatus.SUCCESS

    def test_unknown_tool_fails(self):
        pipe_client = PipeClient(pipe_name="axiom_test")
        agent = ExecutionAgent(pipe_client=pipe_client)

        from uuid import uuid4

        from axiom_core.schemas import Plan, ToolStep

        plan = Plan(
            job_id=uuid4(),
            steps=[
                ToolStep(
                    sequence=0,
                    tool_name="UnknownTool",
                    args={},
                )
            ],
        )

        results = agent.execute_plan(plan, simulate=True)
        assert len(results) == 1
        assert results[0].status == StepStatus.FAILED


class TestTelemetryAgent:
    def test_log_and_retrieve_events(self):
        agent = TelemetryAgent()
        agent.log_event("test_event", {"key": "value"})
        agent.log_event("other_event", {"x": 1})

        all_events = agent.get_events()
        assert len(all_events) == 2

        filtered = agent.get_events(event_type="test_event")
        assert len(filtered) == 1
        assert filtered[0].data["key"] == "value"


class TestOrchestratorAgent:
    def test_end_to_end_grid_prompt(self):
        pipe_client = PipeClient(pipe_name="axiom_test")
        execution_agent = ExecutionAgent(pipe_client=pipe_client)
        telemetry_agent = TelemetryAgent()
        orchestrator = OrchestratorAgent(
            execution_agent=execution_agent,
            telemetry_agent=telemetry_agent,
        )

        result = orchestrator.handle_prompt(
            "Create 10 vertical gridlines, 50' long, spaced 10' apart",
            simulate=True,
        )

        assert result["status"] == "SUCCESS"
        assert result["resolved"] is not None
        assert result["resolved"].capability_name == "CreateGrids"
        assert result["plan"].status == PlanStatus.COMPLETED
        assert len(result["results"]) == 1
        assert result["results"][0].status == StepStatus.SUCCESS

        events = telemetry_agent.get_events()
        assert len(events) >= 3  # prompt_received, prompt_resolved, plan_completed

    def test_unresolvable_prompt(self):
        pipe_client = PipeClient(pipe_name="axiom_test")
        execution_agent = ExecutionAgent(pipe_client=pipe_client)
        telemetry_agent = TelemetryAgent()
        orchestrator = OrchestratorAgent(
            execution_agent=execution_agent,
            telemetry_agent=telemetry_agent,
        )

        result = orchestrator.handle_prompt("Do something random")

        assert result["status"] == "UNRESOLVED"
        assert result["resolved"] is None

    def test_orchestrator_uses_registry(self):
        """OrchestratorAgent has a registry with CreateGrids registered."""
        pipe_client = PipeClient(pipe_name="axiom_test")
        execution_agent = ExecutionAgent(pipe_client=pipe_client)
        telemetry_agent = TelemetryAgent()
        orchestrator = OrchestratorAgent(
            execution_agent=execution_agent,
            telemetry_agent=telemetry_agent,
        )

        assert orchestrator.registry.is_registered("CreateGrids")
        meta = orchestrator.registry.get("CreateGrids")
        assert meta.status == "validated"

    def test_planned_capability_returns_not_implemented(self):
        """Prompt resolving to a 'planned' capability should fail gracefully."""
        from axiom_core.capability_registry import CapabilityMetadata, CapabilityRegistry

        registry = CapabilityRegistry()
        registry.register(
            CapabilityMetadata(
                name="CreateGrids",
                description="grids",
                status="planned",
            )
        )

        pipe_client = PipeClient(pipe_name="axiom_test")
        execution_agent = ExecutionAgent(pipe_client=pipe_client)
        telemetry_agent = TelemetryAgent()
        orchestrator = OrchestratorAgent(
            execution_agent=execution_agent,
            telemetry_agent=telemetry_agent,
            registry=registry,
        )

        result = orchestrator.handle_prompt(
            "Create 5 grids spaced 30 ft apart",
            simulate=True,
        )

        assert result["status"] == "FAILED"
        assert "not implemented yet" in result.get("error", "")

    def test_ambiguous_rows_columns_returns_clarification(self):
        """BUG-001: rows/columns without 'grid' returns CLARIFICATION_NEEDED."""
        pipe_client = PipeClient(pipe_name="axiom_test")
        execution_agent = ExecutionAgent(pipe_client=pipe_client)
        telemetry_agent = TelemetryAgent()
        orchestrator = OrchestratorAgent(
            execution_agent=execution_agent,
            telemetry_agent=telemetry_agent,
        )

        result = orchestrator.handle_prompt(
            "Create 5 rows and 10 columns spaced 10 ft apart",
            simulate=True,
        )

        assert result["status"] == "CLARIFICATION_NEEDED"
        assert "clarification" in result
        assert "gridlines" in result["clarification"].lower()
        assert result["results"] == []


class TestPipeClient:
    @pytest.mark.skipif(sys.platform == "win32", reason="Linux-specific: pipe unavailability test")
    def test_mock_mode_on_linux(self):
        client = PipeClient(pipe_name="axiom_test")
        assert not client.is_available()

    def test_mock_execute_grids(self):
        client = PipeClient(pipe_name="axiom_test")
        result = client.execute_tool(
            tool_name="CreateGrids",
            args={
                "HorizontalCount": 5,
                "VerticalCount": 5,
                "SpacingFeet": 30.0,
            },
            simulate=True,
        )
        assert result.status == StepStatus.SUCCESS
        assert len(result.created_ids) == 10
        assert result.output_data["mock"] is True

    def test_mock_execute_both_counts_zero_fails(self):
        """BUG-002: mock must reject both counts = 0, matching C# validation."""
        client = PipeClient(pipe_name="axiom_test")
        result = client.execute_tool(
            tool_name="CreateGrids",
            args={
                "HorizontalCount": 0,
                "VerticalCount": 0,
                "SpacingFeet": 30.0,
            },
            simulate=True,
        )
        assert result.status == StepStatus.FAILED
        assert any("count > 0" in e.lower() or "count" in e.lower() for e in result.errors)

    def test_mock_execute_single_orientation_zero_succeeds(self):
        """One orientation count=0 is valid when the other is >0."""
        client = PipeClient(pipe_name="axiom_test")
        result = client.execute_tool(
            tool_name="CreateGrids",
            args={
                "HorizontalCount": 5,
                "VerticalCount": 0,
                "SpacingFeet": 10.0,
            },
            simulate=True,
        )
        assert result.status == StepStatus.SUCCESS
        assert len(result.created_ids) == 5

    def test_mock_execute_unknown_tool(self):
        client = PipeClient(pipe_name="axiom_test")
        result = client.execute_tool(
            tool_name="UnknownCapability",
            args={},
            simulate=True,
        )
        assert result.status == StepStatus.FAILED
