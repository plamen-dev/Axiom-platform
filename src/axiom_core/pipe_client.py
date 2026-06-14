"""Named pipe client for communicating with the C# Revit add-in.

Sends JSON-RPC 2.0 requests to the AxiomPipeServer running inside Revit
and returns structured ToolResult responses.

On non-Windows platforms, falls back to mock mode for development and testing.
When simulate=True, always uses mock mode regardless of platform.
In real mode (no --simulate), reports detailed errors if pipe is unavailable.
"""

import json
import struct
import sys
from typing import Any, Optional
from uuid import UUID, uuid4

from axiom_core.schemas import StepStatus, ToolResult


def _alpha_name(index: int) -> str:
    """A-Z, AA-AZ, BA-BZ, … — mirrors C# GridCreationService.GetAlphabeticName."""
    name = ""
    i = index + 1
    while i > 0:
        remainder = (i - 1) % 26
        name = chr(65 + remainder) + name
        i = (i - 1) // 26
    return name


# Error code mapping for structured C# responses
_ERROR_CODES = {
    -32600: "Invalid JSON-RPC request",
    -32601: "Capability not registered in ToolRegistry",
    -32602: "Invalid capability parameters",
    -32603: "Internal server error in AxiomPipeServer",
    -32001: "GridCapability validation failed",
    -32002: "Revit transaction failed",
    -32003: "Revit API exception",
}


