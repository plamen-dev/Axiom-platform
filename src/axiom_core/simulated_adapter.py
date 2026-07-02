"""Simulated Product Adapter (Adapter 000) — in-memory BIM model.

Adapter 000 validates capabilities without any live product. It exposes the
same client surface as :class:`axiom_core.pipe_client.PipeClient`
(``is_available()`` / ``execute_tool(...)`` returning a
:class:`~axiom_core.schemas.ToolResult`), so it can be injected into
:func:`axiom_core.automation_bridge.execute_capability_via_bridge` and
produce real bridge evidence bundles — with every result stamped
``adapter: simulated-000`` so simulated evidence can never be mistaken for
live product evidence.

Supported capabilities (mirroring Adapter 001's contract):

- ``CreateGrids`` — grid system per the registry schema.
- ``CreateLevels`` — levels with uniform or variable elevations.
- ``InventoryModel`` — **summary mode only**: counts + category breakdown,
  never a full parameter dump (same safety doctrine as live inventory).
- ``SetParameterValue`` — category-constrained, text/writable/instance
  parameters only, hard cap of 5 elements, preview by default; apply
  requires ``Mode: "apply"``.

The adapter owns no evidence or promotion logic; it only executes against
its in-memory model. Nothing here talks to Revit.
"""

from __future__ import annotations

import string
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from axiom_core.schemas import StepStatus, ToolResult

ADAPTER_ID = "simulated-000"

MAX_SET_PARAMETER_ELEMENTS = 5


# ---------------------------------------------------------------------------
# In-memory model
# ---------------------------------------------------------------------------


@dataclass
class SimElement:
    """One element in the simulated model."""

    element_id: str
    category: str
    name: str
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)


def _text_param(value: str) -> dict[str, Any]:
    return {
        "value": value,
        "data_type": "Text",
        "is_read_only": False,
        "is_instance": True,
    }


def _seed_elements() -> list[SimElement]:
    """Deterministic starter model: a few walls and doors with a Comments
    text parameter, plus one read-only parameter to exercise safety gates."""
    elements: list[SimElement] = []
    for i in range(1, 4):
        elements.append(
            SimElement(
                element_id=f"sim-wall-{i}",
                category="Walls",
                name=f"Basic Wall {i}",
                parameters={
                    "Comments": _text_param(""),
                    "Mark": _text_param(f"W-{i}"),
                    "Type Name": {
                        "value": "Generic - 200mm",
                        "data_type": "Text",
                        "is_read_only": True,
                        "is_instance": False,
                    },
                },
            )
        )
    for i in range(1, 3):
        elements.append(
            SimElement(
                element_id=f"sim-door-{i}",
                category="Doors",
                name=f"Single Door {i}",
                parameters={
                    "Comments": _text_param(""),
                    "Mark": _text_param(f"D-{i}"),
                },
            )
        )
    return elements


class SimulatedModel:
    """The in-memory model Adapter 000 executes against."""

    def __init__(self, seed: bool = True) -> None:
        self.elements: list[SimElement] = _seed_elements() if seed else []
        self._counter = 0

    def new_id(self, prefix: str) -> str:
        self._counter += 1
        return f"sim-{prefix}-{self._counter}"

    def by_category(self, category: str) -> list[SimElement]:
        return [e for e in self.elements if e.category == category]

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for element in self.elements:
            counts[element.category] = counts.get(element.category, 0) + 1
        return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Capability executors
# ---------------------------------------------------------------------------


def _grid_names(horizontal: int, vertical: int) -> tuple[list[str], list[str]]:
    numeric = [str(i) for i in range(1, horizontal + 1)]
    letters = list(string.ascii_uppercase)
    alpha: list[str] = []
    for i in range(vertical):
        name = letters[i % 26]
        if i >= 26:
            name = f"{name}{i // 26}"
        alpha.append(name)
    return numeric, alpha


