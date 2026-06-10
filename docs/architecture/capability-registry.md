# Capability Registry

## Purpose

The enhanced capability registry catalogs Axiom capabilities with rich metadata
suitable for agent-addressable surfaces. Each capability carries:

- Identity (ID, display name, version)
- Risk classification
- Mode support (dry-run, execute, validate, rollback)
- Requirements (active Revit document)
- Input schema (JSON Schema)
- Validation contract (pass checks)
- Expected artifact outputs

## Schema

```json
{
  "capability_id": "grid_creation",
  "display_name": "Grid Creation",
  "version": "0.1",
  "risk_level": "medium",
  "dry_run_supported": true,
  "execute_supported": true,
  "validation_supported": true,
  "rollback_supported": false,
  "requires_active_revit_document": true,
  "input_schema": {},
  "validation_contract": {},
  "artifact_outputs": []
}
```

## Registered capabilities

| ID               | Display Name     | Risk   | Dry-run | Execute | Validate |
|------------------|------------------|--------|---------|---------|----------|
| `grid_creation`  | Grid Creation    | medium | Yes     | Yes     | Yes      |

## Adding capabilities

```python
from axiom_core.server_tools import (
    AxiomCapabilityRegistry,
    EnhancedCapabilityMeta,
    get_enhanced_registry,
)

registry = get_enhanced_registry()
registry.register(
    EnhancedCapabilityMeta(
        capability_id="my_capability",
        display_name="My Capability",
        version="0.1",
        risk_level="low",
        dry_run_supported=True,
        execute_supported=False,  # reflect actual state
        input_schema={...},
    )
)
```

## Relationship to existing registry

The existing `axiom_core.capability_registry.CapabilityRegistry` (PR #22+) holds
the foundational catalog with parameter schemas and simulate support. The
enhanced registry in `axiom_core.server_tools` adds MCP-oriented metadata
(validation contract, artifact outputs, risk level, rollback support). They are
separate registries today; a future PR may unify them.
