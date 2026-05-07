"""MCP Layer - Tool protocol boundary for Revit operations.

This is a mock implementation that simulates Revit tool execution.
The real implementation will connect to the Revit add-in via the MCP protocol.
"""

import time
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from axiom_core.schemas import StepStatus, ToolResult


class ToolDefinition(BaseModel):
    """Definition of a tool available in the MCP layer."""

    name: str
    description: str
    category: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    requires_transaction: bool = True
    is_read_only: bool = False
    min_revit_version: int = 2020
    max_revit_version: int = 2030


class ToolExecutionContext(BaseModel):
    """Context for tool execution."""

    execution_id: UUID = Field(default_factory=uuid4)
    simulate: bool = True
    revit_version: int = 2023
    document_path: Optional[str] = None
    transaction_name: Optional[str] = None


class MCPLayer:
    """Mock MCP Layer for simulating Revit tool execution.

    In production, this will be replaced with actual Revit API calls
    via the MCP protocol to the Revit add-in.
    """

    def __init__(self, revit_version: int = 2023):
        self.revit_version = revit_version
        self.tools: dict[str, ToolDefinition] = {}
        self.tool_handlers: dict[str, Callable] = {}
        self.execution_log: list[dict[str, Any]] = []
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of mock tools."""

        self.register_tool(
            ToolDefinition(
                name="ValidateInputs",
                description="Validate job inputs before execution",
                category="validation",
                args_schema={"job_id": "string"},
                requires_transaction=False,
                is_read_only=True,
            ),
            self._mock_validate_inputs,
        )

        self.register_tool(
            ToolDefinition(
                name="CreateProject",
                description="Create a new Revit project from template",
                category="project",
                args_schema={
                    "project_name": "string",
                    "project_number": "string",
                    "revit_version": "integer",
                    "template_path": "string?",
                },
                requires_transaction=True,
            ),
            self._mock_create_project,
        )

        self.register_tool(
            ToolDefinition(
                name="LoadArchLink",
                description="Load an architectural link into the project",
                category="link",
                args_schema={
                    "link_path": "string",
                    "link_index": "integer",
                },
                requires_transaction=True,
            ),
            self._mock_load_arch_link,
        )

        self.register_tool(
            ToolDefinition(
                name="SetCoordinates",
                description="Set project coordinate system",
                category="project",
                args_schema={"coordinate_mode": "string"},
                requires_transaction=True,
            ),
            self._mock_set_coordinates,
        )

        self.register_tool(
            ToolDefinition(
                name="CreateScopeBox",
                description="Create a scope box in the project",
                category="scope_box",
                args_schema={
                    "name": "string",
                    "copy_from_arch": "boolean",
                    "levels": "array",
                },
                requires_transaction=True,
            ),
            self._mock_create_scope_box,
        )

        self.register_tool(
            ToolDefinition(
                name="CreateViews",
                description="Create views based on view type code",
                category="view",
                args_schema={
                    "view_type_code": "string",
                    "levels": "array",
                },
                requires_transaction=True,
            ),
            self._mock_create_views,
        )

        self.register_tool(
            ToolDefinition(
                name="CreateSheets",
                description="Create sheets from sheet list",
                category="sheet",
                args_schema={"sheet_list_path": "string"},
                requires_transaction=True,
            ),
            self._mock_create_sheets,
        )

        self.register_tool(
            ToolDefinition(
                name="RunBackgroundDiagnostic",
                description="Run background diagnostic analysis",
                category="diagnostic",
                args_schema={},
                requires_transaction=False,
                is_read_only=True,
            ),
            self._mock_run_diagnostic,
        )

        self.register_tool(
            ToolDefinition(
                name="GenerateReport",
                description="Generate execution report",
                category="report",
                args_schema={"job_id": "string"},
                requires_transaction=False,
                is_read_only=True,
            ),
            self._mock_generate_report,
        )

    def register_tool(self, definition: ToolDefinition, handler: Callable) -> None:
        """Register a tool with its handler."""
        self.tools[definition.name] = definition
        self.tool_handlers[definition.name] = handler

    def get_tool_catalog(self) -> list[ToolDefinition]:
        """Get all available tools."""
        return list(self.tools.values())

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self.tools.get(name)

    def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        simulate: bool = True,
    ) -> ToolResult:
        """Execute a tool with the given arguments."""
        start_time = time.time()

        if tool_name not in self.tools:
            return ToolResult(
                step_id=uuid4(),
                status=StepStatus.FAILED,
                errors=[f"Unknown tool: {tool_name}"],
                duration_ms=0,
            )

        handler = self.tool_handlers[tool_name]

        context = ToolExecutionContext(
            simulate=simulate,
            revit_version=self.revit_version,
            transaction_name=f"Axiom_{tool_name}",
        )

        self.execution_log.append(
            {
                "tool_name": tool_name,
                "args": args,
                "simulate": simulate,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        try:
            result = handler(args, context)
            result.duration_ms = int((time.time() - start_time) * 1000)
            return result
        except Exception as e:
            return ToolResult(
                step_id=uuid4(),
                status=StepStatus.FAILED,
                errors=[str(e)],
                duration_ms=int((time.time() - start_time) * 1000),
            )

    def _mock_validate_inputs(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock validation of inputs."""
        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            output_data={"validation_result": "PASS", "simulated": context.simulate},
        )

    def _mock_create_project(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock project creation."""
        project_name = args.get("project_name", "Untitled")
        project_number = args.get("project_number", "0000")

        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=["doc_001"],
            output_data={
                "project_path": f"/projects/{project_number}_{project_name}.rvt",
                "document_id": "doc_001",
                "simulated": context.simulate,
            },
        )

    def _mock_load_arch_link(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock loading architectural link."""
        link_path = args.get("link_path", "")
        link_index = args.get("link_index", 0)

        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=[f"link_{link_index:03d}"],
            output_data={
                "link_id": f"link_{link_index:03d}",
                "link_name": link_path.split("/")[-1] if link_path else f"Link_{link_index}",
                "simulated": context.simulate,
            },
        )

    def _mock_set_coordinates(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock setting coordinates."""
        mode = args.get("coordinate_mode", "project")

        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            output_data={
                "coordinate_status": "SET",
                "mode": mode,
                "simulated": context.simulate,
            },
        )

    def _mock_create_scope_box(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock scope box creation."""
        name = args.get("name", "Scope Box")

        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=[f"sb_{name.replace(' ', '_').lower()}"],
            output_data={
                "scope_box_id": f"sb_{name.replace(' ', '_').lower()}",
                "name": name,
                "simulated": context.simulate,
            },
        )

    def _mock_create_views(self, args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """Mock view creation."""
        view_type = args.get("view_type_code", "E - General")
        levels = args.get("levels", ["Level 1"])

        view_ids = [f"view_{view_type.replace(' ', '_')}_{level}" for level in levels]
        if not levels:
            view_ids = [f"view_{view_type.replace(' ', '_')}_all"]

        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=view_ids,
            output_data={
                "view_ids": view_ids,
                "view_type": view_type,
                "simulated": context.simulate,
            },
        )

    def _mock_create_sheets(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock sheet creation."""
        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=["sheet_E001", "sheet_E002", "sheet_M001"],
            output_data={
                "sheet_ids": ["sheet_E001", "sheet_E002", "sheet_M001"],
                "count": 3,
                "simulated": context.simulate,
            },
        )

    def _mock_run_diagnostic(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock background diagnostic."""
        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=["view_DIAG_Background"],
            output_data={
                "diagnostic_view_id": "view_DIAG_Background",
                "anomalies": [],
                "anomaly_count": 0,
                "simulated": context.simulate,
            },
        )

    def _mock_generate_report(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Mock report generation."""
        return ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            output_data={
                "report": {
                    "status": "SUCCESS",
                    "steps_completed": 10,
                    "warnings": 0,
                    "errors": 0,
                },
                "simulated": context.simulate,
            },
        )