def _run_create_grids(
    model: SimulatedModel, args: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any], list[str]]:
    horizontal = int(args.get("HorizontalCount", 5))
    vertical = int(args.get("VerticalCount", 5))
    spacing = float(args.get("SpacingFeet", 30.0))
    errors: list[str] = []
    if horizontal < 0 or vertical < 0:
        errors.append("grid counts must be >= 0")
    if spacing <= 0:
        errors.append("SpacingFeet must be > 0")
    if errors:
        return [], [], {}, errors

    numeric, alpha = _grid_names(horizontal, vertical)
    created: list[str] = []
    for index, name in enumerate(numeric):
        element_id = model.new_id("grid")
        model.elements.append(
            SimElement(
                element_id=element_id,
                category="Grids",
                name=name,
                parameters={
                    "Name": _text_param(name),
                    "Offset": {
                        "value": index * spacing,
                        "data_type": "Number",
                        "is_read_only": False,
                        "is_instance": True,
                    },
                },
            )
        )
        created.append(element_id)
    for index, name in enumerate(alpha):
        element_id = model.new_id("grid")
        model.elements.append(
            SimElement(
                element_id=element_id,
                category="Grids",
                name=name,
                parameters={
                    "Name": _text_param(name),
                    "Offset": {
                        "value": index * spacing,
                        "data_type": "Number",
                        "is_read_only": False,
                        "is_instance": True,
                    },
                },
            )
        )
        created.append(element_id)
    output = {
        "grid_count": len(created),
        "numeric_names": numeric,
        "alphabetic_names": alpha,
        "spacing_feet": spacing,
    }
    return created, [], output, []


def _run_create_levels(
    model: SimulatedModel, args: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        count = int(args["LevelCount"])
    except (KeyError, TypeError, ValueError):
        return [], [], {}, ["LevelCount is required and must be an integer"]
    if count < 1:
        return [], [], {}, ["LevelCount must be >= 1"]

    start = float(args.get("StartElevationFeet", 0))
    names = args.get("LevelNames")
    variable = args.get("VariableElevationsFeet")
    floor_to_floor = args.get("FloorToFloorFeet")

    if names is not None and len(names) != count:
        errors.append("LevelNames length must match LevelCount")
    if variable is not None and len(variable) != count:
        errors.append("VariableElevationsFeet length must match LevelCount")
    if variable is None and floor_to_floor is None:
        errors.append(
            "either FloorToFloorFeet or VariableElevationsFeet is required"
        )
    elif variable is None and float(floor_to_floor) <= 0:
        errors.append("FloorToFloorFeet must be > 0")
    if errors:
        return [], [], {}, errors

    if variable is not None:
        elevations = [float(v) for v in variable]
    else:
        step = float(floor_to_floor)
        elevations = [start + i * step for i in range(count)]

    created: list[str] = []
    level_records: list[dict[str, Any]] = []
    for index, elevation in enumerate(elevations):
        name = (
            names[index] if names is not None else f"Level {index + 1}"
        )
        element_id = model.new_id("level")
        model.elements.append(
            SimElement(
                element_id=element_id,
                category="Levels",
                name=name,
                parameters={
                    "Name": _text_param(name),
                    "Elevation": {
                        "value": elevation,
                        "data_type": "Number",
                        "is_read_only": False,
                        "is_instance": True,
                    },
                },
            )
        )
        created.append(element_id)
        level_records.append({"name": name, "elevation_feet": elevation})
    output = {"level_count": len(created), "levels": level_records}
    return created, [], output, []


def _run_inventory_model(
    model: SimulatedModel, args: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any], list[str]]:
    """Summary mode only: counts + category breakdown, no parameter dump."""
    category_filter = args.get("CategoryFilter")
    counts = model.category_counts()
    if category_filter:
        wanted = set(category_filter)
        counts = {c: n for c, n in counts.items() if c in wanted}
    output = {
        "mode": "summary",
        "element_count": sum(counts.values()),
        "category_count": len(counts),
        "categories": counts,
        "source_model": "simulated-000-in-memory",
    }
    return [], [], output, []