class PipeClient:
    """Client for the Axiom named pipe bridge to Revit."""

    def __init__(self, pipe_name: str = "axiom"):
        self.pipe_name = pipe_name
        self._pipe_path = rf"\\.\pipe\{pipe_name}"
        self._is_windows = sys.platform == "win32"

    def is_available(self) -> bool:
        """Check if the pipe server is listening (Windows only)."""
        if not self._is_windows:
            return False
        try:
            import ctypes

            invalid_handle = ctypes.c_void_p(-1).value

            handle = ctypes.windll.kernel32.CreateFileW(
                self._pipe_path,
                0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                0,
                None,
                3,  # OPEN_EXISTING
                0,
                None,
            )
            if handle == invalid_handle or handle == 0:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False

    def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        simulate: bool = False,
        step_id: Optional[UUID] = None,
        transaction_name: Optional[str] = None,
    ) -> ToolResult:
        """Send a tool execution request to the C# add-in via named pipe.

        When simulate=True, always uses mock mode (no pipe/Revit needed).
        In real mode (simulate=False):
          - Non-Windows: returns FAILED with platform diagnostic
          - Windows + pipe unavailable: returns FAILED with server diagnostic
          - Windows + pipe available: sends request over pipe
        """
        request_id = str(step_id or uuid4())

        # Simulate mode never needs the pipe — always mock
        if simulate:
            return self._mock_execute(request_id, tool_name, args, simulate)

        # Real mode: require Windows + pipe
        if not self._is_windows:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe unavailable: named pipes require Windows. "
                    f"Current platform: {sys.platform}. "
                    f"Use --simulate for mock mode on non-Windows."
                ],
            )

        if not self.is_available():
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe connection failed: {self._pipe_path} not found. "
                    f"Ensure Revit 2024 is running and AxiomPipeServer.Start() "
                    f"has been called in App.OnStartup. "
                    f"Use --simulate to test without Revit."
                ],
            )

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "execute_tool",
            "params": {
                "tool_name": tool_name,
                "args_json": json.dumps(args),
                "simulate": simulate,
                "transaction_name": transaction_name or f"Axiom_{tool_name}",
            },
        }

        return self._send_request(request, request_id)

    def _send_request(self, request: dict, request_id: str) -> ToolResult:
        """Send request over named pipe and parse response."""
        try:
            import win32file  # type: ignore[import-not-found]

            handle = win32file.CreateFile(
                self._pipe_path,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )

            try:
                request_bytes = json.dumps(request).encode("utf-8")
                length_prefix = struct.pack("<I", len(request_bytes))

                win32file.WriteFile(handle, length_prefix + request_bytes)

                # Read length prefix
                _, length_data = win32file.ReadFile(handle, 4)
                response_length = struct.unpack("<I", length_data)[0]

                # Read response body
                _, response_data = win32file.ReadFile(handle, response_length)
            finally:
                win32file.CloseHandle(handle)

            response = json.loads(response_data.decode("utf-8"))

            if "error" in response and response["error"]:
                error_obj = response["error"]
                code = error_obj.get("code", 0)
                message = error_obj.get("message", "Unknown server error")
                detail = _ERROR_CODES.get(code, "")
                error_parts = [f"C# AxiomPipeServer error (code {code}): {message}"]
                if detail:
                    error_parts.append(f"Category: {detail}")
                data = error_obj.get("data")
                if data:
                    error_parts.append(f"Detail: {data}")
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=error_parts,
                )

            result_data = response.get("result", {})
            status = (
                StepStatus.SUCCESS if result_data.get("status") == "SUCCESS" else StepStatus.FAILED
            )

            return ToolResult(
                step_id=UUID(request_id),
                status=status,
                created_ids=result_data.get("created_ids", []),
                warnings=result_data.get("warnings", []),
                errors=result_data.get("errors", []),
                duration_ms=result_data.get("duration_ms", 0),
                output_data=result_data.get("output_data", {}),
            )

        except ImportError:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    "Pipe connection failed: pywin32 not installed. " "Run: pip install pywin32"
                ],
            )
        except FileNotFoundError:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe connection failed: {self._pipe_path} does not exist. "
                    f"AxiomPipeServer is not running in Revit."
                ],
            )
        except PermissionError:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe connection failed: access denied to {self._pipe_path}. "
                    f"Check that Revit is running with sufficient permissions."
                ],
            )
        except TimeoutError:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe connection timed out: {self._pipe_path}. "
                    f"AxiomPipeServer may be busy processing another request."
                ],
            )
        except json.JSONDecodeError as e:
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Invalid response from AxiomPipeServer: not valid JSON. " f"Parse error: {e}"
                ],
            )
        except Exception as e:
            exc_type = type(e).__name__
            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.FAILED,
                errors=[
                    f"Pipe communication error ({exc_type}): {e}. "
                    f"Pipe: {self._pipe_path}. "
                    f"Check that AxiomPipeServer is running in Revit."
                ],
            )

    def _mock_execute(
        self,
        request_id: str,
        tool_name: str,
        args: dict[str, Any],
        simulate: bool,
    ) -> ToolResult:
        """Mock execution for development/testing when Revit is not available."""
        if tool_name == "CreateGrids":
            h_count = args.get("HorizontalCount", 0)
            v_count = args.get("VerticalCount", 0)
            spacing = args.get("SpacingFeet", 0)
            h_spacings = args.get("HorizontalSpacingsFeet")
            v_spacings = args.get("VerticalSpacingsFeet")

            # Validate at least one orientation has count > 0
            if h_count <= 0 and v_count <= 0:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=[
                        "At least one grid orientation must have count > 0. "
                        "Both HorizontalCount and VerticalCount are 0."
                    ],
                )

            # Validate variable spacing count
            if h_spacings and h_count > 1 and len(h_spacings) != h_count - 1:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=[
                        f"HorizontalSpacingsFeet has {len(h_spacings)} values "
                        f"but HorizontalCount is {h_count} "
                        f"(expected {h_count - 1} spacings)."
                    ],
                )
            if v_spacings and v_count > 1 and len(v_spacings) != v_count - 1:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=[
                        f"VerticalSpacingsFeet has {len(v_spacings)} values "
                        f"but VerticalCount is {v_count} "
                        f"(expected {v_count - 1} spacings)."
                    ],
                )

            # Validate positive values
            if h_spacings and any(s <= 0 for s in h_spacings):
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["All HorizontalSpacingsFeet values must be positive."],
                )
            if v_spacings and any(s <= 0 for s in v_spacings):
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["All VerticalSpacingsFeet values must be positive."],
                )

            span_x = sum(h_spacings) if h_spacings else (
                (h_count - 1) * spacing if h_count > 1 else 0
            )
            span_y = sum(v_spacings) if v_spacings else (
                (v_count - 1) * spacing if v_count > 1 else 0
            )

            created_ids = [f"grid_{i + 1}" for i in range(h_count)]
            created_ids += [f"grid_{_alpha_name(i)}" for i in range(v_count)]

            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.SUCCESS,
                created_ids=created_ids,
                duration_ms=50,
                output_data={
                    "simulated": True,
                    "mock": True,
                    "grid_count": h_count + v_count,
                    "span_x_feet": span_x,
                    "span_y_feet": span_y,
                },
            )

        if tool_name == "CreateLevels":
            count = args.get("LevelCount", 0)
            ftf = args.get("FloorToFloorFeet", 0)
            start = args.get("StartElevationFeet", 0.0)
            var_elevations = args.get("VariableElevationsFeet")
            level_names = args.get("LevelNames")

            # Validate count
            if count <= 0:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["LevelCount must be greater than 0."],
                )

            # Validate floor-to-floor (required when no variable elevations and count > 1)
            if var_elevations is None and count > 1 and ftf <= 0:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["FloorToFloorFeet must be provided and > 0 when creating multiple levels without variable elevations."],
                )

            # Validate variable elevations length
            if var_elevations is not None and len(var_elevations) != count:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=[
                        f"VariableElevationsFeet has {len(var_elevations)} "
                        f"values but LevelCount is {count}."
                    ],
                )

            # Validate level names length
            if level_names is not None and len(level_names) != count:
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=[
                        f"LevelNames has {len(level_names)} names "
                        f"but LevelCount is {count}."
                    ],
                )

            # Compute elevations
            if var_elevations is not None:
                elevations = list(var_elevations)
            else:
                elevations = [start + i * ftf for i in range(count)]

            # Check for duplicate elevations
            if len(set(elevations)) != len(elevations):
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["Duplicate elevation detected. Each level must have a unique elevation."],
                )

            # Check for duplicate names
            if level_names is not None and len(set(level_names)) != len(level_names):
                return ToolResult(
                    step_id=UUID(request_id),
                    status=StepStatus.FAILED,
                    errors=["Duplicate level name detected."],
                )

            # Generate mock IDs
            if level_names:
                created_ids = [f"level_{name}" for name in level_names]
            else:
                created_ids = [f"level_{i + 1}" for i in range(count)]

            return ToolResult(
                step_id=UUID(request_id),
                status=StepStatus.SUCCESS,
                created_ids=created_ids,
                duration_ms=50,
                output_data={
                    "simulated": True,
                    "mock": True,
                    "level_count": count,
                    "elevations_feet": elevations,
                },
            )

        if tool_name == "InventoryModel":
            return _mock_inventory(request_id)

        return ToolResult(
            step_id=UUID(request_id),
            status=StepStatus.FAILED,
            errors=[f"Unknown tool (mock mode): {tool_name}"],
        )


