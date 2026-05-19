"""Capability registry — catalogs available capabilities with metadata.

The registry is the menu of executable tools. It is referenceable by both
OrchestratorAgent and ExecutionAgent, but owned by neither.

Agents coordinate. Capabilities execute. Services implement.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CapabilityMetadata:
    """Metadata describing a single capability."""

    name: str
    description: str
    parameter_schema: dict = field(default_factory=dict)
    supports_simulate: bool = True
    requires_revit_document: bool = True
    status: str = "validated"


class CapabilityRegistry:
    """Registry of available capabilities and their metadata.

    The registry catalogs tools. It does not execute them.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityMetadata] = {}

    def register(self, metadata: CapabilityMetadata) -> None:
        """Register a capability by its metadata."""
        self._capabilities[metadata.name] = metadata

    def get(self, name: str) -> Optional[CapabilityMetadata]:
        """Look up capability metadata by name."""
        return self._capabilities.get(name)

    def list_all(self) -> list[CapabilityMetadata]:
        """Return all registered capability metadata entries."""
        return list(self._capabilities.values())

    def list_names(self) -> list[str]:
        """Return names of all registered capabilities."""
        return list(self._capabilities.keys())

    def is_registered(self, name: str) -> bool:
        """Check if a capability name is registered."""
        return name in self._capabilities


# ---------------------------------------------------------------------------
# Default registry instance with validated capabilities
# ---------------------------------------------------------------------------

_CREATE_GRIDS_SCHEMA = {
    "type": "object",
    "properties": {
        "HorizontalCount": {
            "type": "integer",
            "description": "Number of vertical (numeric) grid lines.",
            "default": 5,
            "minimum": 0,
        },
        "VerticalCount": {
            "type": "integer",
            "description": "Number of horizontal (alphabetic) grid lines.",
            "default": 5,
            "minimum": 0,
        },
        "SpacingFeet": {
            "type": "number",
            "description": "Uniform spacing between grid lines in feet.",
            "default": 30.0,
            "exclusiveMinimum": 0,
        },
        "Length": {
            "type": "number",
            "description": "Explicit line length in feet. 0 = derived from extents.",
            "default": 0,
            "minimum": 0,
        },
    },
    "required": ["HorizontalCount", "VerticalCount", "SpacingFeet"],
}

_CREATE_LEVELS_SCHEMA = {
    "type": "object",
    "properties": {
        "LevelCount": {
            "type": "integer",
            "description": "Number of levels to create.",
            "minimum": 1,
        },
        "FloorToFloorFeet": {
            "type": "number",
            "description": "Uniform floor-to-floor height in feet. Not required when VariableElevationsFeet is provided.",
            "exclusiveMinimum": 0,
        },
        "StartElevationFeet": {
            "type": "number",
            "description": "Elevation of the first level in feet. May be negative (basements).",
            "default": 0,
        },
        "LevelNames": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional custom names for levels. Length must match LevelCount.",
        },
        "VariableElevationsFeet": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Explicit elevation for each level. Overrides FloorToFloorFeet. Length must match LevelCount.",
        },
    },
    "required": ["LevelCount"],
}


def get_default_registry() -> CapabilityRegistry:
    """Build the default registry with all validated/planned capabilities."""
    registry = CapabilityRegistry()

    registry.register(
        CapabilityMetadata(
            name="CreateGrids",
            description="Creates a grid system with vertical (numeric) and horizontal (alphabetic) grid lines.",
            parameter_schema=_CREATE_GRIDS_SCHEMA,
            supports_simulate=True,
            requires_revit_document=True,
            status="validated",
        )
    )

    registry.register(
        CapabilityMetadata(
            name="CreateLevels",
            description="Creates building levels at specified elevations.",
            parameter_schema=_CREATE_LEVELS_SCHEMA,
            supports_simulate=True,
            requires_revit_document=True,
            status="validated",
        )
    )

    registry.register(
        CapabilityMetadata(
            name="InventoryModel",
            description="Scans the active model and returns a structured inventory of all elements and their parameters. Read-only.",
            parameter_schema={
                "type": "object",
                "properties": {
                    "CategoryFilter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional category filter. Null = all categories.",
                    },
                    "IncludeTypeParameters": {
                        "type": "boolean",
                        "description": "Include element type parameters.",
                        "default": True,
                    },
                    "IncludeInstanceParameters": {
                        "type": "boolean",
                        "description": "Include instance parameters.",
                        "default": True,
                    },
                },
            },
            supports_simulate=True,
            requires_revit_document=True,
            status="validated",
        )
    )

    return registry
