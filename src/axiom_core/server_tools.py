"""Axiom Capability Registry and MCP-Compatible Server Surface v1.

Exposes Axiom capabilities through a local tool surface whose schemas and names
map cleanly to a future MCP server. The surface is usable today as plain Python
function calls; network/JSON-RPC transport can be added later without changing
the tool contracts.

Tool names::

    axiom_server_diagnose
    axiom_server_get_log_path
    axiom_server_get_version
    axiom_capabilities_list
    axiom_capabilities_describe
    axiom_runs_create_dry_run
    axiom_runs_list_history
    axiom_runs_get_artifacts
    axiom_model_health_get_latest    (optional, depends on PR #32)
    axiom_capability_readiness_get   (optional, depends on PR #32)

All tool functions return plain ``dict`` that is JSON-serializable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from axiom_core.run_spine import (
    RunContext,
    artifacts_root,
    audit_log_path,
    execute_run,
    list_runs,
    runs_root,
)

# ---------------------------------------------------------------------------
# Enhanced capability registry
# ---------------------------------------------------------------------------

AXIOM_VERSION = "0.1.0"


@dataclass
class EnhancedCapabilityMeta:
    """Rich metadata for a capability, compatible with MCP tool description."""

    capability_id: str
    display_name: str
    version: str = "0.1"
    risk_level: str = "medium"
    dry_run_supported: bool = True
    execute_supported: bool = True
    validation_supported: bool = True
    rollback_supported: bool = False
    requires_active_revit_document: bool = True
    input_schema: dict[str, Any] = field(default_factory=dict)
    validation_contract: dict[str, Any] = field(default_factory=dict)
    artifact_outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "display_name": self.display_name,
            "version": self.version,
            "risk_level": self.risk_level,
            "dry_run_supported": self.dry_run_supported,
            "execute_supported": self.execute_supported,
            "validation_supported": self.validation_supported,
            "rollback_supported": self.rollback_supported,
            "requires_active_revit_document": self.requires_active_revit_document,
            "input_schema": self.input_schema,
            "validation_contract": self.validation_contract,
            "artifact_outputs": self.artifact_outputs,
        }


class AxiomCapabilityRegistry:
    """Enhanced registry of Axiom capabilities with MCP-compatible metadata."""

    def __init__(self) -> None:
        self._capabilities: dict[str, EnhancedCapabilityMeta] = {}

    def register(self, meta: EnhancedCapabilityMeta) -> None:
        self._capabilities[meta.capability_id] = meta

    def get(self, capability_id: str) -> EnhancedCapabilityMeta | None:
        return self._capabilities.get(capability_id)

    def list_all(self) -> list[EnhancedCapabilityMeta]:
        return list(self._capabilities.values())

    def list_ids(self) -> list[str]:
        return sorted(self._capabilities.keys())

    def is_registered(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    @property
    def count(self) -> int:
        return len(self._capabilities)


# ---------------------------------------------------------------------------
# Default registry with GridCreation
# ---------------------------------------------------------------------------


_GRID_CREATION_INPUT_SCHEMA: dict[str, Any] = {
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


def get_enhanced_registry() -> AxiomCapabilityRegistry:
    """Build the enhanced registry with all capabilities."""
    registry = AxiomCapabilityRegistry()

    registry.register(
        EnhancedCapabilityMeta(
            capability_id="grid_creation",
            display_name="Grid Creation",
            version="0.1",
            risk_level="medium",
            dry_run_supported=True,
            execute_supported=True,
            validation_supported=True,
            rollback_supported=False,
            requires_active_revit_document=True,
            input_schema=_GRID_CREATION_INPUT_SCHEMA,
            validation_contract={
                "pass_checks": [
                    "grid_count_matches_input",
                    "grid_spacing_matches_input",
                    "no_duplicate_grid_names",
                ],
            },
            artifact_outputs=[
                "run_metadata.json",
                "command_input.json",
                "execution_result.json",
                "external_calls.json",
                "artifact_manifest.json",
                "run_summary.md",
            ],
        )
    )

    return registry


# Module-level singleton
_registry: AxiomCapabilityRegistry | None = None


def _get_registry() -> AxiomCapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = get_enhanced_registry()
    return _registry


def reset_registry() -> None:
    """Reset the module-level registry to the default state.

    Intended for test isolation.  After calling this, the singleton is
    cleared and will be re-built from ``get_enhanced_registry()`` on the
    next tool-function call.
    """
    global _registry
    _registry = None


# ---------------------------------------------------------------------------
# Tool functions — MCP-compatible surface
# ---------------------------------------------------------------------------


def axiom_server_diagnose() -> dict[str, Any]:
    """Return server health diagnostics."""
    registry = _get_registry()
    audit_path = audit_log_path()
    return {
        "status": "healthy",
        "axiom_version": AXIOM_VERSION,
        "artifact_root": str(artifacts_root()),
        "audit_log_path": str(audit_path),
        "registered_capability_count": registry.count,
        "external_calls_made": False,
    }


def axiom_server_get_log_path() -> dict[str, Any]:
    """Return the path to the command audit log."""
    return {
        "audit_log_path": str(audit_log_path()),
        "exists": audit_log_path().is_file(),
    }


def axiom_server_get_version() -> dict[str, Any]:
    """Return the Axiom server version."""
    return {
        "axiom_version": AXIOM_VERSION,
        "api_version": "1.0",
    }


def axiom_capabilities_list() -> dict[str, Any]:
    """List all registered capabilities."""
    registry = _get_registry()
    return {
        "capabilities": [
            {
                "capability_id": c.capability_id,
                "display_name": c.display_name,
                "version": c.version,
                "risk_level": c.risk_level,
                "dry_run_supported": c.dry_run_supported,
                "execute_supported": c.execute_supported,
            }
            for c in registry.list_all()
        ],
        "count": registry.count,
    }


def axiom_capabilities_describe(capability_id: str) -> dict[str, Any]:
    """Describe a capability by ID. Returns error if not found."""
    registry = _get_registry()
    meta = registry.get(capability_id)
    if meta is None:
        return {
            "error": True,
            "error_type": "CapabilityNotFound",
            "error_message": f"Unknown capability: '{capability_id}'",
            "available_capabilities": registry.list_ids(),
        }
    return {
        "error": False,
        "capability": meta.to_dict(),
    }


def axiom_runs_create_dry_run(
    capability_id: str,
    input_data: dict[str, Any] | None = None,
    source: str = "cli",
    model_path: str | None = None,
    revit_version: str | None = None,
    active_view: str | None = None,
    active_view_type: str | None = None,
) -> dict[str, Any]:
    """Create a dry-run for a capability through the run spine.

    Validates capability exists, creates PR #31 run artifacts, calls the
    dry-run path, returns run ID + status + artifact path.
    """
    registry = _get_registry()
    meta = registry.get(capability_id)
    if meta is None:
        return {
            "error": True,
            "error_type": "CapabilityNotFound",
            "error_message": f"Unknown capability: '{capability_id}'",
            "available_capabilities": registry.list_ids(),
        }

    if not meta.dry_run_supported:
        return {
            "error": True,
            "error_type": "DryRunNotSupported",
            "error_message": f"Dry-run not supported for '{capability_id}'.",
        }

    ctx = RunContext(
        capability=meta.display_name,
        mode="dry_run",
        source=source,
        risk_level=meta.risk_level,
        model_path=model_path,
        revit_version=revit_version,
        active_view=active_view,
        active_view_type=active_view_type,
        input_data=input_data or {},
    )

    result = execute_run(ctx)

    return {
        "error": False,
        "run_id": result.run_id,
        "status": result.status,
        "artifact_path": result.artifact_path,
        "capability_id": capability_id,
        "mode": "dry_run",
    }


def axiom_runs_list_history(
    limit: int = 50,
    capability: str | None = None,
) -> dict[str, Any]:
    """Return recent local runs from the artifact store.

    The *capability* filter accepts either a ``capability_id``
    (e.g. ``"grid_creation"``) or the display name
    (e.g. ``"Grid Creation"``). Matching is case-insensitive.
    """
    fetch_limit = 10_000 if capability else limit
    all_runs = list_runs(limit=fetch_limit)

    if capability:
        cap_lower = capability.lower().replace("_", " ")
        all_runs = [
            r for r in all_runs
            if r.get("capability", "").lower().replace("_", " ") == cap_lower
        ][:limit]

    return {
        "runs": all_runs,
        "count": len(all_runs),
        "limit": limit,
    }


def axiom_runs_get_artifacts(run_id: str) -> dict[str, Any]:
    """Return artifact manifest and file paths for a run ID."""
    runs_dir = runs_root()
    run_folder = (runs_dir / run_id).resolve()

    if not run_folder.is_relative_to(runs_dir.resolve()):
        return {
            "error": True,
            "error_type": "InvalidRunId",
            "error_message": f"Invalid run_id: '{run_id}'",
        }

    if not run_folder.is_dir():
        return {
            "error": True,
            "error_type": "RunNotFound",
            "error_message": f"Run folder not found: '{run_id}'",
        }

    manifest_path = run_folder / "artifact_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = None
    else:
        manifest = None

    files = sorted(
        str(f.relative_to(run_folder))
        for f in run_folder.rglob("*")
        if f.is_file()
    )

    return {
        "error": False,
        "run_id": run_id,
        "artifact_path": str(run_folder),
        "manifest": manifest,
        "files": files,
        "file_count": len(files),
    }


# ---------------------------------------------------------------------------
# Optional tools (depend on PR #32 model_health module)
# ---------------------------------------------------------------------------


def axiom_model_health_get_latest() -> dict[str, Any]:
    """Get the most recent model health report from artifacts.

    Scans run history for the latest ModelHealth run and returns its
    health data. Returns error if no health runs exist.
    """
    runs = list_runs(limit=100)
    health_runs = [
        r for r in runs if r.get("capability") == "ModelHealth"
    ]

    if not health_runs:
        return {
            "error": True,
            "error_type": "NoHealthRunsFound",
            "error_message": "No model health runs found in artifacts.",
        }

    latest = health_runs[0]
    run_folder = runs_root() / latest["run_id"]
    health_path = run_folder / "axiom_model_health.json"

    if not health_path.is_file():
        return {
            "error": True,
            "error_type": "HealthFileNotFound",
            "error_message": f"Health file missing for run '{latest['run_id']}'.",
        }

    try:
        health_data = json.loads(health_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "error": True,
            "error_type": "HealthFileError",
            "error_message": str(exc),
        }

    if "model_path" in health_data and "model_path_redacted" in health_data:
        health_data["model_path"] = health_data["model_path_redacted"]

    return {
        "error": False,
        "run_id": latest["run_id"],
        "health": health_data,
    }


def axiom_capability_readiness_get(
    capability: str | None = None,
) -> dict[str, Any]:
    """Get the most recent capability readiness data from artifacts.

    If ``capability`` is given, returns readiness for that capability only.
    Otherwise returns all capabilities from the latest health run.
    """
    runs = list_runs(limit=100)
    health_runs = [
        r for r in runs if r.get("capability") == "ModelHealth"
    ]

    if not health_runs:
        return {
            "error": True,
            "error_type": "NoHealthRunsFound",
            "error_message": "No model health runs found in artifacts.",
        }

    latest = health_runs[0]
    run_folder = runs_root() / latest["run_id"]
    readiness_path = run_folder / "axiom_capability_readiness.json"

    if not readiness_path.is_file():
        return {
            "error": True,
            "error_type": "ReadinessFileNotFound",
            "error_message": f"Readiness file missing for run '{latest['run_id']}'.",
        }

    try:
        readiness_data = json.loads(readiness_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "error": True,
            "error_type": "ReadinessFileError",
            "error_message": str(exc),
        }

    if capability:
        caps = [
            c for c in readiness_data.get("capabilities", [])
            if c.get("capability", "").lower() == capability.lower()
        ]
        if not caps:
            return {
                "error": True,
                "error_type": "CapabilityNotInReport",
                "error_message": (
                    f"Capability '{capability}' not found in latest readiness "
                    f"report (run '{latest['run_id']}')."
                ),
            }
        return {
            "error": False,
            "run_id": latest["run_id"],
            "readiness": caps[0],
        }

    return {
        "error": False,
        "run_id": latest["run_id"],
        "readiness": readiness_data,
    }