def _mock_inventory(request_id: str) -> ToolResult:
    """Return a representative mock inventory for simulation/testing."""
    mock_elements = [
        {
            "ElementId": 100001,
            "UniqueId": "mock-wall-001",
            "Category": "Walls",
            "ClassName": "Wall",
            "Name": "Basic Wall",
            "FamilyName": "Basic Wall",
            "TypeName": "Generic - 8\"",
            "LevelName": "Level 1",
            "LevelId": 300001,
            "WorksetName": "",
            "IsType": False,
            "Parameters": [
                {"Name": "Length", "StorageType": "Double", "ValueString": "20.0", "ValueDouble": 20.0, "ValueInt": None, "BuiltInParameterId": "CURVE_ELEM_LENGTH", "IsReadOnly": True, "ParameterGroup": "Constraints"},
                {"Name": "Area", "StorageType": "Double", "ValueString": "200.0", "ValueDouble": 200.0, "ValueInt": None, "BuiltInParameterId": "HOST_AREA_COMPUTED", "IsReadOnly": True, "ParameterGroup": "Dimensions"},
                {"Name": "Volume", "StorageType": "Double", "ValueString": "133.33", "ValueDouble": 133.33, "ValueInt": None, "BuiltInParameterId": "HOST_VOLUME_COMPUTED", "IsReadOnly": True, "ParameterGroup": "Dimensions"},
                {"Name": "Comments", "StorageType": "String", "ValueString": "", "ValueDouble": None, "ValueInt": None, "BuiltInParameterId": "ALL_MODEL_INSTANCE_COMMENTS", "IsReadOnly": False, "ParameterGroup": "Identity Data"},
            ],
        },
        {
            "ElementId": 100002,
            "UniqueId": "mock-door-001",
            "Category": "Doors",
            "ClassName": "FamilyInstance",
            "Name": "Single-Flush",
            "FamilyName": "Single-Flush",
            "TypeName": "36\" x 84\"",
            "LevelName": "Level 1",
            "LevelId": 300001,
            "WorksetName": "",
            "IsType": False,
            "Parameters": [
                {"Name": "Width", "StorageType": "Double", "ValueString": "3.0", "ValueDouble": 3.0, "ValueInt": None, "BuiltInParameterId": "DOOR_WIDTH", "IsReadOnly": True, "ParameterGroup": "Dimensions"},
                {"Name": "Height", "StorageType": "Double", "ValueString": "7.0", "ValueDouble": 7.0, "ValueInt": None, "BuiltInParameterId": "DOOR_HEIGHT", "IsReadOnly": True, "ParameterGroup": "Dimensions"},
                {"Name": "Mark", "StorageType": "String", "ValueString": "1", "ValueDouble": None, "ValueInt": None, "BuiltInParameterId": "ALL_MODEL_MARK", "IsReadOnly": False, "ParameterGroup": "Identity Data"},
            ],
        },
        {
            "ElementId": 100003,
            "UniqueId": "mock-level-001",
            "Category": "Levels",
            "ClassName": "Level",
            "Name": "Level 1",
            "FamilyName": "",
            "TypeName": "",
            "LevelName": "",
            "LevelId": 0,
            "WorksetName": "",
            "IsType": False,
            "Parameters": [
                {"Name": "Elevation", "StorageType": "Double", "ValueString": "0.0", "ValueDouble": 0.0, "ValueInt": None, "BuiltInParameterId": "LEVEL_ELEV", "IsReadOnly": False, "ParameterGroup": "Constraints"},
                {"Name": "Name", "StorageType": "String", "ValueString": "Level 1", "ValueDouble": None, "ValueInt": None, "BuiltInParameterId": "DATUM_TEXT", "IsReadOnly": False, "ParameterGroup": "Identity Data"},
            ],
        },
        {
            "ElementId": 100004,
            "UniqueId": "mock-level-002",
            "Category": "Levels",
            "ClassName": "Level",
            "Name": "Level 2",
            "FamilyName": "",
            "TypeName": "",
            "LevelName": "",
            "LevelId": 0,
            "WorksetName": "",
            "IsType": False,
            "Parameters": [
                {"Name": "Elevation", "StorageType": "Double", "ValueString": "10.0", "ValueDouble": 10.0, "ValueInt": None, "BuiltInParameterId": "LEVEL_ELEV", "IsReadOnly": False, "ParameterGroup": "Constraints"},
                {"Name": "Name", "StorageType": "String", "ValueString": "Level 2", "ValueDouble": None, "ValueInt": None, "BuiltInParameterId": "DATUM_TEXT", "IsReadOnly": False, "ParameterGroup": "Identity Data"},
            ],
        },
        {
            "ElementId": 200001,
            "UniqueId": "mock-walltype-001",
            "Category": "Walls",
            "ClassName": "WallType",
            "Name": "Generic - 8\"",
            "FamilyName": "Basic Wall",
            "TypeName": "Generic - 8\"",
            "LevelName": "",
            "LevelId": 0,
            "WorksetName": "",
            "IsType": True,
            "Parameters": [
                {"Name": "Width", "StorageType": "Double", "ValueString": "0.667", "ValueDouble": 0.667, "ValueInt": None, "BuiltInParameterId": "WALL_ATTR_WIDTH_PARAM", "IsReadOnly": True, "ParameterGroup": "Construction"},
                {"Name": "Function", "StorageType": "Integer", "ValueString": "Interior", "ValueDouble": None, "ValueInt": 1, "BuiltInParameterId": "FUNCTION_PARAM", "IsReadOnly": False, "ParameterGroup": "Construction"},
            ],
        },
    ]

    instance_count = sum(1 for e in mock_elements if not e["IsType"])
    type_count = sum(1 for e in mock_elements if e["IsType"])
    param_count = sum(len(e["Parameters"]) for e in mock_elements)

    return ToolResult(
        step_id=UUID(request_id),
        status=StepStatus.SUCCESS,
        duration_ms=120,
        output_data={
            "simulated": True,
            "mock": True,
            "source_model": "Mock Model - Architectural Sample",
            "element_count": instance_count,
            "type_count": type_count,
            "parameter_count": param_count,
            "elements": mock_elements,
        },
    )