def _run_set_parameter_value(
    model: SimulatedModel, args: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any], list[str]]:
    errors: list[str] = []
    category = str(args.get("Category", "")).strip()
    parameter = str(args.get("ParameterName", "")).strip()
    element_count = args.get("ElementCount")
    mode = str(args.get("Mode", "preview")).strip().lower()
    if "Value" not in args:
        errors.append("Value is required")
    value = str(args.get("Value", ""))
    if not category:
        errors.append("Category is required (no whole-model edits)")
    if not parameter:
        errors.append("ParameterName is required")
    if not isinstance(element_count, int) or element_count < 1:
        errors.append("ElementCount is required and must be >= 1")
    elif element_count > MAX_SET_PARAMETER_ELEMENTS:
        errors.append(
            f"ElementCount exceeds hard cap of {MAX_SET_PARAMETER_ELEMENTS}"
        )
    if mode not in ("preview", "apply"):
        errors.append("Mode must be 'preview' or 'apply'")
    if errors:
        return [], [], {}, errors

    candidates = model.by_category(category)
    if len(candidates) < element_count:
        return [], [], {}, [
            f"category '{category}' has {len(candidates)} elements, "
            f"{element_count} requested"
        ]

    targets = candidates[:element_count]
    for element in targets:
        param = element.parameters.get(parameter)
        if param is None:
            errors.append(
                f"{element.element_id}: parameter '{parameter}' not found"
            )
        elif param.get("data_type") != "Text":
            errors.append(
                f"{element.element_id}: '{parameter}' is not a Text parameter"
            )
        elif param.get("is_read_only"):
            errors.append(
                f"{element.element_id}: '{parameter}' is read-only"
            )
        elif not param.get("is_instance"):
            errors.append(
                f"{element.element_id}: '{parameter}' is not an instance "
                "parameter"
            )
    if errors:
        return [], [], {}, errors

    previews = [
        {
            "element_id": e.element_id,
            "current_value": e.parameters[parameter]["value"],
            "new_value": value,
        }
        for e in targets
    ]
    modified: list[str] = []
    if mode == "apply":
        for element in targets:
            element.parameters[parameter]["value"] = value
            modified.append(element.element_id)
    output = {
        "mode": mode,
        "category": category,
        "parameter_name": parameter,
        "element_count": len(targets),
        "previews": previews,
        "applied": mode == "apply",
    }
    return [], modified, output, []


_EXECUTORS = {
    "CreateGrids": _run_create_grids,
    "CreateLevels": _run_create_levels,
    "InventoryModel": _run_inventory_model,
    "SetParameterValue": _run_set_parameter_value,
}

SUPPORTED_CAPABILITIES = tuple(sorted(_EXECUTORS))


# ---------------------------------------------------------------------------
# PipeClient-compatible adapter client
# ---------------------------------------------------------------------------


class SimulatedPipeClient:
    """Adapter 000 client with the same surface as ``PipeClient``.

    Inject into ``execute_capability_via_bridge(pipe_client=...)`` to drive
    capabilities against the in-memory model and produce real bridge
    evidence bundles stamped ``adapter: simulated-000``.
    """

    def __init__(self, model: SimulatedModel | None = None) -> None:
        self.model = model if model is not None else SimulatedModel()

    def is_available(self) -> bool:
        return True

    def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        simulate: bool = False,
        step_id: UUID | None = None,
        transaction_name: str | None = None,
    ) -> ToolResult:
        args = dict(args or {})
        step_id = step_id or uuid4()
        started = time.monotonic()

        executor = _EXECUTORS.get(tool_name)
        if executor is None:
            return ToolResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                errors=[
                    f"Adapter 000 does not support capability '{tool_name}' "
                    f"(supported: {', '.join(SUPPORTED_CAPABILITIES)})"
                ],
                output_data={"adapter": ADAPTER_ID},
            )

        if simulate:
            created, modified, output, errors = [], [], {}, []
        else:
            created, modified, output, errors = executor(self.model, args)

        duration_ms = int((time.monotonic() - started) * 1000)
        output = dict(output)
        output["adapter"] = ADAPTER_ID
        output["simulated_model"] = True
        return ToolResult(
            step_id=step_id,
            status=StepStatus.FAILED if errors else StepStatus.SUCCESS,
            created_ids=created,
            modified_ids=modified,
            errors=errors,
            duration_ms=duration_ms,
            output_data=output,
        )
